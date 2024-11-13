import argparse
import os
import signal
import sys
import time
import uuid

import requests
from dotenv import load_dotenv
from loguru import logger

from config.personas import get_persona_by_name
from meetingbaas_pipecat.utils.logger import configure_logger

logger = configure_logger()

# Load environment variables from .env file
load_dotenv()
API_KEY = os.getenv("MEETING_BAAS_API_KEY")
if not API_KEY:
    logger.error("MEETING_BAAS_API_KEY not found in environment variables")
    exit(1)


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


def get_persona_selection():
    """Prompts user to select a persona from available options"""
    from config.personas import get_persona, list_personas

    available_personas = list_personas()
    logger.info("\nAvailable personas:")
    for persona_key in available_personas:
        persona = get_persona(persona_key)
        logger.info(f"{persona_key}: {persona['name']}")

    logger.info("\nPress Enter for random selection or type persona name:")

    while True:
        try:
            choice = (
                input("\nSelect a persona (enter name or press Enter for random): ")
                .strip()
                .lower()
            )
            if not choice:  # Empty input
                return None
            if choice in available_personas:
                return choice
            logger.warning("Invalid selection. Please try again.")
        except ValueError:
            logger.warning("Please enter a valid persona name.")


def create_baas_bot(meeting_url, ngrok_url, persona_name=None):
    from config.personas import get_persona

    if not persona_name:
        persona_name = get_persona_selection()

    try:
        persona = get_persona(persona_name)
    except KeyError:
        try:
            persona = get_persona_by_name(persona_name)
        except KeyError:
            logger.error(f"Persona '{persona_name}' not found in available personas.")
            return None

    url = "https://api.meetingbaas.com/bots"
    headers = {
        "Content-Type": "application/json",
        "x-meeting-baas-api-key": API_KEY,
    }

    deduplication_key = str(uuid.uuid4())
    config = {
        "meeting_url": meeting_url,
        "bot_name": persona["name"],
        "recording_mode": "speaker_view",
        "bot_image": persona["image"],
        "entry_message": persona["entry_message"],
        "reserved": False,
        "speech_to_text": {"provider": "Default"},
        "automatic_leave": {"waiting_room_timeout": 600},
        "deduplication_key": deduplication_key,
        "streaming": {"input": ngrok_url, "output": ngrok_url},
    }

    logger.info(f"Creating bot with persona: {persona['name']}")
    logger.debug(f"Bot configuration: {config}")

    logger.warning(f"**BOT NAME: {persona['name']}**")
    logger.warning(f"**SYSTEM PROMPT in meetingbaas.py**")
    logger.warning(f"System prompt: {persona['prompt']}")
    logger.warning(f"**SYSTEM PROMPT END**")

    response = requests.post(url, json=config, headers=headers)
    if response.status_code == 200:
        bot_id = response.json().get("bot_id")
        logger.success(f"Bot created successfully with ID: {bot_id}")
        return bot_id
    else:
        error_msg = f"Failed to create bot: {response.json()}"
        logger.error(error_msg)
        raise Exception(error_msg)


def delete_bot(bot_id):
    delete_url = f"https://api.meetingbaas.com/bots/{bot_id}"
    headers = {
        "Content-Type": "application/json",
        "x-meeting-baas-api-key": API_KEY,
    }

    logger.info(f"Attempting to delete bot with ID: {bot_id}")
    response = requests.delete(delete_url, headers=headers)

    if response.status_code != 200:
        error_msg = f"Failed to delete bot: {response.json()}"
        logger.error(error_msg)
        raise Exception(error_msg)
    else:
        logger.success(f"Bot {bot_id} deleted successfully")


class BotManager:
    def __init__(self, args):
        self.args = args
        self.current_bot_id = None
        logger.info("BotManager initialized with args: {}", args)

    def run(self):
        logger.info("Starting BotManager")
        signal.signal(signal.SIGINT, self.signal_handler)

        while True:
            try:
                self.get_or_update_urls()
                self.create_and_manage_bot()
            except Exception as e:
                logger.exception(f"An error occurred during bot management: {e}")
                if self.current_bot_id:
                    self.delete_current_bot()
                time.sleep(5)

    def get_or_update_urls(self):
        """Get or update URLs in the order: ngrok -> persona -> meeting URL"""
        if not self.args.ngrok_url:
            logger.info("Prompting for ngrok URL")
            self.args.ngrok_url = get_user_input(
                "Enter the ngrok URL (must start with https://): ", validate_url
            )
            self.args.ngrok_url = "wss://" + self.args.ngrok_url[8:]

        if not self.args.persona_name:
            self.args.persona_name = get_persona_selection()

        if not self.args.meeting_url:
            logger.info("Prompting for meeting URL")
            self.args.meeting_url = get_user_input(
                "Enter the meeting URL (must start with https://): ", validate_url
            )

        logger.debug(
            f"URLs configured - Meeting: {self.args.meeting_url}, WSS: {self.args.ngrok_url}"
        )

    def create_and_manage_bot(self):
        self.current_bot_id = create_baas_bot(
            self.args.meeting_url, self.args.ngrok_url, self.args.persona_name
        )

        logger.warning(f"Bot name: {self.args.persona_name}")

        logger.info("\nOptions:")
        logger.info("- Press Enter to respawn bot with same URLs")
        logger.info("- Enter 'n' to input new URLs")
        logger.info("- Enter 'p' to select a new persona")
        logger.info("- Press Ctrl+C to exit")

        user_choice = input().strip().lower()
        logger.debug(f"User selected option: {user_choice}")

        self.delete_current_bot()

        if user_choice == "n":
            logger.info("User requested new URLs")
            self.args.meeting_url = None
            self.args.ngrok_url = None
        elif user_choice == "p":
            logger.info("User requested new persona")
            self.args.persona_name = None

    def delete_current_bot(self):
        if self.current_bot_id:
            try:
                delete_bot(self.current_bot_id)
            except Exception as e:
                logger.exception(f"Error deleting bot: {e}")
            finally:
                self.current_bot_id = None

    def signal_handler(self, signum, frame):
        logger.warning("Ctrl+C detected, initiating cleanup...")
        self.delete_current_bot()
        logger.success("Bot cleaned up successfully")
        logger.info("Exiting...")
        exit(0)


def main():
    parser = argparse.ArgumentParser(description="Meeting BaaS Bot")
    parser.add_argument(
        "--meeting-url", help="The meeting URL (must start with https://)"
    )
    parser.add_argument("--ngrok-url", help="The ngrok URL (must start with https://)")
    parser.add_argument(
        "--persona-name",
        help="The name of the persona to use (e.g., 'interviewer', 'pair_programmer')",
    )

    args = parser.parse_args()
    logger.info("Starting application with arguments: {}", args)

    bot_manager = BotManager(args)
    bot_manager.run()


if __name__ == "__main__":
    main()

# Example usage:
# python meeting_baas_bot.py
# or
# python meeting_baas_bot.py --meeting-url https://example.com/meeting --ngrok-url https://example.ngrok.io
