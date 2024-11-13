import json
from pathlib import Path

from loguru import logger


# Load personas from JSON file
def load_personas():
    json_path = Path(__file__).parent / "personas.json"
    try:
        with open(json_path, "r") as f:
            personas = json.load(f)
            # Set default image URL if empty
            for persona in personas.values():
                if not persona["image"]:
                    persona["image"] = (
                        "https://example.com/default-avatar.png"  # Set a default image URL
                    )
            return personas
    except Exception as e:
        logger.error(f"Failed to load personas from JSON: {e}")
        raise


PERSONAS = load_personas()


def list_personas():
    """
    Returns a sorted list of available persona names
    """
    return sorted(PERSONAS.keys())


def get_persona(name=None):
    """
    Get a persona by name, or return a random one if no name is provided
    """
    import random

    interaction_instructions = """

Remember:
1. Start by clearly stating who you are
2. When someone new speaks, ask them who they are
3. Then consider and express how their role/expertise could help you"""

    if name:
        if name not in PERSONAS:
            raise KeyError(
                f"Persona '{name}' not found in available personas. Valid options are: {', '.join(PERSONAS.keys())}"
            )
        persona = PERSONAS[name].copy()  # Create a copy to avoid modifying the original
        logger.warning(f"Using specified persona: {name}")
    else:
        persona = random.choice(list(PERSONAS.values())).copy()  # Create a copy
        logger.warning(f"No persona specified, randomly selected: {persona['name']}")

    persona["prompt"] = persona["prompt"] + interaction_instructions
    return persona


def get_persona_by_name(name):
    """
    Get a specific persona by name. Raises KeyError if persona doesn't exist.

    Args:
        name (str): The name of the persona to retrieve

    Returns:
        dict: The persona configuration

    Raises:
        KeyError: If the requested persona doesn't exist
    """
    for key, persona in PERSONAS.items():
        if persona["name"] == name:
            return persona

    raise KeyError(
        f"Persona '{name}' not found in available personas. Valid options are: {', '.join(p['name'] for p in PERSONAS.values())}"
    )
