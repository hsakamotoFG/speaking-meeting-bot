"""Main application module for the Speaking Meeting Bot API."""

import argparse
import logging
import os
import sys
from typing import Dict, List, Optional, Tuple

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from app.routes import router as app_router
from app.websockets import websocket_router
from meetingbaas_pipecat.utils.logger import configure_logger
from utils.ngrok import LOCAL_DEV_MODE, NGROK_URL_INDEX, NGROK_URLS, load_ngrok_urls

# Configure logging with the prettier logger
logger = configure_logger()
logger.name = "meetingbaas-api"  # Set logger name after configuring

# Set logging level for pipecat WebSocket client to WARNING to reduce noise
pipecat_ws_logger = logging.getLogger("pipecat.transports.network.websocket_client")
pipecat_ws_logger.setLevel(logging.WARNING)


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.

    Returns:
        A configured FastAPI application
    """
    app = FastAPI(
        title="Speaking Meeting Bot API",
        description="API for deploying AI-powered speaking agents in video meetings. Combines MeetingBaas for meeting connectivity with Pipecat for voice AI processing.",
        version="0.0.1",
        contact={
            "name": "Speaking Bot API by MeetingBaas",
            "url": "https://meetingbaas.com",
        },
        openapi_url="/openapi.json",  # Explicitly set the OpenAPI schema URL
        docs_url="/docs",  # Swagger UI path
        # redoc_url="/redoc",  # Explicitly set the ReDoc URL
    )

    # Set the server URL for the OpenAPI schema
    app.openapi_schema = None  # Clear any existing schema

    # Override the openapi method to add server information
    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema

        openapi_schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )

        openapi_schema["servers"] = [
            {
                "url": "https://speaking.meetingbaas.com",
                "description": "Production server",
            },
            {"url": "/", "description": "Local development server"},
        ]
        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include the routers
    app.include_router(app_router)
    app.include_router(websocket_router)

    # Add a health endpoint
    @app.get("/health", tags=["system"])
    async def health():
        """Health check endpoint"""
        return {
            "status": "ok",
            "service": "speaking-meeting-bot",
            "version": "1.0.0",
            "endpoints": [
                {
                    "path": "/bots",
                    "method": "POST",
                    "description": "Create a bot that joins a meeting",
                },
                {
                    "path": "/bots/{bot_id}",
                    "method": "DELETE",
                    "description": "Remove a bot using its bot ID",
                },
                {"path": "/", "method": "GET", "description": "API root endpoint"},
                {
                    "path": "/health",
                    "method": "GET",
                    "description": "Health check endpoint",
                },
                {
                    "path": "/ws/{client_id}",
                    "method": "WebSocket",
                    "description": "WebSocket endpoint for client connections",
                },
                {
                    "path": "/pipecat/{client_id}",
                    "method": "WebSocket",
                    "description": "WebSocket endpoint for Pipecat connections",
                },
            ],
        }

    return app


def start_server(host: str = "0.0.0.0", port: int = 8766, local_dev: bool = False):
    """Start the WebSocket server"""
    # Global variables for ngrok URL tracking
    NGROK_URLS = []
    NGROK_URL_INDEX = 0

    # Set LOCAL_DEV_MODE based on parameter
    LOCAL_DEV_MODE = local_dev

    # Reset the ngrok URL counter when starting the server
    NGROK_URL_INDEX = 0

    if local_dev:
        print("\n⚠️ Starting in local development mode")
        # Cache the ngrok URLs at server start
        NGROK_URLS = load_ngrok_urls()

        if NGROK_URLS:
            print(f"✅ {len(NGROK_URLS)} Bot(s) available from Ngrok")
            for i, url in enumerate(NGROK_URLS):
                print(f"  Bot {i + 1}: {url}")
        else:
            print(
                "⚠️ No ngrok URLs configured. Using auto-detection for WebSocket URLs."
            )
        print("\n")

    logger.info(f"Starting WebSocket server on {host}:{port}")

    # Pass the local_dev flag as a command-line argument to the uvicorn process
    args = [
        sys.executable,
        "-m",
        "uvicorn",
        "app:app",  # Use the app from app/__init__.py
        "--host",
        host,
        "--port",
        str(port),
    ]

    if local_dev:
        args.extend(["--reload"])

        # Create a file that uvicorn will read on startup to set LOCAL_DEV_MODE
        with open(".local_dev_mode", "w") as f:
            f.write("true")
    else:
        # Make sure we don't have the flag set if not in local dev mode
        if os.path.exists(".local_dev_mode"):
            os.remove(".local_dev_mode")

    # Use os.execv to replace the current process with uvicorn
    # This way all arguments are directly passed to uvicorn
    os.execv(sys.executable, args)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start the MeetingBaas Bot API server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8766, help="Port to listen on")
    parser.add_argument(
        "--local-dev",
        action="store_true",
        help="Run in local development mode with ngrok",
    )

    args = parser.parse_args()
    start_server(args.host, args.port, args.local_dev)
