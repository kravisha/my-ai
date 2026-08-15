"""Thin wrapper around the reasoning model call.

Deliberately minimal for Milestone 1 - the seed of a future Model Adapter
Layer, not a full pluggable provider registry (only one model in play).
"""

import os

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

_client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

MODEL = "claude-sonnet-5"


def call_reasoning_model(system: str, messages: list, tools: list, max_tokens: int = 2048):
    return _client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
        tools=tools,
    )
