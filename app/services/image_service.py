"""Service for handling image generation using Replicate."""

from typing import Optional
from loguru import logger
from PIL import Image
import requests
from io import BytesIO
import os
import replicate
from pathlib import Path
from dotenv import load_dotenv
from config.image_uploader import UTFSUploader
from config.prompts import IMAGE_NEGATIVE_PROMPT

# Load environment variables
load_dotenv()

class ImageService:
    """Service for handling image generation and processing."""
    
    def __init__(self):
        """Initialize the image service."""
        self.uploader = UTFSUploader(
            api_key=os.getenv("UTFS_KEY"),
            app_id=os.getenv("APP_ID")
        )
        # Set Replicate API token
        # Replicate API tokens shouldn't include the "sk_live_" prefix
        self.replicate_key = os.getenv("REPLICATE_KEY", "")
        if self.replicate_key.startswith("sk_live_"):
            self.replicate_key = self.replicate_key.replace("sk_live_", "")
        os.environ["REPLICATE_API_TOKEN"] = self.replicate_key
        logger.info("Initialized Replicate client and UTFSUploader for image generation")
    
            # Download the image
            response = requests.get(image_url)
            if response.status_code != 200:
                raise ValueError(f"Failed to download image. Status code: {response.status_code}")

            # Save to temporary file with unique name
            import uuid
            temp_path = f"temp_generated_image_{uuid.uuid4()}.png"
            with open(temp_path, "wb") as f:
                f.write(response.content)

            # Upload to UTFS
            file_url = self.uploader.upload_file(Path(temp_path))
    def process_image(self, image_url: str) -> Optional[Image.Image]:
        try:
            response = requests.get(image_url)
            response.raise_for_status()
            return Image.open(BytesIO(response.content))
        except Exception as e:
            logger.error(f"Failed to process image: {str(e)}")
            return None

# Create global instance
image_service = ImageService() 