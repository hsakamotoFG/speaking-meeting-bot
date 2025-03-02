import asyncio
import signal
import sys
from contextlib import suppress

import websockets
from google.protobuf.message import EncodeError
from loguru import logger
from websockets.exceptions import ConnectionClosedError

import protobufs.frames_pb2 as frames_pb2
from meetingbaas_pipecat.utils.logger import configure_logger

from .runner import configure

logger = configure_logger()


async def handle_pipecat_messages(pipecat_ws, client_ws):
    """Handle messages coming from Pipecat back to the client"""
    try:
        async for message in pipecat_ws:
            if isinstance(message, bytes):
                try:
                    frame = frames_pb2.Frame()
                    frame.ParseFromString(message)
                    if frame.HasField("audio"):
                        audio_data = frame.audio.audio
                        await client_ws.send(bytes(audio_data))
                        logger.debug("Forwarded audio response to client")
                except Exception as e:
                    logger.error(f"Error processing Pipecat response: {str(e)}")
                    logger.exception(e)
    except Exception as e:
        logger.error(f"Error in Pipecat message handler: {str(e)}")
        logger.exception(e)


async def forward_audio(websocket, websocket_url, sample_rate, channels):
    pipecat_ws = None
    try:
        async with websockets.connect(websocket_url) as pipecat_ws:
            logger.debug("Connected to Pipecat WebSocket")

            # Create message handler task
            pipecat_handler = asyncio.create_task(
                handle_pipecat_messages(pipecat_ws, websocket)
            )

            try:
                async for message in websocket:
                    if isinstance(message, bytes):
                        try:
                            frame = frames_pb2.Frame()
                            frame.audio.audio = message
                            frame.audio.sample_rate = sample_rate
                            frame.audio.num_channels = channels

                            serialized_frame = frame.SerializeToString()
                            await pipecat_ws.send(serialized_frame)
                            logger.debug("Successfully forwarded audio frame to Pipecat")
                        except Exception as e:
                            logger.error(f"Error processing client frame: {str(e)}")
                            logger.exception(e)
                    elif isinstance(message, str):
                        logger.info(f"Received string message: {message}")
                    else:
                        logger.warning(f"Unexpected message type: {type(message)}")
            except websockets.exceptions.ConnectionClosed as e:
                logger.info(f"Client connection closed: {e}")
            except Exception as e:
                logger.error(f"Error in client message handler: {str(e)}")
                logger.exception(e)
            finally:
                # Cancel and wait for the handler task
                if not pipecat_handler.done():
                    pipecat_handler.cancel()
                    with suppress(asyncio.CancelledError):
                        await pipecat_handler
    except websockets.exceptions.ConnectionClosed as e:
        logger.info(f"Pipecat connection closed: {e}")
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        logger.exception(e)
    finally:
        # Ensure proper closing of both WebSocket connections
        if pipecat_ws and not pipecat_ws.closed:
            try:
                await pipecat_ws.close(code=1000, reason="Session ended")
                logger.info("Pipecat WebSocket connection closed properly")
            except Exception as e:
                logger.error(f"Error closing Pipecat connection: {e}")

        if not websocket.closed:
            try:
                await websocket.close(code=1000, reason="Session ended")
                logger.info("Client WebSocket connection closed properly")
            except Exception as e:
                logger.error(f"Error closing client connection: {e}")


async def main():
    host, port, websocket_url, sample_rate, channels, args = await configure()

    async def cleanup(server):
        logger.info("Initiating WebSocket server cleanup...")
        server.close()
        await server.wait_closed()
        logger.info("WebSocket server cleanup completed")

    server = await websockets.serve(
        lambda ws: forward_audio(ws, websocket_url, sample_rate, channels), host, port
    )
    logger.info(f"WebSocket server started on ws://{host}:{port}")

    try:
        # Handle graceful shutdown
        loop = asyncio.get_running_loop()
        for signal_name in ('SIGINT', 'SIGTERM'):
            loop.add_signal_handler(
                getattr(signal, signal_name),
                lambda: asyncio.create_task(cleanup(server))
            )
        await asyncio.Future()  # Keep server running
    except KeyboardInterrupt:
        logger.info("Shutting down server...")
        await cleanup(server)


def start():
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server shutdown complete.")


if __name__ == "__main__":
    start()
