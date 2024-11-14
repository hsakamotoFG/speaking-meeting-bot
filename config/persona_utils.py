import json
from pathlib import Path
from typing import Dict, Optional

from loguru import logger


class PersonaManager:
    def __init__(self, json_path: Optional[Path] = None):
        self.json_path = json_path or Path(__file__).parent / "personas.json"

    def load_personas(self) -> Dict:
        """Load personas from JSON file"""
        try:
            with open(self.json_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load personas: {e}")
            return {}

    def save_personas(self, personas: Dict) -> bool:
        """Save personas to JSON file"""
        try:
            with open(self.json_path, "w", encoding="utf-8") as f:
                json.dump(personas, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f"Failed to save personas: {e}")
            return False

    def update_persona_image(self, persona_key: str, image_path: str) -> bool:
        """Update image path for a specific persona"""
        personas = self.load_personas()
        if persona_key in personas:
            personas[persona_key]["image"] = image_path
            return self.save_personas(personas)
        return False

    def update_persona_image_url(self, persona_key: str, image_url: str) -> bool:
        """Update image URL for a specific persona"""
        personas = self.load_personas()
        if persona_key in personas:
            personas[persona_key]["image"] = image_url
            return self.save_personas(personas)
        return False
