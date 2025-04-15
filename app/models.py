"""Data models for the Speaking Meeting Bot API."""

from typing import Any, Dict, List, Optional

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
    recorder_only: bool = Field(
        False, description="If true, bot will only record meeting without speaking"
    )
    websocket_url: Optional[str] = None
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
                "recorder_only": False,
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
    client_id: str = Field(
        ...,
        description="A unique UUID for this bot instance used for WebSocket connections",
    )


class LeaveResponse(BaseModel):
    """Response model for a bot leaving a meeting"""

    ok: bool


class LeaveBotRequest(BaseModel):
    """Request model for making a bot leave a meeting"""

    meeting_baas_api_key: str = Field(
        ..., description="Your MeetingBaas API key for authentication"
    )
    client_id: Optional[str] = Field(
        None,
        description="The client UUID to identify which bot WebSocket connection to close",
    )
    bot_id: Optional[str] = Field(
        None, description="The MeetingBaas bot ID to remove from the meeting"
    )
