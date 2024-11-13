import argparse
import os


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
  parser.add_argument(
    "--system-prompt",
    type=str,
    required=False,
    help="System prompt for the bot's personality",
  )

  args, unknown = parser.parse_known_args()

  # Get system prompt from arguments or passed parameter
  system_prompt = args.system_prompt or system_prompt

  if not system_prompt:
    raise Exception("No system prompt provided")

  voice_id = args.voice_id or os.getenv("CARTESIA_VOICE_ID")

  if not voice_id:
    raise Exception(
      "No Cartesia voice ID. use the -v/--voice-id option from the command line, or set CARTESIA_API_KEY in your environment to specify a Cartesia voice ID."
    )

  return (args.host, args.port, system_prompt, voice_id, args.persona_name, args)
