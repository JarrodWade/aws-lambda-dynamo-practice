"""Amazon Bedrock helper for chat responses.

Uses the Bedrock Converse API so the same code works across many models
(e.g. Amazon Nova, Anthropic Claude). Configure via env vars:

    BEDROCK_MODEL_ID   e.g. "amazon.nova-micro-v1:0"
    BEDROCK_REGION     e.g. "us-east-1"
    MAX_OUTPUT_TOKENS  e.g. "300"
"""

from __future__ import annotations

import os
from typing import Iterable

import boto3

_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "amazon.nova-micro-v1:0")
_REGION = os.environ.get("BEDROCK_REGION", os.environ.get("AWS_REGION", "us-east-1"))
_MAX_OUTPUT_TOKENS = int(os.environ.get("MAX_OUTPUT_TOKENS", "300"))
_TEMPERATURE = float(os.environ.get("TEMPERATURE", "0.3"))

_SYSTEM_PROMPT = (
    "You are a friendly billing assistant chatbot used for practice. "
    "Keep responses short (1-3 sentences). Never claim to actually charge "
    "a payment; this is a sandbox. If asked about payments, walk the user "
    "through the steps but do not request real card details."
)

_client = boto3.client("bedrock-runtime", region_name=_REGION)


def _to_converse_messages(history: Iterable[dict]) -> list[dict]:
    """Map stored chat items to Bedrock Converse format."""
    messages: list[dict] = []
    for item in history:
        role = "user" if item.get("role") == "USER" else "assistant"
        text = item.get("text", "")
        if not text:
            continue
        messages.append({"role": role, "content": [{"text": text}]})
    return messages


def generate_reply(history: list[dict], user_text: str) -> str:
    messages = _to_converse_messages(history)
    messages.append({"role": "user", "content": [{"text": user_text}]})

    response = _client.converse(
        modelId=_MODEL_ID,
        system=[{"text": _SYSTEM_PROMPT}],
        messages=messages,
        inferenceConfig={
            "maxTokens": _MAX_OUTPUT_TOKENS,
            "temperature": _TEMPERATURE,
        },
    )

    output_message = response["output"]["message"]
    parts = output_message.get("content", [])
    return "".join(p.get("text", "") for p in parts).strip()
