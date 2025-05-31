import openai
import json
import os
from typing import Any, Dict, Optional
from loguru import logger

async def extract_details(
    prompt: str
) -> Optional[Dict[str, Any]]:
    """Uses LLM to extract structured persona details from a text prompt."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.error("OPENAI_API_KEY environment variable not set.")
        return None

    try:
        # Use async client
        client = openai.AsyncOpenAI(api_key=api_key)

        llm_prompt = f'''Analyze the following text prompt and extract the persona's name, gender, a brief description for image generation, and a list of characteristics.
If no explicit name is mentioned, suggest a suitable name based on the description. If no name can be suggested, return null.

Prompt: {prompt}

Extract the information in the following JSON format. If a field cannot be determined, use null or an empty list:
{{
    "name": "string or null",
    "gender": "male, female, non-binary, or null",
    "description": "string or null",
    "characteristics": ["string", ...]
}}

JSON Output:'''

        response = await client.chat.completions.create(
            model="gpt-4o-mini", # Use a cost-effective model for extraction
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "You are a highly skilled AI assistant capable of extracting structured information from text."},
                {"role": "user", "content": llm_prompt}
            ],
            temperature=0.1, # Low temperature for precise extraction
            max_tokens=500 # Limit token usage
        )

        content = response.choices[0].message.content
        if content:
            extracted_data = json.loads(content)
            
            # Apply default values and handle nulls/empty strings
            extracted_data["name"] = extracted_data.get("name") or "Bot"
            extracted_data["gender"] = extracted_data.get("gender") or "male"

            extracted_data['description'] = extracted_data.get("description") or prompt

            # Ensure characteristics is a list, default to empty list if null or not list
            characteristics = extracted_data.get("characteristics")
            extracted_data["characteristics"] = characteristics if isinstance(characteristics, list) else []
            
            return extracted_data
        else:
            logger.warning("LLM returned empty content for persona details extraction.")
            return None

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON from LLM response: {e}")
        return None
    except Exception as e:
        logger.error(f"Error during LLM persona details extraction: {e}")
        return None 