"""API Gateway -> Lambda entrypoint for the practice chatbot.

Expected request body (JSON):
    {
        "userId": "user-123",
        "sessionId": "sess-abc",   // optional, defaults to "default"
        "message": "I want to pay my bill"
    }

Response body (JSON):
    {
        "reply": "...",
        "userId": "user-123",
        "sessionId": "sess-abc"
    }
"""

from __future__ import annotations

import json
import logging
from typing import Any

import ddb
import bedrock

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _response(status: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body),
    }


def _parse_body(event: dict[str, Any]) -> dict[str, Any]:
    raw = event.get("body")
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    logger.info("event: %s", json.dumps(event)[:1000])

    body = _parse_body(event)
    user_id = (body.get("userId") or "").strip()
    session_id = (body.get("sessionId") or "default").strip()
    message = (body.get("message") or "").strip()

    if not user_id or not message:
        return _response(400, {"error": "userId and message are required"})

    request_id = (event.get("requestContext") or {}).get("requestId")
    if request_id and not ddb.record_idempotency(request_id):
        return _response(200, {"reply": "(duplicate request ignored)"})

    ddb.upsert_session(user_id, session_id)
    ddb.put_message(user_id, session_id, role="USER", text=message)

    history = ddb.list_recent_messages(user_id)

    try:
        reply = bedrock.generate_reply(history=history[:-1], user_text=message)
    except Exception:  # noqa: BLE001
        logger.exception("bedrock call failed")
        return _response(502, {"error": "model invocation failed"})

    ddb.put_message(user_id, session_id, role="BOT", text=reply)

    return _response(
        200,
        {"reply": reply, "userId": user_id, "sessionId": session_id},
    )
