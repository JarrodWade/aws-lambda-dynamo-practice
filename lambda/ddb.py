"""DynamoDB helpers for the practice chatbot."""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

_TABLE_NAME = os.environ["TABLE_NAME"]
_SESSION_TTL_SECONDS = int(os.environ.get("SESSION_TTL_SECONDS", str(7 * 24 * 3600)))
_MAX_HISTORY_TURNS = int(os.environ.get("MAX_HISTORY_TURNS", "10"))

_dynamodb = boto3.resource("dynamodb")
_table = _dynamodb.Table(_TABLE_NAME)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expires_at() -> int:
    return int(time.time()) + _SESSION_TTL_SECONDS


def get_session(user_id: str, session_id: str) -> dict[str, Any] | None:
    resp = _table.get_item(
        Key={"PK": f"USER#{user_id}", "SK": f"SESSION#{session_id}"}
    )
    return resp.get("Item")


def upsert_session(user_id: str, session_id: str, state: str = "ACTIVE") -> None:
    _table.put_item(
        Item={
            "PK": f"USER#{user_id}",
            "SK": f"SESSION#{session_id}",
            "itemType": "ConversationSession",
            "userId": user_id,
            "sessionId": session_id,
            "state": state,
            "updatedAt": _now_iso(),
            "expiresAt": _expires_at(),
        }
    )


def put_message(
    user_id: str,
    session_id: str,
    role: str,
    text: str,
) -> dict[str, Any]:
    """Append a chat message item. Role is 'USER' or 'BOT'."""
    iso_ts = _now_iso()
    message_id = uuid.uuid4().hex[:8]
    item = {
        "PK": f"USER#{user_id}",
        "SK": f"MSG#{iso_ts}#{message_id}",
        "itemType": "ChatMessage",
        "userId": user_id,
        "sessionId": session_id,
        "role": role,
        "text": text,
        "createdAt": iso_ts,
        "expiresAt": _expires_at(),
    }
    _table.put_item(
        Item=item,
        ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
    )
    return item


def list_recent_messages(user_id: str, limit: int | None = None) -> list[dict[str, Any]]:
    """Return the most recent messages for a user, oldest-first."""
    limit = limit or _MAX_HISTORY_TURNS * 2
    resp = _table.query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
        ExpressionAttributeValues={
            ":pk": f"USER#{user_id}",
            ":prefix": "MSG#",
        },
        ScanIndexForward=False,
        Limit=limit,
    )
    items = resp.get("Items", [])
    return list(reversed(items))


def record_idempotency(request_id: str) -> bool:
    """Return True if this request_id was newly recorded, False if duplicate."""
    try:
        _table.put_item(
            Item={
                "PK": f"IDEMPOTENCY#{request_id}",
                "SK": "REQUEST",
                "itemType": "Idempotency",
                "createdAt": _now_iso(),
                "expiresAt": int(time.time()) + 24 * 3600,
            },
            ConditionExpression="attribute_not_exists(PK)",
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise
