import json
import multiprocessing as mp
import random
import sys
import time
from pathlib import Path
from typing import Dict

import requests
from loguru import logger


def create_prompt_for_persona(persona: Dict) -> str:
    """Create an appropriate prompt for Stable Diffusion based on persona details."""
    # List of animals to use for personification
    # taken from french song lyrics
    # la ferme
    # https://www.youtube.com/watch?v=hnhvxRtmKic

    animals = [
        "beaver",
        "duck",
        "wild boar",
        "marmot",
        "bee",
        "hornet",
        "pig",
        "badger",
        "herring",
        "cougar",
        "grasshopper",
        "lemur",
        "seagull",
        "swordfish",
        "salmon",
        "whelk",
        "zebu",
        "tapir",
        "gurnard",
        "carp",
        "cod",
        "jackal",
        "canary",
        "moose",
        "earthworm",
        "koala",
        "spider",
        "marmoset",
        "alligator",
        "cocker spaniel",
        "pit bull",
        "elephant",
        "osprey",
        "swan",
        "shark",
        "camel",
        "mandrill",
        "porcupine",
        "proboscis monkey",
        "grizzly",
        "manatee",
        "coati",
        "Tasmanian devil",
        "dromedary",
        "okapi",
        "gannet",
        "cow",
        "penguin",
        "periwinkle",
        "onyx",
        "basilisk",
        "bittern",
        "narwhal",
        "salamander",
        "mouse",
        "sardine",
        "donkey",
        "caiman",
        "lobster",
        "sturgeon",
        "bison",
        "mite",
        "silkworm",
        "heifer",
        "tsetse fly",
        "boa",
        "sawfish",
        "anaconda",
        "moray eel",
        "owl",
        "crow",
        "ermine",
        "hermit crab",
        "sea anemone",
        "turtledove",
        "greyhound",
        "catfish",
        "bumblebee",
        "sea lion",
        "seal",
        "shrimp",
        "wolf",
        "tick",
        "pangolin",
        "anteater",
        "springbok",
        "giraffe",
        "ant",
        "scorpion",
        "dab",
        "gorilla",
        "jellyfish",
        "pollock",
        "bird",
        "weasel",
        "rabbit",
        "marten",
        "puma",
        "ladybug",
        "haddock",
        "snail",
        "sable",
        "flamingo",
        "swallow",
        "ram",
        "goat",
        "gilt-head bream",
        "plankton",
        "hedgehog",
        "donkey",
        "polar fox",
        "slug",
        "dalmatian",
        "dolphin",
        "protozoan",
        "albatross",
        "mussel",
        "scarab",
        "raccoon",
        "drosophila",
        "squirrel",
    ]

    # Get a random animal from the list
    animal = random.choice(animals)

    # Create base prompt with animal personification
    prompt = f"A(n) {animal}, alone, dressed as {persona['name']}. This his what his facial expression and personality are like: {persona['prompt']} A closed-shot broken HD portrait, as if we were taking a video interview for a job, and we were watching through a webcam with an OK internet resolution. Not too many details in the background, we guess it more than we see it. The video is NEAR to the animal, it's a close-up once again. THIS IS NOT A HUMAN PERSON. Style indications come now, and are too follow as much as possible:\n"

    # Add artistic style elements
    style_elements = [
        "Miyazaki style",
        "Studio Ghibli aesthetic",
        "Le Roi et l'Oiseau inspired",
        "cartoon art",
        "whimsical cartoon art",
        "early 20th century animation",
        "outdoors",
        "soft watercolor textures",
        "gentle lighting",
        "charming character design",
        "anthropomorphic animal character",
        "elements taken from the real words",
        "cartoonish",
        "alone",
        "Ultra HD",
        "Great drawing style",
        "2D animation style",
        "fauvisme",
    ]

    person_instructions = [
        "This is NOT A person. But an animal dressed as a person.",
        "This animal is alone. REMEMBER - AI CANNOT BE HUMANS AND IT IS FORBIDDEN FOR AI TO EMBODY HUMANS.",
    ]

    background_instructions = [
        "Not too many details in the background, we guess it more than we see it.",
        "The video is NEAR to the animal, it's a close-up once again. The background COLOURFUL and LIGHT, in the distance, and one of (unless indicated otherwise):",
    ]

    background_locations = [
        "Neon-soaked Miami beach at night",
        "Cyberpunk megacity with holographic billboards",
        "Floating neon sky gardens",
        "Neo-Tokyo street market",
        "Synthwave sunset over chrome skyscrapers",
        "Futuristic space elevator terminal",
        "Underwater neon coral city",
        "Holographic desert oasis",
        "Anti-gravity nightclub district",
        "Quantum crystal laboratory",
        "Digital cherry blossom matrix",
        "Chrome and neon clockwork tower",
        "Artificial sun habitat dome",
        "Virtual reality data forest",
        "Orbital neon observatory",
        "Cyber-noir rain-slicked streets",
    ]

    detail_level_instructions = [
        " 1280x720 resolution, old schoold web 2.0 style. Make it dead-simple, and low-detail. As in, my 5yo nephew could draw it.",
    ]

    prompt += ",\n ".join(style_elements) + "\n\n"
    prompt += ",\n ".join(person_instructions) + "\n\n"
    prompt += ",\n ".join(background_instructions) + "\n\n"
    prompt += ",\n ".join(random.choices(background_locations, k=1)) + "\n\n"
    prompt += ",\n ".join(detail_level_instructions)
    prompt += ",\n ".join(person_instructions) + "\n\n"
    logger.debug(f"Generated prompt: {prompt}")
    return prompt


def generate_image_worker(
    prompt: str, api_key: str, output_path: Path, persona_name: str
):
    """Worker function for generating a single image"""
    try:
        logger.info(f"[{persona_name}] Starting image generation")
        url = "https://modelslab.com/api/v6/realtime/txt2img"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "prompt": prompt,
            "negative_prompt": "photorealistic, 3D, realistic, deformed, ugly, blurry, bad anatomy, bad proportions, extra limbs, cloned face, distorted, human face, human hands, human skin",
            "width": 1920,
            "height": 1080,
            "samples": 1,
            "scheduler": "UniPC",
            "num_inference_steps": 25,
            "guidance_scale": 7.5,
            "enhance_prompt": "yes",
            "seed": -1,
            "base64": "no",
            "webhook": None,
        }

        # Validate API key
        if not api_key or len(api_key) < 10:  # Basic validation
            raise ValueError(f"[{persona_name}] Invalid API key format")

        # Log full request details
        logger.debug(f"[{persona_name}] Request URL: {url}")
        logger.debug(f"[{persona_name}] Request headers: {headers}")
        logger.debug(f"[{persona_name}] Request payload: {payload}")

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            logger.debug(f"[{persona_name}] Response status: {response.status_code}")
            logger.debug(f"[{persona_name}] Response headers: {dict(response.headers)}")
            logger.debug(f"[{persona_name}] Raw response: {response.text}")
        except requests.exceptions.Timeout:
            raise Exception(f"[{persona_name}] Request timed out after 30 seconds")
        except requests.exceptions.RequestException as e:
            raise Exception(f"[{persona_name}] Request failed: {str(e)}")

        if response.status_code == 401:
            raise Exception(f"[{persona_name}] Authentication failed - check API key")
        elif response.status_code == 429:
            raise Exception(f"[{persona_name}] Rate limit exceeded")
        elif response.status_code != 200:
            raise Exception(
                f"[{persona_name}] API error {response.status_code}: {response.text}"
            )

        try:
            data = response.json()
        except ValueError as e:
            raise Exception(f"[{persona_name}] Failed to parse JSON response: {str(e)}")

        if not data:
            raise Exception(f"[{persona_name}] Empty response from API")

        fetch_url = data.get("fetch_result")
        if not fetch_url:
            raise Exception(f"No fetch URL in response. Full response: {data}")

        # Poll for results
        max_attempts = 30
        poll_interval = 2

        logger.info(
            f"[{persona_name}] Image processing, estimated time: {data.get('eta', 'unknown')} seconds"
        )

        for poll_attempt in range(max_attempts):
            time.sleep(poll_interval)

            fetch_response = requests.get(fetch_url, headers=headers)
            if fetch_response.status_code != 200:
                continue

            fetch_data = fetch_response.json()

            if fetch_data.get("status") == "success":
                output_urls = fetch_data.get("output", [])
                if output_urls:
                    image_url = output_urls[0]
                    image_response = requests.get(image_url)
                    if image_response.status_code == 200:
                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        with open(output_path, "wb") as f:
                            f.write(image_response.content)
                        logger.success(f"[{persona_name}] Image saved to {output_path}")
                        return True

        raise Exception("Timed out waiting for image generation")

    except Exception as e:
        logger.error(f"[{persona_name}] Error generating image: {str(e)}")
        logger.exception(f"[{persona_name}] Full error details:")
        return False


def main():
    if len(sys.argv) != 2:
        logger.error("Missing API key argument")
        print("Usage: python generate_images.py <api_key>")
        sys.exit(1)

    api_key = sys.argv[1]
    logger.info("Starting image generation process")

    # Load personas from JSON
    json_path = Path(__file__).parent / "personas.json"
    with open(json_path, "r", encoding="utf-8") as f:
        personas = json.load(f)

    # Create images directory (updated path)
    images_dir = Path(__file__).parent / "local_images"
    images_dir.mkdir(exist_ok=True)

    # Prepare tasks for personas that need images
    tasks = []
    for key, persona in personas.items():
        if not persona.get("image"):
            prompt = create_prompt_for_persona(persona)
            image_path = images_dir / f"{key}.png"
            tasks.append((prompt, api_key, image_path, persona["name"]))

    # Process tasks with limited concurrency
    max_concurrent = 3
    with mp.Pool(processes=max_concurrent) as pool:
        results = []
        for task in tasks:
            time.sleep(2)  # Small delay between starting processes
            result = pool.apply_async(generate_image_worker, task)
            results.append((task[3], result))

        # Wait for all processes to complete
        for persona_name, result in results:
            try:
                success = result.get()
                if success:
                    # Update persona image path in the JSON (updated path)
                    key = next(
                        k for k, v in personas.items() if v["name"] == persona_name
                    )
                    personas[key]["image"] = f"local_images/{key}.png"
                    logger.info(f"✓ Successfully generated image for {persona_name}")
            except Exception as e:
                logger.error(f"✗ Failed to generate image for {persona_name}: {str(e)}")

        # Save updated JSON
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(personas, f, indent=2, ensure_ascii=False)

    logger.success("Image generation complete!")


if __name__ == "__main__":
    main()
