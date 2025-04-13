import argparse
import asyncio
import json
import logging
import os
import random  # Add import for random selection
import signal
import subprocess
import sys
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import requests
import uvicorn
import websockets
import yaml
from fastapi import (
    FastAPI,
    Header,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, HttpUrl

import protobufs.frames_pb2 as frames_pb2  # Import Protobuf definitions
from config.persona_utils import PersonaManager  # Import PersonaManager
from meetingbaas_pipecat.utils.logger import configure_logger
from scripts.meetingbaas_api import create_meeting_bot, leave_meeting_bot

# Configure logging with the prettier logger
logger = configure_logger()
logger.name = "meetingbaas-api"  # Set logger name after configuring

# Initialize PersonaManager to get available personas
persona_manager = PersonaManager()

# Set logging level for pipecat WebSocket client to WARNING to reduce noise
pipecat_ws_logger = logging.getLogger("pipecat.transports.network.websocket_client")
pipecat_ws_logger.setLevel(logging.WARNING)

# Check for local dev mode marker file (created by the parent process)
LOCAL_DEV_MODE = False
if os.path.exists(".local_dev_mode"):
    with open(".local_dev_mode", "r") as f:
        if f.read().strip().lower() == "true":
            LOCAL_DEV_MODE = True
            logger.info(
                "🚀 Starting in LOCAL_DEV_MODE (detected from .local_dev_mode file)"
            )


# Add this helper function before its first use
def convert_http_to_ws_url(url: str) -> str:
    """
    Convert HTTP(S) URL to WS(S) URL.

    Args:
        url: HTTP or HTTPS URL to convert

    Returns:
        WebSocket URL (ws:// or wss://)
    """
    if url.startswith("http://"):
        return "ws://" + url[7:]
    elif url.startswith("https://"):
        return "wss://" + url[8:]
    return url  # Already a WS URL or other format


# Get base URL from environment variable
BASE_URL = os.environ.get("BASE_URL", None)
if BASE_URL:
    logger.info(f"Using BASE_URL from environment: {BASE_URL}")
    # Convert http to ws or https to wss if needed
    WS_BASE_URL = convert_http_to_ws_url(BASE_URL)
else:
    logger.info(
        "No BASE_URL environment variable found. Will attempt auto-detection or use provided URLs."
    )
    WS_BASE_URL = None

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add these globals near the top of the file, after other globals
# Global variables for ngrok URL tracking
NGROK_URLS = []
NGROK_URL_INDEX = 0

# Global dictionary to store meeting details for each client
MEETING_DETAILS: Dict[
    str, Tuple[str, str, Optional[str], bool]
] = {}  # client_id -> (meeting_url, persona_name, meetingbaas_bot_id, enable_tools)
PIPECAT_PROCESSES: Dict[str, subprocess.Popen] = {}  # client_id -> process


class ConnectionRegistry:
    """Manages WebSocket connections for clients and Pipecat."""

    def __init__(self, logger=logger):
        self.active_connections: Dict[str, WebSocket] = {}
        self.pipecat_connections: Dict[str, WebSocket] = {}
        self.logger = logger

    async def connect(
        self, websocket: WebSocket, client_id: str, is_pipecat: bool = False
    ):
        """Register a new connection."""
        await websocket.accept()
        if is_pipecat:
            self.pipecat_connections[client_id] = websocket
            self.logger.info(f"Pipecat client {client_id} connected")
        else:
            self.active_connections[client_id] = websocket
            self.logger.info(f"Client {client_id} connected")

    async def disconnect(self, client_id: str, is_pipecat: bool = False):
        """Remove a connection and close the websocket."""
        try:
            if is_pipecat and client_id in self.pipecat_connections:
                websocket = self.pipecat_connections[client_id]
                await websocket.close(code=1000, reason="Bot disconnected")
                del self.pipecat_connections[client_id]
                self.logger.info(f"Pipecat client {client_id} disconnected")
            elif client_id in self.active_connections:
                websocket = self.active_connections[client_id]
                await websocket.close(code=1000, reason="Bot disconnected")
                del self.active_connections[client_id]
                self.logger.info(f"Client {client_id} disconnected")
        except Exception as e:
            self.logger.error(f"Error during disconnect for {client_id}: {e}")

    def get_client(self, client_id: str) -> Optional[WebSocket]:
        """Get a client connection by ID."""
        return self.active_connections.get(client_id)

    def get_pipecat(self, client_id: str) -> Optional[WebSocket]:
        """Get a Pipecat connection by ID."""
        return self.pipecat_connections.get(client_id)


class ProtobufConverter:
    """Handles conversion between raw audio and Protobuf frames."""

    def __init__(self, logger=logger, sample_rate: int = 24000, channels: int = 1):
        self.logger = logger
        self.sample_rate = sample_rate
        self.channels = channels

    def set_sample_rate(self, sample_rate: int):
        """Update the sample rate."""
        self.sample_rate = sample_rate
        self.logger.info(f"Updated ProtobufConverter sample rate to {sample_rate}")

    def raw_to_protobuf(self, raw_audio: bytes) -> bytes:
        """Convert raw audio data to a serialized Protobuf frame."""
        try:
            frame = frames_pb2.Frame()
            frame.audio.audio = raw_audio
            frame.audio.sample_rate = self.sample_rate
            frame.audio.num_channels = self.channels

            return frame.SerializeToString()
        except Exception as e:
            self.logger.error(f"Error converting raw audio to Protobuf: {str(e)}")
            raise

    def protobuf_to_raw(self, proto_data: bytes) -> Optional[bytes]:
        """Extract raw audio from a serialized Protobuf frame."""
        try:
            frame = frames_pb2.Frame()
            frame.ParseFromString(proto_data)

            if frame.HasField("audio"):
                return bytes(frame.audio.audio)
            return None
        except Exception as e:
            self.logger.error(f"Error extracting audio from Protobuf: {str(e)}")
            return None


class MessageRouter:
    """Routes messages between clients and Pipecat."""

    def __init__(
        self, registry: ConnectionRegistry, converter: ProtobufConverter, logger=logger
    ):
        self.registry = registry
        self.converter = converter
        self.logger = logger
        self.closing_clients = set()  # Track clients that are in the process of closing

    def mark_closing(self, client_id: str):
        """Mark a client as closing to prevent sending more data to it."""
        self.closing_clients.add(client_id)
        self.logger.debug(f"Marked client {client_id} as closing")

    async def send_binary(self, message: bytes, client_id: str):
        """Send binary data to a client."""
        if client_id in self.closing_clients:
            self.logger.debug(f"Skipping send to closing client {client_id}")
            return

        client = self.registry.get_client(client_id)
        if client:
            try:
                await client.send_bytes(message)
                self.logger.debug(f"Sent {len(message)} bytes to client {client_id}")
            except Exception as e:
                self.logger.debug(f"Error sending binary to client {client_id}: {e}")

    async def send_text(self, message: str, client_id: str):
        """Send text message to a specific client."""
        if client_id in self.closing_clients:
            self.logger.debug(f"Skipping send_text to closing client {client_id}")
            return

        client = self.registry.get_client(client_id)
        if client:
            try:
                await client.send_text(message)
                self.logger.debug(
                    f"Sent text message to client {client_id}: {message[:100]}..."
                )
            except Exception as e:
                self.logger.debug(f"Error sending text to client {client_id}: {e}")

    async def broadcast(self, message: str):
        """Broadcast text message to all clients."""
        for client_id, connection in self.registry.active_connections.items():
            if client_id not in self.closing_clients:
                try:
                    await connection.send_text(message)
                    self.logger.debug(f"Broadcast text message to client {client_id}")
                except Exception as e:
                    self.logger.debug(f"Error broadcasting to client {client_id}: {e}")

    async def send_to_pipecat(self, message: bytes, client_id: str):
        """Convert raw audio to Protobuf frame and send to Pipecat."""
        if client_id in self.closing_clients:
            self.logger.debug(
                f"Skipping send to Pipecat for closing client {client_id}"
            )
            return

        pipecat = self.registry.get_pipecat(client_id)
        if pipecat:
            try:
                serialized_frame = self.converter.raw_to_protobuf(message)
                await pipecat.send_bytes(serialized_frame)
                self.logger.debug(
                    f"Forwarded audio frame ({len(message)} bytes) to Pipecat for client {client_id}"
                )
            except Exception as e:
                self.logger.error(f"Error sending to Pipecat: {str(e)}")
                # If we get a connection closed error, mark client as closing
                if "close" in str(e).lower() or "closed" in str(e).lower():
                    self.mark_closing(client_id)

    async def send_from_pipecat(self, message: bytes, client_id: str):
        """Extract audio from Protobuf frame and send to client."""
        if client_id in self.closing_clients:
            self.logger.debug(
                f"Skipping send from Pipecat for closing client {client_id}"
            )
            return

        client = self.registry.get_client(client_id)
        if client:
            try:
                audio_data = self.converter.protobuf_to_raw(message)
                if audio_data:
                    await client.send_bytes(audio_data)
                    self.logger.debug(
                        f"Forwarded audio ({len(audio_data)} bytes) from Pipecat to client {client_id}"
                    )
            except Exception as e:
                self.logger.error(f"Error processing Pipecat message: {str(e)}")
                # If we get a connection closed error, mark client as closing
                if "close" in str(e).lower() or "closed" in str(e).lower():
                    self.mark_closing(client_id)


class BotRequest(BaseModel):
    meeting_url: str
    personas: Optional[List[str]] = None
    recorder_only: bool = False
    websocket_url: Optional[str] = None  # Now optional in all cases
    meeting_baas_api_key: str
    bot_image: Optional[str] = None
    entry_message: Optional[str] = None
    extra: Optional[Dict] = None
    streaming_audio_frequency: str = "24khz"  # Default to 24khz for higher quality
    enable_tools: bool = True  # Default to True to enable function tools by default


class LeaveBotRequest(BaseModel):
    """Request model for making a bot leave a meeting"""

    meeting_baas_api_key: str
    client_id: Optional[str] = None
    bot_id: Optional[str] = None


@app.get("/")
async def root():
    return {"message": "MeetingBaas Bot API is running"}


def load_ngrok_urls() -> List[str]:
    """
    Load ngrok URLs using the ngrok API.
    Returns a list of available ngrok URLs with preference for those pointing to port 8766.
    """
    urls = []
    priority_urls = []  # For tunnels pointing to port 8766

    try:
        # Try to fetch active ngrok tunnels from the API
        # ngrok web interface is usually available at localhost:4040
        logger.info("📡 Attempting to fetch ngrok tunnels from API...")
        response = requests.get("http://localhost:4040/api/tunnels")

        if response.status_code == 200:
            data = response.json()
            tunnels = data.get("tunnels", [])

            if tunnels:
                logger.info(f"🔍 Found {len(tunnels)} active ngrok tunnels")

                # Extract public URLs from tunnels
                for tunnel in tunnels:
                    public_url = tunnel.get("public_url")
                    config = tunnel.get("config", {})
                    addr = config.get("addr", "")

                    # Log the tunnel details for debugging
                    logger.info(f"🔍 Tunnel: {public_url} -> {addr}")

                    if public_url and public_url.startswith("https://"):
                        # Check if this tunnel points to port 8766
                        if addr and "8766" in addr:
                            logger.info(
                                f"✅ Found priority tunnel for port 8766: {public_url}"
                            )
                            priority_urls.append(public_url)
                        else:
                            urls.append(public_url)
                            logger.info(f"✅ Added regular ngrok tunnel: {public_url}")

                # Use priority URLs first, then regular ones
                if priority_urls:
                    logger.info(
                        f"✅ Using {len(priority_urls)} priority tunnels for port 8766"
                    )
                    urls = priority_urls + urls

                if not urls:
                    logger.warning("⚠️ Found tunnels but none with HTTPS protocol!")
            else:
                logger.warning(
                    "⚠️ No active ngrok tunnels found. Make sure ngrok is running with 'ngrok start --all'"
                )
        else:
            logger.warning(
                f"⚠️ Failed to get ngrok tunnels. Status code: {response.status_code}"
            )

    except Exception as e:
        logger.error(f"❌ Error accessing ngrok API: {e}")
        logger.info(
            "Make sure ngrok is running with 'ngrok start --all' before starting this server"
        )

    # Log the final URLs we're using
    if urls:
        logger.info(f"📡 Final ngrok URLs to be used: {urls}")
    else:
        logger.warning(
            "⚠️ No ngrok URLs found - websocket connections may not work properly!"
        )

    return urls


def _get_next_ngrok_url(urls: List[str]) -> Optional[str]:
    """
    Get the next available ngrok URL in a simpler way.
    Uses a global counter variable to track which URLs have been used.
    """
    global NGROK_URL_INDEX

    if not urls:
        return None

    # If we've used all URLs, return None
    if NGROK_URL_INDEX >= len(urls):
        logger.warning(f"⚠️ All {len(urls)} ngrok URLs have been assigned!")
        return None

    # Get the URL and increment the counter
    url = urls[NGROK_URL_INDEX]
    NGROK_URL_INDEX += 1

    # Convert http to ws for WebSocket
    url = convert_http_to_ws_url(url)

    logger.info(f"✅ Assigned ngrok WebSocket URL: {url} (URL #{NGROK_URL_INDEX})")
    return url


def determine_websocket_url(
    request_websocket_url: Optional[str], client_request: Request
) -> str:
    """
    Determine the appropriate WebSocket URL based on the environment and request.
    Uses a cached list of ngrok URLs when in local dev mode.
    """
    global NGROK_URLS

    # 1. If user explicitly provided a URL, use it (highest priority)
    if request_websocket_url:
        logger.info(f"Using user-provided WebSocket URL: {request_websocket_url}")
        return request_websocket_url

    # 2. If BASE_URL is set in environment, use it
    if WS_BASE_URL:
        logger.info(f"Using WebSocket URL from BASE_URL env: {WS_BASE_URL}")
        return WS_BASE_URL

    # 3. In local dev mode, try to use ngrok URL
    if LOCAL_DEV_MODE:
        logger.info(
            f"🔍 LOCAL_DEV_MODE is {LOCAL_DEV_MODE}, attempting to get ngrok URL"
        )

        # Use cached ngrok URLs instead of loading them every time
        if not NGROK_URLS:
            logger.info("Loading ngrok URLs (first request)")
            NGROK_URLS = load_ngrok_urls()

        if NGROK_URLS:
            logger.info(f"🔍 Found {len(NGROK_URLS)} ngrok URLs")

            # Get the next available URL
            ngrok_url = _get_next_ngrok_url(NGROK_URLS)
            if ngrok_url:
                logger.info(f"Using ngrok WebSocket URL: {ngrok_url}")
                return ngrok_url
            else:
                # If we're here, we've used all available ngrok URLs
                logger.warning("⚠️ All ngrok URLs have been used")
                # In local dev mode, we should require ngrok URLs
                raise HTTPException(
                    status_code=400,
                    detail="No more ngrok URLs available. Limited to 2 bots in local dev mode.",
                )
        else:
            logger.warning("⚠️ No ngrok URLs found despite being in LOCAL_DEV_MODE")

    # 4. Auto-detect from request (fallback, only for non-local environments)
    host = client_request.headers.get("host", "localhost:8766")
    scheme = client_request.headers.get("x-forwarded-proto", "http")
    websocket_scheme = "wss" if scheme == "https" else "ws"
    auto_url = f"{websocket_scheme}://{host}"
    logger.warning(
        f"⚠️ Using auto-detected WebSocket URL: {auto_url} - This may not work in production. "
        "Consider setting the BASE_URL environment variable."
    )
    return auto_url


@app.post("/run-bots")
async def run_bots(request: BotRequest, client_request: Request):
    """
    Create a bot directly via MeetingBaas API and establish WebSocket connection.
    The WebSocket URL is determined automatically if not provided.
    """
    # Validate required parameters
    if not request.meeting_url:
        return JSONResponse(
            content={"message": "Meeting URL is required", "status": "error"},
            status_code=400,
        )

    if not request.meeting_baas_api_key:
        return JSONResponse(
            content={"message": "MeetingBaas API key is required", "status": "error"},
            status_code=400,
        )

    # Log local dev mode status
    if LOCAL_DEV_MODE:
        logger.info("🔍 Running in LOCAL_DEV_MODE - will prioritize ngrok URLs")
    else:
        logger.info("🔍 Running in standard mode")

    # Determine WebSocket URL (works in all cases now)
    websocket_url = determine_websocket_url(request.websocket_url, client_request)

    logger.info(f"Starting bot for meeting {request.meeting_url}")
    logger.info(f"WebSocket URL: {websocket_url}")
    logger.info(f"Personas: {request.personas}")

    # Generate a unique client ID for this bot
    bot_client_id = str(uuid.uuid4())

    # Select the persona - use provided one or pick a random one
    if request.personas and len(request.personas) > 0:
        persona_name = request.personas[0]
        logger.info(f"Using specified persona: {persona_name}")
    else:
        # Get all available personas
        available_personas = list(persona_manager.personas.keys())
        if not available_personas:
            # Fallback to baas_onboarder if we somehow can't get the personas list
            persona_name = "baas_onboarder"
            logger.warning("No personas found, using fallback persona: baas_onboarder")
        else:
            # Select a random persona
            persona_name = random.choice(available_personas)
            logger.info(f"Randomly selected persona: {persona_name}")

    # Store meeting details for when the WebSocket connects
    MEETING_DETAILS[bot_client_id] = (
        request.meeting_url,
        persona_name,
        None,  # MeetingBaas bot ID will be set after creation
        request.enable_tools,
    )

    # Create bot directly through MeetingBaas API
    meetingbaas_bot_id = create_meeting_bot(
        meeting_url=request.meeting_url,
        websocket_url=websocket_url,
        bot_id=bot_client_id,
        persona_name=persona_name,
        api_key=request.meeting_baas_api_key,
        recorder_only=request.recorder_only,
        bot_image=request.bot_image,
        entry_message=request.entry_message,
        extra=request.extra,
        streaming_audio_frequency=request.streaming_audio_frequency,
    )

    if meetingbaas_bot_id:
        # Start the Pipecat process for this bot
        pipecat_websocket_url = f"ws://localhost:8766/pipecat/{bot_client_id}"

        # Update the converter's sample rate to match the streaming audio frequency
        sample_rate = 24000 if request.streaming_audio_frequency == "24khz" else 16000
        converter.set_sample_rate(sample_rate)
        logger.info(
            f"Set audio sample rate to {sample_rate} Hz for {request.streaming_audio_frequency}"
        )

        process = start_pipecat_process(
            client_id=bot_client_id,
            websocket_url=pipecat_websocket_url,
            meeting_url=request.meeting_url,
            persona_name=persona_name,
            streaming_audio_frequency=request.streaming_audio_frequency,
            enable_tools=request.enable_tools,
        )

        # Store the meetingbaas_bot_id in MEETING_DETAILS
        MEETING_DETAILS[bot_client_id] = (
            request.meeting_url,
            persona_name,
            meetingbaas_bot_id,
            request.enable_tools,
        )

        return {
            "message": f"Bot successfully created for meeting {request.meeting_url}",
            "status": "success",
            "websocket_url": websocket_url,
            "bot_id": meetingbaas_bot_id,
            "client_id": bot_client_id,
        }
    else:
        return JSONResponse(
            content={
                "message": "Failed to create bot through MeetingBaas API",
                "status": "error",
            },
            status_code=500,
        )


@app.delete("/bots/{bot_id}", response_model=Dict[str, Any])
async def leave_bot(
    bot_id: str,
    request: LeaveBotRequest,
):
    """
    Remove a bot from a meeting by its ID.

    This will:
    1. Call the MeetingBaas API to make the bot leave
    2. Close WebSocket connections if they exist
    3. Terminate the associated Pipecat process
    """
    logger.info(f"Removing bot with ID: {bot_id}")

    # Verify we have at least the bot_id or client_id
    if not bot_id and not request.bot_id and not request.client_id:
        return JSONResponse(
            content={
                "message": "Either bot_id path parameter or client_id in request body is required",
                "status": "error",
            },
            status_code=400,
        )

    # Use the path parameter bot_id if provided, otherwise use request.bot_id
    meetingbaas_bot_id = bot_id or request.bot_id
    client_id = request.client_id

    # Try to find the client ID from our stored mapping if not provided
    if not client_id:
        # Look through MEETING_DETAILS to find the client ID for this bot ID
        for cid, details in MEETING_DETAILS.items():
            # See if we have a stored mapping for this bot ID
            # Check if the stored meetingbaas_bot_id matches
            if len(details) >= 3 and details[2] == meetingbaas_bot_id:
                client_id = cid
                logger.info(
                    f"Found client ID {client_id} for bot ID {meetingbaas_bot_id}"
                )
                break
            # For now, just checking if client ID is available as a fallback
            logger.info(f"Checking client ID: {cid}")

    # If we found a client ID, try to get the meetingbaas_bot_id if not already provided
    if client_id and not meetingbaas_bot_id and client_id in MEETING_DETAILS:
        details = MEETING_DETAILS[client_id]
        if len(details) >= 3 and details[2]:
            meetingbaas_bot_id = details[2]
            logger.info(f"Found bot ID {meetingbaas_bot_id} for client {client_id}")

    success = True

    # 1. Call MeetingBaas API to make the bot leave
    if meetingbaas_bot_id:
        logger.info(f"Removing bot with ID: {meetingbaas_bot_id} from MeetingBaas API")
        result = leave_meeting_bot(
            bot_id=meetingbaas_bot_id,
            api_key=request.meeting_baas_api_key,
        )
        if not result:
            success = False
            logger.error(
                f"Failed to remove bot {meetingbaas_bot_id} from MeetingBaas API"
            )
    else:
        logger.warning("No MeetingBaas bot ID found, skipping API call")

    # 2. Close WebSocket connections if they exist
    if client_id:
        # Mark the client as closing to prevent further messages
        router.mark_closing(client_id)

        # Close Pipecat WebSocket first
        if client_id in registry.pipecat_connections:
            try:
                await registry.disconnect(client_id, is_pipecat=True)
                logger.info(f"Closed Pipecat WebSocket for client {client_id}")
            except Exception as e:
                success = False
                logger.error(f"Error closing Pipecat WebSocket: {e}")

        # Then close client WebSocket if it exists
        if client_id in registry.active_connections:
            try:
                await registry.disconnect(client_id, is_pipecat=False)
                logger.info(f"Closed client WebSocket for client {client_id}")
            except Exception as e:
                success = False
                logger.error(f"Error closing client WebSocket: {e}")

        # Add a small delay to allow for clean disconnection
        await asyncio.sleep(0.5)

    # 3. Terminate the Pipecat process after WebSockets are closed
    if client_id and client_id in PIPECAT_PROCESSES:
        process = PIPECAT_PROCESSES[client_id]
        if process and process.poll() is None:  # If process is still running
            try:
                if terminate_process_gracefully(process, timeout=3.0):
                    logger.info(
                        f"Gracefully terminated Pipecat process for client {client_id}"
                    )
                else:
                    logger.warning(
                        f"Had to forcefully kill Pipecat process for client {client_id}"
                    )
            except Exception as e:
                success = False
                logger.error(f"Error terminating Pipecat process: {e}")

        # Remove from our storage
        PIPECAT_PROCESSES.pop(client_id, None)

        # Clean up meeting details
        if client_id in MEETING_DETAILS:
            MEETING_DETAILS.pop(client_id, None)
    else:
        logger.warning(f"No Pipecat process found for client {client_id}")

    return {
        "message": "Bot removal request processed",
        "status": "success" if success else "partial",
        "bot_id": meetingbaas_bot_id,
        "client_id": client_id,
    }


@app.delete("/clients/{client_id}", response_model=Dict[str, Any])
async def leave_client(
    client_id: str,
    request: LeaveBotRequest,
):
    """
    Remove a bot from a meeting by its client ID.
    This is a convenience endpoint that sets the client_id and calls leave_bot.
    """
    logger.info(f"Removing bot for client: {client_id}")

    # Update the request to include the client ID from the path
    request.client_id = client_id

    # Find the MeetingBaaS bot_id if available
    if client_id in MEETING_DETAILS:
        # Get any data we might need from our stored mapping
        # For now we don't store bot_id directly, but could be added
        pass

    # Delegate to the main leave_bot endpoint
    return await leave_bot("", request)


# Initialize components
registry = ConnectionRegistry()
converter = ProtobufConverter()
router = MessageRouter(registry, converter)


@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await registry.connect(websocket, client_id)
    logger.info(f"Client {client_id} connected")

    try:
        # Get meeting details from our in-memory storage
        if client_id not in MEETING_DETAILS:
            logger.error(f"No meeting details found for client {client_id}")
            await websocket.close(code=1008, reason="Missing meeting details")
            return

        meeting_url, persona_name, meetingbaas_bot_id, enable_tools = MEETING_DETAILS[
            client_id
        ]
        logger.info(
            f"Retrieved meeting details for {client_id}: {meeting_url}, {persona_name}, {meetingbaas_bot_id}, {enable_tools}"
        )

        # Start Pipecat process
        pipecat_websocket_url = f"ws://localhost:8766/pipecat/{client_id}"
        process = start_pipecat_process(
            client_id=client_id,
            websocket_url=pipecat_websocket_url,
            meeting_url=meeting_url,
            persona_name=persona_name,
            # Use default streaming_audio_frequency and enable_tools
            # These values could be stored in MEETING_DETAILS in the future if needed
            streaming_audio_frequency="24khz",
            enable_tools=enable_tools,
        )

        # Store the process for cleanup
        PIPECAT_PROCESSES[client_id] = process

        # Process messages
        while True:
            message = await websocket.receive()
            if "bytes" in message:
                audio_data = message["bytes"]
                logger.debug(
                    f"Received audio data ({len(audio_data)} bytes) from client {client_id}"
                )
                await router.send_to_pipecat(audio_data, client_id)
            elif "text" in message:
                text_data = message["text"]
                logger.info(
                    f"Received text message from client {client_id}: {text_data[:100]}..."
                )
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for client {client_id}")
    except Exception as e:
        logger.error(f"Error in WebSocket connection: {e}")
    finally:
        # Clean up
        if client_id in PIPECAT_PROCESSES:
            process = PIPECAT_PROCESSES[client_id]
            if process and process.poll() is None:  # If process is still running
                try:
                    process.terminate()
                    logger.info(f"Terminated Pipecat process for client {client_id}")
                except Exception as e:
                    logger.error(f"Error terminating process: {e}")
            # Remove from our storage
            PIPECAT_PROCESSES.pop(client_id, None)

        if client_id in MEETING_DETAILS:
            MEETING_DETAILS.pop(client_id, None)

        try:
            await registry.disconnect(client_id)
            logger.info(f"Client {client_id} disconnected")
        except Exception as e:
            logger.error(f"Error disconnecting client {client_id}: {e}")


@app.websocket("/pipecat/{client_id}")
async def pipecat_websocket(websocket: WebSocket, client_id: str):
    """Handle WebSocket connections from Pipecat"""
    await registry.connect(websocket, client_id, is_pipecat=True)
    try:
        while True:
            message = await websocket.receive()
            if "bytes" in message:
                data = message["bytes"]
                logger.debug(
                    f"Received binary data ({len(data)} bytes) from Pipecat client {client_id}"
                )
                # Forward Pipecat messages to client with conversion
                await router.send_from_pipecat(data, client_id)
            elif "text" in message:
                data = message["text"]
                logger.info(
                    f"Received text message from Pipecat client {client_id}: {data[:100]}..."
                )
    except WebSocketDisconnect:
        await registry.disconnect(client_id, is_pipecat=True)
    except Exception as e:
        logger.error(
            f"Error in Pipecat WebSocket handler for client {client_id}: {str(e)}"
        )
        await registry.disconnect(client_id, is_pipecat=True)


def start_pipecat_process(
    client_id: str,
    websocket_url: str,
    meeting_url: str,
    persona_name: str,
    speak_first: bool = False,
    streaming_audio_frequency: str = "24khz",
    enable_tools: bool = False,
) -> subprocess.Popen:
    """Start a Pipecat process for a client.

    Args:
        client_id: Unique ID for the client
        websocket_url: WebSocket URL for the Pipecat process to connect to
        meeting_url: URL of the meeting to join
        persona_name: Name of the persona to use
        speak_first: Whether the bot should speak first (deprecated)
        streaming_audio_frequency: The streaming audio frequency
        enable_tools: Whether to enable function tools like weather and time

    Returns:
        The started process object
    """
    logger.info(f"Starting Pipecat process for client {client_id}")

    # Construct the command to run the meetingbaas.py script
    script_path = os.path.join(os.path.dirname(__file__), "scripts", "meetingbaas.py")

    # Convert speak_first to entry_message if needed
    entry_message = (
        "Hello, I am here to assist with the meeting."
        if speak_first
        else "Hello, I am the meeting bot"
    )

    # Build command with all parameters
    command = [
        sys.executable,
        script_path,
        "--meeting-url",
        meeting_url,
        "--persona-name",
        persona_name,
        "--entry-message",
        entry_message,
        "--websocket-url",
        websocket_url,
        "--streaming-audio-frequency",
        streaming_audio_frequency,
    ]

    # Add optional flags
    if enable_tools:
        command.append("--enable-tools")

    # Start the process with updated arguments matching the new script interface
    process = subprocess.Popen(
        command,
        env=os.environ.copy(),  # Copy the current environment
    )

    logger.info(f"Started Pipecat process with PID {process.pid}")
    return process


def terminate_process_gracefully(
    process: subprocess.Popen, timeout: float = 2.0
) -> bool:
    """
    Terminate a process gracefully by first sending SIGTERM, waiting for it to exit,
    and then forcefully killing it if needed.

    Args:
        process: The process to terminate
        timeout: How long to wait for graceful termination before force killing

    Returns:
        True if process was terminated gracefully, False if it had to be force-killed
    """
    if process.poll() is not None:
        # Process is already terminated
        return True

    # Send SIGTERM
    try:
        process.terminate()

        # Wait for process to exit
        for _ in range(int(timeout * 10)):  # Check 10 times per second
            if process.poll() is not None:
                return True
            time.sleep(0.1)

        # Process didn't exit gracefully, force kill it
        process.kill()
        process.wait(1.0)  # Wait up to 1 second for it to be killed
        return False
    except Exception as e:
        logger.error(f"Error terminating process: {e}")
        # Try one last time with kill
        try:
            process.kill()
        except:
            pass
        return False


def start_server(host: str = "0.0.0.0", port: int = 8766, local_dev: bool = False):
    """Start the WebSocket server"""
    global LOCAL_DEV_MODE, NGROK_URLS, NGROK_URL_INDEX

    LOCAL_DEV_MODE = local_dev

    # Reset the ngrok URL counter when starting the server
    NGROK_URL_INDEX = 0

    if local_dev:
        print("\n⚠️ Starting in local development mode")
        # Cache the ngrok URLs at server start
        NGROK_URLS = load_ngrok_urls()

        if NGROK_URLS:
            print(f"✅ {len(NGROK_URLS)} Bot(s) available from Ngrok")
            for i, url in enumerate(NGROK_URLS):
                print(f"  Bot {i + 1}: {url}")
        else:
            print(
                "⚠️ No ngrok URLs configured. Using auto-detection for WebSocket URLs."
            )
        print("\n")

    logger.info(f"Starting WebSocket server on {host}:{port}")

    # Pass the local_dev flag as a command-line argument to the uvicorn process
    import sys

    args = [
        sys.executable,
        "-m",
        "uvicorn",
        "api:app",
        "--host",
        host,
        "--port",
        str(port),
    ]

    if local_dev:
        args.extend(["--reload"])

        # Create a file that uvicorn will read on startup to set LOCAL_DEV_MODE
        with open(".local_dev_mode", "w") as f:
            f.write("true")
    else:
        # Make sure we don't have the flag set if not in local dev mode
        if os.path.exists(".local_dev_mode"):
            os.remove(".local_dev_mode")

    # Use os.execv to replace the current process with uvicorn
    # This way all arguments are directly passed to uvicorn
    os.execv(sys.executable, args)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start the MeetingBaas Bot API server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8766, help="Port to listen on")
    parser.add_argument(
        "--local-dev",
        action="store_true",
        help="Run in local development mode with ngrok",
    )

    args = parser.parse_args()
    start_server(args.host, args.port, args.local_dev)
