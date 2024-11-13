import argparse
import os

from loguru import logger

from config.personas import get_persona_by_name


async def configure(
    parser: argparse.ArgumentParser | None = None, system_prompt: str = None
):
    if not parser:
        parser = argparse.ArgumentParser(description="Pipecat SDK AI Bot")
    parser.add_argument(
        "--host", type=str, default="0.0.0.0", help="Host to bind the server to"
    )
    parser.add_argument(
        "-p", "--port", type=int, default=8766, help="Port to run the server on"
    )
    parser.add_argument(
        "--voice-id",
        type=str,
        required=False,
        help="Cartesia voice ID for text-to-speech conversion",
    )
    parser.add_argument(
        "--persona-name",
        type=str,
        required=False,
        help="Name of the persona to use",
    )

    args, unknown = parser.parse_known_args()

    logger.warning(f"**FOR ARGS: {args}**")
    # Get persona based on name or random if none provided
    persona = get_persona_by_name(args.persona_name)

    # Use persona's prompt as system prompt if no override provided
    system_prompt = system_prompt or persona["prompt"]

    if not system_prompt:
        raise Exception("No system prompt provided")

    voice_id = args.voice_id or os.getenv("CARTESIA_VOICE_ID")

    if not voice_id:
        raise Exception(
            "No Cartesia voice ID. use the -v/--voice-id option from the command line, or set CARTESIA_API_KEY in your environment to specify a Cartesia voice ID."
        )

    logger.warning(
        f"returning {args.host, args.port, system_prompt, voice_id, persona['name'], args}"
    )
    return (args.host, args.port, system_prompt, voice_id, persona["name"], args)
