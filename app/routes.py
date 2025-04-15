"""API routes for the Speaking Meeting Bot application."""

import asyncio
import uuid
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, HttpUrl

from app.models import BotRequest, JoinResponse, LeaveBotRequest
from config.persona_utils import persona_manager
from core.connection import MEETING_DETAILS, PIPECAT_PROCESSES, registry
from core.process import start_pipecat_process, terminate_process_gracefully
from core.router import router as message_router

# Import from the app module (will be defined in __init__.py)
from meetingbaas_pipecat.utils.logger import logger
from scripts.meetingbaas_api import create_meeting_bot, leave_meeting_bot
from utils.ngrok import (
    LOCAL_DEV_MODE,
    determine_websocket_url,
    log_ngrok_status,
    release_ngrok_url,
    update_ngrok_client_id,
)

router = APIRouter()


@router.get("/")
async def root():
    """Root endpoint that confirms the API is running."""
    return {"message": "MeetingBaas Bot API is running"}


@router.post("/bots", tags=["Bots"], response_model=JoinResponse)
async def join_meeting(request: BotRequest, client_request: Request):
    """
    Create and deploy a speaking bot in a meeting.

    Launches an AI-powered bot that joins a video meeting through MeetingBaas
    and processes audio using Pipecat's voice AI framework.
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
    websocket_url, temp_client_id = determine_websocket_url(
        request.websocket_url, client_request
    )

    logger.info(f"Starting bot for meeting {request.meeting_url}")
    logger.info(f"WebSocket URL: {websocket_url}")
    logger.info(f"Bot name: {request.bot_name}")

    # INTERNAL PARAMETER: Set a fixed value for streaming_audio_frequency
    # This is not exposed in the API and is always "24khz"
    streaming_audio_frequency = "24khz"
    logger.info(f"Using fixed streaming audio frequency: {streaming_audio_frequency}")

    # Set the converter sample rate based on our fixed streaming_audio_frequency
    from core.converter import converter

    sample_rate = 24000  # Always 24000 Hz for 24khz audio
    converter.set_sample_rate(sample_rate)
    logger.info(
        f"Set audio sample rate to {sample_rate} Hz for {streaming_audio_frequency}"
    )

    # Generate a unique client ID for this bot
    bot_client_id = str(uuid.uuid4())

    # If we're in local dev mode and we have a temp client ID, update the mapping
    if LOCAL_DEV_MODE and temp_client_id:
        update_ngrok_client_id(temp_client_id, bot_client_id)
        log_ngrok_status()

    # Select the persona - use provided one or pick a random one
    if request.personas and len(request.personas) > 0:
        persona_name = request.personas[0]
        logger.info(f"Using specified persona: {persona_name}")
    else:
        # Use the bot_name as the persona name if no personas are specified
        persona_name = request.bot_name
        logger.info(f"Using bot_name as persona: {persona_name}")

        # If the persona doesn't exist, try to use a random one
        if persona_name not in persona_manager.personas:
            import random

            available_personas = list(persona_manager.personas.keys())
            if available_personas:
                persona_name = random.choice(available_personas)
                logger.info(f"Persona not found, using random persona: {persona_name}")
            else:
                # Fallback to baas_onboarder if we somehow can't get the personas list
                persona_name = "baas_onboarder"
                logger.warning(
                    "No personas found, using fallback persona: baas_onboarder"
                )

    # Get the persona data
    persona = persona_manager.get_persona(persona_name)

    # Store meeting details for when the WebSocket connects
    # Also store streaming_audio_frequency and recorder_only
    MEETING_DETAILS[bot_client_id] = (
        request.meeting_url,
        persona_name,
        None,  # MeetingBaas bot ID will be set after creation
        request.enable_tools,
        streaming_audio_frequency,
        request.recorder_only,  # Add recorder_only parameter
    )

    # Get image from persona if not specified in request
    bot_image = request.bot_image
    if not bot_image and persona.get("image"):
        # Ensure the image is a string
        try:
            # Convert to string no matter what type it is
            bot_image = str(persona.get("image"))
            logger.info(f"Using persona image: {bot_image}")
        except Exception as e:
            logger.error(f"Error converting persona image to string: {e}")
            bot_image = None

    # Ensure the bot_image is definitely a string or None
    if bot_image is not None:
        try:
            bot_image_str = str(bot_image)
            logger.info(f"Final bot image URL: {bot_image_str}")
        except Exception as e:
            logger.error(f"Failed to convert bot image to string: {e}")
            bot_image_str = None
    else:
        bot_image_str = None

    # Create bot directly through MeetingBaas API
    meetingbaas_bot_id = create_meeting_bot(
        meeting_url=request.meeting_url,
        websocket_url=websocket_url,
        bot_id=bot_client_id,
        persona_name=persona.get("name", persona_name),  # Use persona display name
        api_key=request.meeting_baas_api_key,
        recorder_only=request.recorder_only,
        bot_image=bot_image_str,  # Use the pre-stringified value
        entry_message=request.entry_message,
        extra=request.extra,
        streaming_audio_frequency=streaming_audio_frequency,
    )

    if meetingbaas_bot_id:
        # Update the meetingbaas_bot_id in MEETING_DETAILS
        MEETING_DETAILS[bot_client_id] = (
            request.meeting_url,
            persona_name,
            meetingbaas_bot_id,
            request.enable_tools,
            streaming_audio_frequency,
            request.recorder_only,  # Add recorder_only parameter
        )

        # Return a response that matches MeetingBaas API format
        return JoinResponse(bot_id=meetingbaas_bot_id)
    else:
        return JSONResponse(
            content={
                "message": "Failed to create bot through MeetingBaas API",
                "status": "error",
            },
            status_code=500,
        )


@router.delete("/bots/{bot_id}", response_model=Dict[str, Any])
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
        message_router.mark_closing(client_id)

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

        # Release ngrok URL if in local dev mode
        if LOCAL_DEV_MODE and client_id:
            release_ngrok_url(client_id)
            log_ngrok_status()
    else:
        logger.warning(f"No Pipecat process found for client {client_id}")

    return {
        "message": "Bot removal request processed",
        "status": "success" if success else "partial",
        "bot_id": meetingbaas_bot_id,
        "client_id": client_id,
    }


@router.delete("/clients/{client_id}", response_model=Dict[str, Any])
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
