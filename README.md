# Speaking Bot

Deploy AI-powered meeting agents that can join and participate in Zoom and Microsoft Teams (and soon on Zoom!). These agents have distinct personalities and can engage in conversations based on predefined personas defined in Markdown files.

## Overview

The Meeting Agent Bot allows you to:

-   Launch one or more AI agents into Google Meet or Microsoft Teams (Zoom is due ASAP)
-   Give each agent a unique personality, knowledge and conversation style
-   Run multiple instances locally (2 max using Ngrok) or scale to web deployment
-   Create custom personas with distinct characteristics and behaviors

## Technical Stack

### Technical Components

-   Poetry - Dependency management
-   Protocol Buffers - Message serialization
-   Ngrok - Local server exposure
-   Pipecat's WebsocketServerTransport - Real-time communication

### APIs & 3rd Party Services

-   MeetingBaas - For meeting bots inside Google Meet and Microsoft Teams
-   OpenAI - For conversation generation
-   Cartesia - For Text-to-Speech conversion
-   Deepgram - For Speech-to-Text conversion
-   UTFS - For image storage
-   Replicate - For image generation

## Persona System

### Bot Service

-   Real-time audio processing pipeline
-   WebSocket-based communication
-   Tool integration (weather, time)
-   Voice activity detection
-   Message context management

-   Dynamic persona loading from markdown files
-   Customizable personality traits and behaviors
-   Support for multiple languages
-   Voice characteristic customization
-   Image generation for persona avatars
-   Metadata management for each persona

### Persona Structure

Each persona is defined in the `@personas` directory with:

-   A README.md defining their personality
-   Space for additional markdown files to expand behavior

### Example Persona Structure

```
@personas/
└── quantum_physicist/
    ├── README.md
    └── (additional beVhavior files)
```

## Prerequisites

-   Python 3.x
-   `grpc_tools` for protocol buffer compilation
-   Ngrok (for local deployment)
-   Poetry for dependency management

## Installation

### 1. Set Up Poetry Environment

```bash
# Install Poetry (Unix/macOS)
curl -sSL https://install.python-poetry.org | python3 -

# Install Poetry (Windows)
(Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | py -

# Install dependencies
poetry install

# Activate virtual environment
poetry shell
```

### 2. Compile Protocol Buffers

```bash
poetry run python -m grpc_tools.protoc --proto_path=./protobufs --python_out=./protobufs frames.proto
```

### 3. Configure Environment

```bash
cp env.example .env
```

Edit `.env` with your MeetingBaas credentials.

## Running Meeting Agents

### Single Agent Deployment

To launch one agent into a meeting:

```bash
poetry run python scripts/batch.py -c 1 --meeting-url <your-meeting-url>
```

### Multiple Agent Deployment

To launch two agents simultaneously:

```bash
poetry run python scripts/batch.py -c 2 --meeting-url <your-meeting-url>
```

### Local Deployment with Ngrok

For 1-2 agents, use Ngrok to expose your local server:

```bash
ngrok start --all --config ~/.config/ngrok/ngrok.yml,./config/ngrok/config.yml
```

### Web Deployment

For more than 2 agents, deploy to a web server to avoid Ngrok limitations.

## Future Extensibility

The persona architecture is designed to support:

-   Additional behavior and knowledge files
-   More detailed conversation patterns
-   Specialized knowledge bases
-   Custom interaction styles

## Troubleshooting

-   Verify Poetry environment is activated
-   Check Ngrok connection status
-   Validate environment variables
-   Ensure unique Ngrok URLs for multiple agents

For more detailed information about specific personas or deployment options, check the respective documentation in the `@personas` directory.

## Troubleshooting WebSocket Connections

### Handling Timing Issues with ngrok and Meeting Baas Bots

Sometimes, due to WebSocket connection delays through ngrok, the Meeting Baas bots may join the meeting before your local bot connects. If this happens:

-   Simply press `Enter` to respawn your bot
-   This will reinitiate the connection and allow your bot to join the meeting

This is a normal occurrence and can be easily resolved with a quick bot respawn.
