"""Data models for the Speaking Meeting Bot API."""

from typing import Any, Dict, List, Optional
from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl


class BotRequest(BaseModel):
    """Request model for creating a speaking bot in a meeting."""

    # Define ONLY the fields we want in our API
    meeting_url: str = Field(
        ...,
        description="URL of the Google Meet, Zoom or Microsoft Teams meeting to join",
    )
    bot_name: str = Field("", description="Name to display for the bot in the meeting")
    personas: Optional[List[str]] = Field(
        None,
        description="List of persona names to use. The first available will be selected.",
    )
    meeting_baas_api_key: str
    bot_image: Optional[str] = None
    entry_message: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None
    enable_tools: bool = True

    # NOTE: streaming_audio_frequency is intentionally excluded and handled internally

    class Config:
        json_schema_extra = {
            "example": {
                "meeting_url": "https://meet.google.com/abc-defg-hij",
                "bot_name": "Meeting Assistant",
                "personas": ["helpful_assistant", "meeting_facilitator"],
                "meeting_baas_api_key": "mb_api_xxxxxxxxxxxxxxxxxxxxxxxx",
                "bot_image": "https://example.com/bot-avatar.png",
                "entry_message": "Hello! I'm here to assist with the meeting.",
                "enable_tools": True,
                "extra": {"company": "ACME Corp", "meeting_purpose": "Weekly sync"},
            }
        }


class JoinResponse(BaseModel):
    """Response model for a bot joining a meeting"""

    bot_id: str = Field(
        ...,
        description="The MeetingBaas bot ID used for API operations with MeetingBaas",
    )


class LeaveResponse(BaseModel):
    """Response model for a bot leaving a meeting"""

    ok: bool


class LeaveBotRequest(BaseModel):
    """Request model for making a bot leave a meeting"""

    meeting_baas_api_key: str = Field(
        ..., description="Your MeetingBaas API key for authentication"
    )
    bot_id: Optional[str] = Field(
        None,
        description="The MeetingBaas bot ID to remove from the meeting. This will also close the WebSocket connection made through Pipecat by this bot.",
    )


class PersonaImageRequest(BaseModel):
    """Request model for generating persona images."""
    name: str = Field(..., description="Name of the persona")
    description: str = Field(None, description="Description of the persona")
    gender: Optional[str] = Field(None, description="Gender of the persona")
    characteristics: Optional[List[str]] = Field(None, description="List of characteristics like blue eyes, etc.")


class PersonaImageResponse(BaseModel):
    """Response model for generated persona images."""
    image_url: str = Field(..., description="URL of the generated image")
    prompt: str = Field(..., description="Prompt used for image generation")
    generated_at: str = Field(..., description="Timestamp of generation")
