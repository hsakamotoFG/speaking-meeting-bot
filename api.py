import argparse
import json
import logging
import os
import sys
import uuid
from typing import Dict, List, Optional, Tuple

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
from scripts.meetingbaas_api import create_meeting_bot

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("meetingbaas-api")

# Check for local dev mode marker file (created by the parent process)
LOCAL_DEV_MODE = False
if os.path.exists(".local_dev_mode"):
    with open(".local_dev_mode", "r") as f:
        if f.read().strip().lower() == "true":
            LOCAL_DEV_MODE = True
            logger.info(
                "🚀 Starting in LOCAL_DEV_MODE (detected from .local_dev_mode file)"
            )

# Get base URL from environment variable
BASE_URL = os.environ.get("BASE_URL", None)
if BASE_URL:
    logger.info(f"Using BASE_URL from environment: {BASE_URL}")
    # Convert http to ws or https to wss if needed
    if BASE_URL.startswith("http://"):
        WS_BASE_URL = "ws://" + BASE_URL[7:]
    elif BASE_URL.startswith("https://"):
        WS_BASE_URL = "wss://" + BASE_URL[8:]
    else:
        # Assume it's already in ws:// or wss:// format
        WS_BASE_URL = BASE_URL
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


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.pipecat_connections: Dict[str, WebSocket] = {}
        self.logger = logger
        self.sample_rate = 24000  # Default sample rate for audio
        self.channels = 1  # Default number of channels

    async def connect(
        self, websocket: WebSocket, client_id: str, is_pipecat: bool = False
    ):
        await websocket.accept()
        if is_pipecat:
            self.pipecat_connections[client_id] = websocket
            self.logger.info(f"Pipecat client {client_id} connected")
        else:
            self.active_connections[client_id] = websocket
            self.logger.info(f"Client {client_id} connected")

    def disconnect(self, client_id: str, is_pipecat: bool = False):
        if is_pipecat and client_id in self.pipecat_connections:
            del self.pipecat_connections[client_id]
            self.logger.info(f"Pipecat client {client_id} disconnected")
        elif client_id in self.active_connections:
            del self.active_connections[client_id]
            self.logger.info(f"Client {client_id} disconnected")

    async def send_binary(self, message: bytes, client_id: str):
        """Send binary data to a client"""
        if client_id in self.active_connections:
            await self.active_connections[client_id].send_bytes(message)
            self.logger.debug(f"Sent {len(message)} bytes to client {client_id}")

    async def send_to_pipecat(self, message: bytes, client_id: str):
        """Convert raw audio to Protobuf frame and send to Pipecat"""
        if client_id in self.pipecat_connections:
            try:
                # Create Protobuf frame for the audio data
                frame = frames_pb2.Frame()
                frame.audio.audio = message
                frame.audio.sample_rate = self.sample_rate
                frame.audio.num_channels = self.channels

                # Serialize and send the frame
                serialized_frame = frame.SerializeToString()
                await self.pipecat_connections[client_id].send_bytes(serialized_frame)
                self.logger.debug(
                    f"Forwarded audio frame ({len(message)} bytes) to Pipecat for client {client_id}"
                )
            except Exception as e:
                self.logger.error(f"Error sending to Pipecat: {str(e)}")

    async def send_from_pipecat(self, message: bytes, client_id: str):
        """Extract audio from Protobuf frame and send to client"""
        if client_id in self.active_connections:
            try:
                frame = frames_pb2.Frame()
                frame.ParseFromString(message)
                if frame.HasField("audio"):
                    audio_data = frame.audio.audio
                    audio_size = len(audio_data)
                    await self.active_connections[client_id].send_bytes(
                        bytes(audio_data)
                    )
                    self.logger.debug(
                        f"Forwarded audio ({audio_size} bytes) from Pipecat to client {client_id}"
                    )
            except Exception as e:
                self.logger.error(f"Error processing Pipecat message: {str(e)}")

    async def send_text(self, message: str, client_id: str):
        """Send text message to a specific client"""
        if client_id in self.active_connections:
            await self.active_connections[client_id].send_text(message)
            self.logger.debug(
                f"Sent text message to client {client_id}: {message[:100]}..."
            )

    async def broadcast(self, message: str):
        """Broadcast text message to all clients"""
        for client_id, connection in self.active_connections.items():
            await connection.send_text(message)
            self.logger.debug(f"Broadcast text message to client {client_id}")


