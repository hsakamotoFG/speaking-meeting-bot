import argparse
import asyncio
import logging
import os
import sys
import uuid
from typing import Optional

from dotenv import load_dotenv
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMMessagesFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.serializers.protobuf import ProtobufFrameSerializer
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.network.websocket_client import (
    WebsocketClientParams,
    WebsocketClientTransport,
)

from config.persona_utils import PersonaManager
from meetingbaas_pipecat.utils.logger import configure_logger

load_dotenv(override=True)

logger = configure_logger()


async def main(
    meeting_url: str = "",
    persona_name: str = "Meeting Bot",
    entry_message: str = "Hello, I am the meeting bot",
    recorder_only: bool = False,
    bot_image: str = "",
    streaming_audio_frequency: str = "24khz",
    websocket_url: str = "",
):
    """
    Run the MeetingBaas bot with specified configurations

    Args:
        meeting_url: URL to join the meeting
        persona_name: Name to display for the bot
        entry_message: Message to send when joining
        recorder_only: Whether to only record (no STT processing)
        bot_image: URL for bot avatar
        streaming_audio_frequency: Audio frequency for streaming (16khz or 24khz)
        websocket_url: Full WebSocket URL to connect to, including any path
    """
    # Load environment variables for credentials (OpenAI, etc.)
    load_dotenv()

    # Validate WebSocket URL
    if not websocket_url:
        logger.error("Error: WebSocket URL not provided")
        return

    logger.info(f"Using WebSocket URL: {websocket_url}")

    # Extract bot_id from the websocket_url if possible
    # Format is usually: ws://localhost:8766/pipecat/{client_id}
    parts = websocket_url.split("/")
    bot_id = parts[-1] if len(parts) > 3 else "unknown"
    logger.info(f"Using bot ID: {bot_id}")

    # Set sample rate based on streaming_audio_frequency
    output_sample_rate = 24000 if streaming_audio_frequency == "24khz" else 16000
    # Silero VAD only supports 16000 or 8000 Hz
    vad_sample_rate = 16000

    logger.info(
        f"Using audio frequency: {streaming_audio_frequency} (output sample rate: {output_sample_rate}, VAD sample rate: {vad_sample_rate})"
    )

    # Set up the WebSocket transport with correct sample rates - use the full WebSocket URL directly
    transport = WebsocketClientTransport(
        uri=websocket_url,
        params=WebsocketClientParams(
            audio_out_sample_rate=output_sample_rate,
            audio_out_enabled=True,
            add_wav_header=False,
            vad_enabled=True,
            vad_analyzer=SileroVADAnalyzer(sample_rate=vad_sample_rate),
            vad_audio_passthrough=True,
            serializer=ProtobufFrameSerializer(),
        ),
    )

    # Get persona configuration
    persona = PersonaManager().get_persona(persona_name)
    if not persona:
        logger.error(f"Persona '{persona_name}' not found")
        return

    # Initialize services
    tts = CartesiaTTSService(
        api_key=os.getenv("CARTESIA_API_KEY"),
        voice_id=os.getenv("CARTESIA_VOICE_ID"),
        sample_rate=24000,
    )

    llm = OpenAILLMService(
        api_key=os.getenv("OPENAI_API_KEY"),
        model="gpt-4-turbo-preview",
    )

    # Add speech-to-text service
    stt = DeepgramSTTService(
        api_key=os.getenv("DEEPGRAM_API_KEY"),
        encoding="linear24",
        sample_rate=24000,
    )

    # Make sure we're setting a valid bot name
    bot_name = persona_name or "Bot"
    logger.info(f"Using bot name: {bot_name}")

    # Set up messages only once
    messages = [
        {
            "role": "system",
            "content": persona["prompt"],
        },
    ]

    # In v0.0.63, the OpenAILLMContext and context aggregation system was updated
    # Create the context object - no tools needed for this use case
    context = OpenAILLMContext(messages)

    # Get the context aggregator pair using the LLM's method
    # This handles properly setting up the context aggregators
    aggregator_pair = llm.create_context_aggregator(context)

    # Get the user and assistant aggregators from the pair
    user_aggregator = aggregator_pair.user()
    assistant_aggregator = aggregator_pair.assistant()

    # Create pipeline using the single instances - adding STT service
    pipeline = Pipeline(
        [
            transport.input(),
            stt,  # Add speech-to-text service
            user_aggregator,  # Process user input and update context
            llm,
            tts,
            transport.output(),
            assistant_aggregator,  # Store LLM responses in context
        ]
    )

    # Create and run task
    task = PipelineTask(pipeline, params=PipelineParams(allow_interruptions=True))
    runner = PipelineRunner()

    # Handle the initial greeting if needed
    if entry_message:
        logger.info("Bot will speak first with an introduction")
        # Prepare a greeting message
        initial_message = {
            "role": "user",
            "content": entry_message,
        }

        # Queue the initial message to be processed once the pipeline starts
        async def queue_initial_message():
            await asyncio.sleep(2)  # Small delay to ensure transport is ready
            await task.queue_frames([LLMMessagesFrame([initial_message])])
            logger.info("Initial greeting message queued")

        # Create a task to queue the initial message
        asyncio.create_task(queue_initial_message())

    # Run the pipeline
    await runner.run(task)


if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Run a MeetingBaas bot")
    parser.add_argument("--meeting-url", help="URL of the meeting to join")
    parser.add_argument(
        "--persona-name", default="Meeting Bot", help="Name to display for the bot"
    )
    parser.add_argument(
        "--entry-message",
        default="Hello, I am the meeting bot",
        help="Message to send when joining",
    )
    parser.add_argument(
        "--recorder-only",
        action="store_true",
        help="Bot only records (no STT processing)",
    )
    parser.add_argument("--bot-image", default="", help="URL for bot avatar")
    parser.add_argument(
        "--streaming-audio-frequency",
        default="24khz",
        choices=["16khz", "24khz"],
        help="Audio frequency for streaming (16khz or 24khz)",
    )
    parser.add_argument(
        "--websocket-url", help="Full WebSocket URL to connect to, including any path"
    )

    args = parser.parse_args()

    # Run the bot
    asyncio.run(
        main(
            meeting_url=args.meeting_url,
            persona_name=args.persona_name,
            entry_message=args.entry_message,
            recorder_only=args.recorder_only,
            bot_image=args.bot_image,
            streaming_audio_frequency=args.streaming_audio_frequency,
            websocket_url=args.websocket_url,
        )
    )
