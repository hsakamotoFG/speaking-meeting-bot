"""Process management for Pipecat processes."""

import os
import subprocess
import sys
import time
from typing import Optional

from config.persona_utils import persona_manager
from meetingbaas_pipecat.utils.logger import logger


def start_pipecat_process(
    client_id: str,
    websocket_url: str,
    meeting_url: str,
    persona_name: str,
    streaming_audio_frequency: str = "16khz",
    enable_tools: bool = False,
) -> subprocess.Popen:
    """
    Start a Pipecat process for a client.

    Args:
        client_id: Unique ID for the client
        websocket_url: WebSocket URL for communication
        meeting_url: Meeting URL to join
        persona_name: Name of the persona to use
        streaming_audio_frequency: Audio sampling frequency
        enable_tools: Whether to enable function calling tools

    Returns:
        The subprocess.Popen object for the started process
    """
    logger.info(f"Starting Pipecat process for client {client_id}")

    # Construct the command to run the meetingbaas.py script
    script_path = os.path.join(
        os.path.dirname(__file__), "..", "scripts", "meetingbaas.py"
    )

    # Get the persona's custom entry message
    persona = persona_manager.get_persona(persona_name)

    # Use the persona's display name (from README) instead of folder name
    display_name = persona.get("name", persona_name)

    # Build command with all parameters
    command = [
        sys.executable,
        script_path,
        "--meeting-url",
        meeting_url,
        "--persona-name",
        display_name,
        "--entry-message",
        persona.get("entry_message", ""),
        "--websocket-url",
        websocket_url,
        "--streaming-audio-frequency",
        streaming_audio_frequency,
    ]

    # Add optional flags
    if enable_tools:
        command.append("--enable-tools")

    # Start the process
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