manager = ConnectionManager()


class BotRequest(BaseModel):
    meeting_url: str
    personas: Optional[List[str]] = None
    recorder_only: bool = False
    websocket_url: Optional[str] = None  # Now optional in all cases
    meeting_baas_api_key: str
    bot_image: Optional[str] = None
    entry_message: Optional[str] = None
    extra: Optional[Dict] = None


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
    if url.startswith("http://"):
        url = "ws://" + url[7:]
    elif url.startswith("https://"):
        url = "wss://" + url[8:]

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

    # Generate a UUID for the bot
    bot_client_id = str(uuid.uuid4())[:8]

    # Select the persona (use first one if provided, otherwise "default")
    persona_name = (
        request.personas[0]
        if request.personas and len(request.personas) > 0
        else "default"
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
    )

    if meetingbaas_bot_id:
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


@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """Handle WebSocket connections from clients (MeetingBaas)"""
    logger.info(f"Received WebSocket connection attempt from client {client_id}")
    try:
        await manager.connect(websocket, client_id)
        logger.info(f"WebSocket connection established with client {client_id}")

        # Track if we've already logged the first audio chunk
        first_audio_logged = False

        while True:
            message = await websocket.receive()
            if "bytes" in message:
                data = message["bytes"]
                # Only log the first audio data received
                if not first_audio_logged:
                    logger.info(
                        f"Receiving audio data from client {client_id} ({len(data)} bytes per chunk)"
                    )
                    first_audio_logged = True
                # Forward binary data to Pipecat with conversion
                await manager.send_to_pipecat(data, client_id)
            elif "text" in message:
                data = message["text"]
                # Try to parse as JSON and pretty print speakers
                try:
                    json_data = json.loads(data)
                    # Check if this is speaker data (contains name and isSpeaking fields)
                    if (
                        isinstance(json_data, list)
                        and len(json_data) > 0
                        and "name" in json_data[0]
                        and "isSpeaking" in json_data[0]
                    ):
                        for speaker in json_data:
                            status = (
                                "started speaking"
                                if speaker.get("isSpeaking")
                                else "stopped speaking"
                            )
                            logger.info(
                                f"👤 {speaker.get('name')} ({speaker.get('id')}) {status}"
                            )
                    else:
                        # Regular JSON message
                        logger.info(
                            f"JSON message from client {client_id}:\n{json.dumps(json_data, indent=2)}"
                        )
                except json.JSONDecodeError:
                    # Not JSON, just a regular text message
                    logger.info(
                        f"Received text message from client {client_id}: {data}"
                    )

                # Handle text messages (could be control commands)
                await manager.broadcast(f"Client {client_id} says: {data}")
    except WebSocketDisconnect:
        logger.warning(f"WebSocket disconnected for client {client_id}")
        manager.disconnect(client_id)
    except Exception as e:
        logger.error(f"Error in WebSocket handler: {str(e)}")
        manager.disconnect(client_id)


@app.websocket("/pipecat/{client_id}")
async def pipecat_websocket(websocket: WebSocket, client_id: str):
    """Handle WebSocket connections from Pipecat"""
    await manager.connect(websocket, client_id, is_pipecat=True)
    try:
        while True:
            message = await websocket.receive()
            if "bytes" in message:
                data = message["bytes"]
                logger.debug(
                    f"Received binary data ({len(data)} bytes) from Pipecat client {client_id}"
                )
                # Forward Pipecat messages to client with conversion
                await manager.send_from_pipecat(data, client_id)
            elif "text" in message:
                data = message["text"]
                logger.info(
                    f"Received text message from Pipecat client {client_id}: {data[:100]}..."
                )
    except WebSocketDisconnect:
        manager.disconnect(client_id, is_pipecat=True)
    except Exception as e:
        logger.error(
            f"Error in Pipecat WebSocket handler for client {client_id}: {str(e)}"
        )
        manager.disconnect(client_id, is_pipecat=True)


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
