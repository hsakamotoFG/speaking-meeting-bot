#!/usr/bin/env python3
import argparse
import asyncio
import os
import queue
import random
import shlex
import subprocess
import sys
import threading
import time
import traceback
from contextlib import suppress
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import ngrok
from dotenv import load_dotenv

from config.persona_utils import PersonaManager
from meetingbaas_pipecat.utils.logger import configure_logger

load_dotenv(override=True)

logger = configure_logger()


def validate_url(url):
    """Validates the URL format, ensuring it starts with https://"""
    if not url.startswith("https://"):
        raise ValueError("URL must start with https://")
    return url


def get_user_input(prompt, validator=None):
    while True:
        user_input = input(prompt).strip()
        if validator:
            try:
                return validator(user_input)
            except ValueError as e:
                logger.warning(f"Invalid input received: {e}")
        else:
            return user_input


def get_consecutive_personas(persona_options):
    if len(persona_options) < 2:
        raise ValueError("Need at least two personas to pick consecutive items.")

    # Ensure we're working with folder names
    folder_names = [name.lower().replace(" ", "_") for name in persona_options]

    # Choose a random start index that allows for two consecutive items
    start_index = random.randint(0, len(folder_names) - 2)
    return folder_names[start_index : start_index + 2]


class ProcessLogger:
    def __init__(self, process_name: str, process: subprocess.Popen):
        self.process_name = process_name
        self.process = process
        self.stdout_queue: queue.Queue = queue.Queue()
        self.stderr_queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self.logger = configure_logger()

    def log_output(self, pipe, queue: queue.Queue, is_error: bool = False) -> None:
        """Log output from a pipe to a queue and logger"""
        try:
            for line in iter(pipe.readline, ""):
                if self._stop_event.is_set():
                    break
                line = line.strip()
                if line:
                    queue.put(line)
                    log_msg = f"[{self.process_name}] {line}"
                    if is_error:
                        self.logger.error(log_msg)
                    else:
                        self.logger.info(log_msg)
        finally:
            pipe.close()

    def start_logging(self) -> Tuple[threading.Thread, threading.Thread]:
        """Start logging threads for stdout and stderr"""
        stdout_thread = threading.Thread(
            target=self.log_output,
            args=(self.process.stdout, self.stdout_queue),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=self.log_output,
            args=(self.process.stderr, self.stderr_queue, True),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()
        return stdout_thread, stderr_thread

    def stop(self) -> None:
        """Stop the logging threads gracefully"""
        self._stop_event.set()


class BotProxyManager:
    def __init__(self):
        self.processes: Dict = {}
        self.listeners: List = []
        self.start_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.shutdown_event = asyncio.Event()
        self.initial_args = None
        self.selected_persona_names = []

    async def create_ngrok_tunnel(
        self, port: int, name: str
    ) -> Optional[ngrok.Listener]:
        """Create an ngrok tunnel for the given port"""
        try:
            logger.info(f"Creating ngrok tunnel for {name} on port {port}")
            listener = await ngrok.forward(port, authtoken_from_env=True)
            logger.success(f"Created ngrok tunnel for {name}: {listener.url()}")
            return listener
        except Exception as e:
            logger.error(f"Error creating ngrok tunnel for {name}: {e}")
            return None

    def run_command(self, command: List[str], name: str) -> Optional[subprocess.Popen]:
        """Run a command and store the process"""
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )

            def log_output(stream, prefix):
                for line in stream:
                    line = line.strip()
                    if line:
                        # Check for log level indicators in the line
                        if "ERROR" in line:
                            logger.error(f"{prefix}: {line}")
                        elif "WARNING" in line:
                            logger.warning(f"{prefix}: {line}")
                        elif "SUCCESS" in line:
                            logger.success(f"{prefix}: {line}")
                        else:
                            logger.info(f"{prefix}: {line}")

            # Start threads to handle stdout and stderr
            threading.Thread(
                target=log_output, args=(process.stdout, f"{name}"), daemon=True
            ).start()
            threading.Thread(
                target=log_output, args=(process.stderr, f"{name}"), daemon=True
            ).start()

            self.processes[name] = {"process": process, "command": command}
            return process
        except Exception as e:
            logger.error(f"Failed to start {name}: {e}")
            logger.error(
                "".join(traceback.format_exception(type(e), e, e.__traceback__))
            )
            return None

    async def cleanup(self):
        """Cleanup all processes and ngrok tunnels"""
        try:
            # Close ngrok tunnels
            for listener in self.listeners:
                tunnel_url = listener.url()
                logger.info(f"Closing ngrok tunnel: {tunnel_url}")
                listener.close()
                logger.success(f"Successfully closed ngrok tunnel: {tunnel_url}")

            # Terminate processes in reverse order to ensure clean shutdown
            process_names = list(self.processes.keys())
            process_names.reverse()  # Reverse to terminate in opposite order of creation
            
            for name in process_names:
                process_info = self.processes[name]
                logger.info(f"Terminating process: {name}")
                process = process_info["process"]
                try:
                    process.terminate()
                    await asyncio.sleep(1)  # Give process time to terminate gracefully
                    if process.poll() is None:
                        process.kill()  # Force kill if still running
                    logger.success(f"Process {name} terminated successfully")
                except Exception as e:
                    logger.error(f"Error terminating process {name}: {e}")

            # Clear the processes dictionary
            self.processes.clear()
            logger.success("Cleanup completed successfully")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

    def signal_handler(self, signum, frame):
        logger.warning("Ctrl+C detected, initiating cleanup...")
        # Create and run a new event loop for cleanup
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.cleanup())
        finally:
            loop.close()
        logger.success("Cleanup completed")
        logger.info("Exiting...")
        sys.exit(0)

    async def monitor_processes(self) -> None:
        """Monitor running processes and handle failures"""
        while not self.shutdown_event.is_set():
            try:
                for name, process_info in list(self.processes.items()):
                    process = process_info["process"]
                    if process.poll() is not None:
                        logger.warning(
                            f"Process {name} exited with code: {process.returncode}"
                        )
                        # Could add restart logic here if needed
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error monitoring processes: {e}")
                await asyncio.sleep(1)

    async def async_main(self) -> None:
        parser = argparse.ArgumentParser(
            description="Run bot and proxy command pairs with ngrok tunnels"
        )
        parser.add_argument(
            "-c",
            "--count",
            type=int,
            required=True,
            help="Number of bot-proxy pairs to run",
        )
        parser.add_argument(
            "--personas",
            nargs="+",
            help="List of persona names to use (space-separated). If not provided, random personas will be used.",
        )
        parser.add_argument(
            "-s",
            "--start-port",
            type=int,
            default=8765,
            help="Starting port number (default: 8765)",
        )
        parser.add_argument(
            "--meeting-url", help="The meeting URL (must start with https://)"
        )
        parser.add_argument(
            "--add-recorder",
            action="store_true",
            help="Add an additional recording-only bot",
        )
        parser.add_argument(
            "--speak-first",
            type=int,
            help="Index of the bot that should speak first (1-based)",
        )
        args = parser.parse_args()

        self.initial_args = args

        meeting_url = args.meeting_url
        if not args.meeting_url:
            meeting_url = get_user_input(
                "Enter the meeting URL (must start with https://): ", validate_url
            )
            self.initial_args.meeting_url = meeting_url

        if not os.getenv("NGROK_AUTHTOKEN"):
            logger.error("NGROK_AUTHTOKEN environment variable is not set")
            return

        current_port = args.start_port

        # Add recording-only bot if requested
        if args.add_recorder:
            recorder_name = f"recorder_{args.count + 1}"
            logger.info(f"Adding recording-only bot: {recorder_name}")

            # Start recorder bot
            recorder_process = self.run_command(
                [
                    "poetry",
                    "run",
                    "meetingbaas",
                    "--meeting-url",
                    meeting_url,
                    "--recorder-only",
                ],
                recorder_name,
            )

            if recorder_process:
                logger.success(f"Successfully added recording bot: {recorder_name}")
            else:
                logger.error(f"Failed to start recording bot: {recorder_name}")

        try:
            logger.info(f"Starting {args.count} bot-proxy pairs with ngrok tunnels...")

            # Store persona selection logic results
            available_personas = PersonaManager().list_personas()
            self.selected_persona_names = []

            if args.personas:
                # Validate provided personas exist
                for persona_name in args.personas:
                    if persona_name not in available_personas:
                        raise ValueError(
                            f"Persona '{persona_name}' not found in available personas"
                        )
                    self.selected_persona_names.append(persona_name)

            # If we need more personas than provided, fill with random selections
            if len(self.selected_persona_names) < args.count:
                remaining_count = args.count - len(self.selected_persona_names)
                remaining_personas = [
                    p
                    for p in available_personas
                    if p not in self.selected_persona_names
                ]

                if remaining_count > len(remaining_personas):
                    raise ValueError(
                        f"Not enough remaining personas to select from. Need {remaining_count} more, but only {len(remaining_personas)} available"
                    )

                random.seed(time.time())
                random_selections = random.sample(remaining_personas, remaining_count)
                self.selected_persona_names.extend(random_selections)

            for i in range(args.count):
                pair_num = i + 1

                # Start bot
                bot_port = current_port
                bot_name = f"bot_{pair_num}"

                # Get persona object for this iteration
                persona_name = self.selected_persona_names[i]
                persona = PersonaManager().get_persona(persona_name)
                bot_prompt = persona["prompt"]
                logger.warning(f"**BOT NAME: {persona_name}**")
                logger.warning(
                    f"**SYSTEM PROMPT in batch.py from choice {persona_name}**"
                )
                logger.warning(f"System prompt: {bot_prompt}")
                logger.warning(f"**SYSTEM PROMPT END**")

                # Determine if this bot should speak first
                speak_first = args.speak_first == pair_num if args.speak_first else False

                bot_process = self.run_command(
                    [
                        "poetry",
                        "run",
                        "bot",
                        "-p",
                        str(bot_port),
                        "--system-prompt",
                        bot_prompt,
                        "--persona-name",
                        persona_name,
                        "--voice-id",
                        "40104aff-a015-4da1-9912-af950fbec99e",
                        *(["--speak-first", str(pair_num)] if speak_first else []),
                    ],
                    bot_name,
                )

                if not bot_process:
                    continue

                await asyncio.sleep(1)

                # Start proxy
                proxy_port = current_port + 1
                proxy_name = f"proxy_{pair_num}"
                proxy_process = self.run_command(
                    [
                        "poetry",
                        "run",
                        "proxy",
                        "-p",
                        str(proxy_port),
                        "--websocket-url",
                        f"ws://localhost:{bot_port}",
                    ],
                    proxy_name,
                )
                if not proxy_process:
                    logger.error(
                        f"Failed to start {proxy_name}, terminating {bot_name}"
                    )
                    self.processes[bot_name]["process"].terminate()
                    continue

                # Create ngrok tunnel for the proxy
                listener = await self.create_ngrok_tunnel(
                    proxy_port, f"tunnel_{pair_num}"
                )
                if listener:
                    self.listeners.append(listener)

                # Determine if this bot should speak first
                speak_first = args.speak_first == pair_num if args.speak_first else False
                
                meeting_name = f"meeting_{pair_num}"
                meeting_process = self.run_command(
                    [
                        "poetry",
                        "run",
                        "meetingbaas",
                        "--meeting-url",
                        self.initial_args.meeting_url,
                        "--persona-name",
                        persona_name,
                        "--ngrok-url",
                        listener.url(),
                        *(["--speak-first"] if speak_first else []),
                    ],
                    meeting_name,
                )
                if not meeting_process:
                    logger.error(f"Failed to start {meeting_name}")

                current_port += 2
                await asyncio.sleep(1)

            logger.success(
                f"Successfully started {args.count} bot-proxy pairs with ngrok tunnels"
            )
            logger.info("Press Ctrl+C to stop all processes and close tunnels")

            # Start process monitor
            monitor_task = asyncio.create_task(self.monitor_processes())

            try:
                await self.shutdown_event.wait()
            except asyncio.CancelledError:
                logger.info("\nReceived shutdown signal")
            finally:
                self.shutdown_event.set()
                await monitor_task

        except KeyboardInterrupt:
            logger.info("\nReceived shutdown signal (Ctrl+C)")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
        finally:
            await self.cleanup()
            logger.success("Cleanup completed successfully")

        # Add keyboard input handling for adding new bots
        while not self.shutdown_event.is_set():
            user_input = await asyncio.get_event_loop().run_in_executor(
                None,
                input,
                "Press Enter to add more bots with the same configuration, or Ctrl+C to exit: ",
            )
            if user_input.strip() == "":
                current_count = len(self.processes) // 3
                current_port = self.initial_args.start_port + (current_count * 2)

                # If original launch didn't specify personas, select new random ones
                if not self.initial_args.personas:
                    available_personas = PersonaManager().list_personas()
                    # Exclude currently active personas to avoid duplicates
                    active_personas = set(
                        self.selected_persona_names[-self.initial_args.count :]
                    )
                    available_personas = [
                        p for p in available_personas if p not in active_personas
                    ]

                    if len(available_personas) < self.initial_args.count:
                        logger.warning(
                            "Not enough unique personas left, reusing some personas"
                        )
                        available_personas = PersonaManager().list_personas()

                    new_personas = random.sample(
                        available_personas, self.initial_args.count
                    )
                    self.selected_persona_names.extend(new_personas)

                for i in range(self.initial_args.count):
                    pair_num = current_count + i + 1
                    bot_port = current_port
                    proxy_port = current_port + 1

                    # Get the newly selected persona for this iteration
                    persona_name = self.selected_persona_names[
                        -self.initial_args.count + i
                    ]
                    persona = PersonaManager().get_persona(persona_name)
                    bot_prompt = persona["prompt"]

                    # Start bot
                    bot_name = f"bot_{pair_num}"
                    logger.warning(f"**STARTING BOT {bot_name} ON PORT {bot_port}**")
                    bot_process = self.run_command(
                        [
                            "poetry",
                            "run",
                            "bot",
                            "-p",
                            str(bot_port),
                            "--system-prompt",
                            bot_prompt,
                            "--persona-name",
                            persona_name,
                            "--voice-id",
                            "40104aff-a015-4da1-9912-af950fbec99e",
                        ],
                        bot_name,
                    )

                    if not bot_process:
                        continue

                    await asyncio.sleep(1)

                    # Start proxy
                    proxy_name = f"proxy_{pair_num}"
                    proxy_port = bot_port + 1
                    logger.warning(
                        f"**STARTING PROXY {proxy_name} ON PORT {proxy_port} CONNECTING TO BOT PORT {bot_port}**"
                    )
                    proxy_process = self.run_command(
                        [
                            "poetry",
                            "run",
                            "proxy",
                            "-p",
                            str(proxy_port),
                            "--websocket-url",
                            f"ws://localhost:{bot_port}",
                        ],
                        proxy_name,
                    )

                    if not proxy_process:
                        logger.error(
                            f"Failed to start {proxy_name}, terminating {bot_name}"
                        )
                        self.processes[bot_name]["process"].terminate()
                        continue

                    # Create ngrok tunnel for the proxy
                    listener = await self.create_ngrok_tunnel(
                        proxy_port, f"tunnel_{pair_num}"
                    )
                    if listener:
                        self.listeners.append(listener)
                        meeting_name = f"meeting_{pair_num}"
                        meeting_process = self.run_command(
                            [
                                "poetry",
                                "run",
                                "meetingbaas",
                                "--meeting-url",
                                self.initial_args.meeting_url,
                                "--persona-name",
                                persona_name,
                                "--ngrok-url",
                                listener.url(),
                            ],
                            meeting_name,
                        )
                        if not meeting_process:
                            logger.error(f"Failed to start {meeting_name}")

                    current_port += 2
                    await asyncio.sleep(1)

                logger.success(
                    f"Successfully added {self.initial_args.count} new bot-proxy pairs"
                )

    def main(self) -> None:
        """Main entry point with proper signal handling"""
        try:
            if sys.platform != "win32":
                # Set up signal handlers for Unix-like systems
                import signal

                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                def signal_handler():
                    self.shutdown_event.set()

                loop.add_signal_handler(signal.SIGINT, signal_handler)
                loop.add_signal_handler(signal.SIGTERM, signal_handler)

                try:
                    loop.run_until_complete(self.async_main())
                finally:
                    loop.close()
            else:
                # Windows doesn't support loop.add_signal_handler
                asyncio.run(self.async_main())
        except Exception as e:
            logger.exception(f"Fatal error in main program: {e}")
            sys.exit(1)


if __name__ == "__main__":
    manager = BotProxyManager()
    manager.main()
