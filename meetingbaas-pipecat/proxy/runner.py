import argparse
import os


async def configure(
  parser: argparse.ArgumentParser | None = None,
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
    "--websocket-url",
    type=str,
    default="ws://localhost:8765",
    help="Pipecat WebSocket URL",
  )
  parser.add_argument(
    "--sample-rate", type=int, default=24000, help="Audio sample rate"
  )
  parser.add_argument(
    "--channels", type=int, default=1, help="Number of audio channels"
  )

  args, unknown = parser.parse_known_args()
  return (
    args.host,
    args.port,
    args.websocket_url,
    args.sample_rate,
    args.channels,
    args,
  )
