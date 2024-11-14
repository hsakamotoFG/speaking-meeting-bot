import json
import random
from pathlib import Path
from typing import Dict, List, Optional, Union

from loguru import logger


class PersonaManager:
    def __init__(self, json_path: Optional[Path] = None):
        """Initialize PersonaManager with optional custom JSON path"""
        self.json_path = json_path or Path(__file__).parent / "personas.json"
        self.personas = self.load_personas()

    def load_personas(self) -> Dict:
        """Load personas from JSON file without default image fallback"""
        try:
            with open(self.json_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load personas: {e}")
            raise

    def save_personas(self, personas: Optional[Dict] = None) -> bool:
        """Save personas to JSON file"""
        try:
            with open(self.json_path, "w", encoding="utf-8") as f:
                json.dump(personas or self.personas, f, indent=2, ensure_ascii=False)
            self.personas = personas or self.personas
            return True
        except Exception as e:
            logger.error(f"Failed to save personas: {e}")
            return False

    def list_personas(self) -> List[str]:
        """Returns a sorted list of available persona names"""
        return sorted(self.personas.keys())

    def get_persona(self, name: Optional[str] = None) -> Dict:
        """Get a persona by name or return a random one"""
        interaction_instructions = """
Remember:
1. Start by clearly stating who you are
2. When someone new speaks, ask them who they are
3. Then consider and express how their role/expertise could help you"""

        if name:
            if name not in self.personas:
                raise KeyError(
                    f"Persona '{name}' not found. Valid options: {', '.join(self.personas.keys())}"
                )
            persona = self.personas[name].copy()
            logger.info(f"Using specified persona: {name}")
        else:
            persona = random.choice(list(self.personas.values())).copy()
            logger.info(f"Randomly selected persona: {persona['name']}")

        # Only set default image if needed for display purposes
        if not persona.get("image"):
            persona["image"] = ""  # Empty string instead of default URL

        persona["prompt"] = persona["prompt"] + interaction_instructions
        return persona

    def get_persona_by_name(self, name: str) -> Dict:
        """Get a specific persona by display name"""
        for persona in self.personas.values():
            if persona["name"] == name:
                return persona.copy()
        raise KeyError(
            f"Persona '{name}' not found. Valid options: {', '.join(p['name'] for p in self.personas.values())}"
        )

    def update_persona_image(self, key: str, image_path: Union[str, Path]) -> bool:
        """Update image path/URL for a specific persona"""
        if key in self.personas:
            self.personas[key]["image"] = str(image_path)
            return self.save_personas()
        logger.error(f"Persona key '{key}' not found")
        return False

    def get_image_urls(self) -> Dict[str, str]:
        """Get mapping of persona keys to their image URLs"""
        return {key: persona.get("image", "") for key, persona in self.personas.items()}

    def needs_image_upload(self, key: str, domain: str = "uploadthing.com") -> bool:
        """Check if a persona needs image upload"""
        if key not in self.personas:
            return False
        current_url = self.personas[key].get("image", "")
        return not (current_url and domain in current_url)


# Global instance for easy access
persona_manager = PersonaManager()
