import argparse
import os
import signal
import sys
import time
import uuid

import requests
from dotenv import load_dotenv
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO")

from config.persona_utils import persona_manager
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
    available_personas = persona_manager.list_personas()
    logger.info("\nAvailable personas:")
    for persona_key in available_personas:
        persona = persona_manager.get_persona(persona_key)
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


def get_baas_bot_dedup_key(character_name: str, is_recorder_only: bool) -> str:
    if is_recorder_only:
        return "BaaS-Recorder"
    return character_name


def create_baas_bot(meeting_url, ngrok_url, persona_name=None, recorder_only=False):
    if recorder_only:
        config = {
            "meeting_url": meeting_url,
            "bot_name": "BaaS Meeting Recorder",
            "recording_mode": "speaker_view",
            "bot_image": "https://i0.wp.com/fishingbooker-prod-blog-backup.s3.amazonaws.com/blog/media/2019/06/14152536/Largemouth-Bass-1024x683.jpg",
            "entry_message": "I will only record this meeting to check the quality of the data recorded by MeetingBaas API through this meeting bot. To learn more about Meeting Baas, visit meetingbaas.com. Data recorded in this meeting will not be used for any other purpose than this quality check, in accordance with MeetingBaas's privacy policy, https://meetingbaas.com/privacy.",
            "reserved": False,
            "speech_to_text": {"provider": "Default"},
            "automatic_leave": {"waiting_room_timeout": 600},
            "deduplication_key": get_baas_bot_dedup_key(persona_name, recorder_only),
            "extra": {
                "deduplication_key": get_baas_bot_dedup_key(persona_name, recorder_only)
            },
            #"webhook_url": "https://webhook-test.com/ce63096bd2c0f2793363fd3fb32bc066",
        }
    else:
        # Existing bot creation logic
        if not persona_name:
            persona_name = get_persona_selection()

        try:
            persona = persona_manager.get_persona(persona_name)
        except KeyError:
            try:
                folder_name = persona_name.lower().replace(" ", "_")
                persona = persona_manager.get_persona(folder_name)
            except KeyError:
                logger.error(
                    f"Persona '{persona_name}' not found in available personas."
                )
                return None

        config = {
            "meeting_url": meeting_url,
            "bot_name": persona["name"],
            "recording_mode": "speaker_view",
            "bot_image": persona["image"],
            "entry_message": persona["entry_message"],
            "reserved": False,
            "speech_to_text": {"provider": "Default"},
            "automatic_leave": {"waiting_room_timeout": 600},
            "deduplication_key": get_baas_bot_dedup_key(persona_name, recorder_only),
            "streaming": {"input": ngrok_url, "output": ngrok_url},
            "extra": {
                "deduplication_key": get_baas_bot_dedup_key(persona_name, recorder_only)
            },
            # "webhook_url": "https://webhook-test.com/ce63096bd2c0f2793363fd3fb32bc066",
        }

    # Create bot using configuration
    url = "https://api.meetingbaas.com/bots"
    headers = {
        "Content-Type": "application/json",
        "x-meeting-baas-api-key": API_KEY,
    }

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
                if not self.args.recorder_only:
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
            self.args.meeting_url,
            self.args.ngrok_url,
            self.args.persona_name,
            self.args.recorder_only,
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
            logger.warning("User requested new URLs")
            self.args.meeting_url = None
            self.args.ngrok_url = None
        elif user_choice == "p":
            logger.warning("User requested new persona")
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
    parser.add_argument(
        "--recorder-only",
        action="store_true",
        help="Run as recording-only bot",
    )
    parser.add_argument(
        "--config", type=str, help="JSON configuration for recorder bot"
    )

    args = parser.parse_args()
    logger.info("Starting application with arguments: {}", args)

    bot_manager = BotManager(args)
    bot_manager.run()


if __name__ == "__main__":
    main()
