"""DynamoDB helpers for the practice chatbot.

Single-table design:
    PK / SK            itemType            notes
    USER#<id> / PROFILE                MemberProfile
    USER#<id> / SESSION#<sid>          ConversationSession  (TTL via expiresAt)
    USER#<id> / MSG#<isoTs>#<msgId>    ChatMessage           (TTL via expiresAt)
    USER#<id> / PAYMENT#<paymentId>    PaymentIntent
    IDEMPOTENCY#<reqId> / REQUEST      Idempotency           (TTL)

GSI1 (queue by status):
    GSI1PK = PAYMENT_STATUS#<status>
    GSI1SK = <createdAt>#<paymentId>
Used to list e.g. all PENDING payments in time order.
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
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


def _expires_at(seconds: int | None = None) -> int:
    return int(time.time()) + (seconds or _SESSION_TTL_SECONDS)


# ---------------------------------------------------------------------------
# Sessions + chat messages
# ---------------------------------------------------------------------------


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


def put_message(user_id: str, session_id: str, role: str, text: str) -> dict[str, Any]:
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
    """Return the most recent messages for a user, oldest-first (for LLM context)."""
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
    return list(reversed(resp.get("Items", [])))


def list_messages_page(
    user_id: str,
    limit: int = 20,
    cursor: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Paginated message history for the GET /history endpoint.

    Returns (items_newest_first, next_cursor). Cursor is the SK of the
    last returned item; pass it back in to get the next page.
    """
    kwargs: dict[str, Any] = {
        "KeyConditionExpression": "PK = :pk AND begins_with(SK, :prefix)",
        "ExpressionAttributeValues": {
            ":pk": f"USER#{user_id}",
            ":prefix": "MSG#",
        },
        "ScanIndexForward": False,
        "Limit": min(max(limit, 1), 100),
    }
    if cursor:
        kwargs["ExclusiveStartKey"] = {
            "PK": f"USER#{user_id}",
            "SK": cursor,
        }

    resp = _table.query(**kwargs)
    items = resp.get("Items", [])
    last_key = resp.get("LastEvaluatedKey")
    next_cursor = last_key["SK"] if last_key else None
    return items, next_cursor


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def record_idempotency(request_id: str) -> bool:
    try:
        _table.put_item(
            Item={
                "PK": f"IDEMPOTENCY#{request_id}",
                "SK": "REQUEST",
                "itemType": "Idempotency",
                "createdAt": _now_iso(),
                "expiresAt": _expires_at(24 * 3600),
            },
            ConditionExpression="attribute_not_exists(PK)",
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


# ---------------------------------------------------------------------------
# PaymentIntent: state machine with conditional writes + GSI1 queue
# ---------------------------------------------------------------------------


PAYMENT_STATUSES = {"PENDING", "PAID", "CANCELLED", "FAILED"}


def _payment_item(
    user_id: str,
    payment_id: str,
    amount: Decimal,
    currency: str,
    status: str,
    created_at: str,
) -> dict[str, Any]:
    return {
        "PK": f"USER#{user_id}",
        "SK": f"PAYMENT#{payment_id}",
        "itemType": "PaymentIntent",
        "userId": user_id,
        "paymentId": payment_id,
        "amount": amount,
        "currency": currency,
        "status": status,
        "createdAt": created_at,
        "updatedAt": created_at,
        # GSI1: queue of payments by status, ordered by createdAt
        "GSI1PK": f"PAYMENT_STATUS#{status}",
        "GSI1SK": f"{created_at}#{payment_id}",
    }


def create_payment_intent(
    user_id: str,
    amount: float | str | Decimal,
    currency: str = "USD",
    payment_id: str | None = None,
) -> dict[str, Any]:
    """Create a new PENDING payment intent. Fails if paymentId already exists."""
    payment_id = payment_id or f"pay-{uuid.uuid4().hex[:10]}"
    created_at = _now_iso()
    # DynamoDB requires Decimal for numbers (not float)
    amount_decimal = amount if isinstance(amount, Decimal) else Decimal(str(amount))

    item = _payment_item(
        user_id=user_id,
        payment_id=payment_id,
        amount=amount_decimal,
        currency=currency,
        status="PENDING",
        created_at=created_at,
    )
    try:
        _table.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise ValueError(f"PaymentIntent {payment_id} already exists") from e
        raise
    return item


def get_payment_intent(user_id: str, payment_id: str) -> dict[str, Any] | None:
    resp = _table.get_item(
        Key={"PK": f"USER#{user_id}", "SK": f"PAYMENT#{payment_id}"}
    )
    return resp.get("Item")


def mark_payment_paid(
    user_id: str,
    payment_id: str,
    confirmation_id: str,
) -> dict[str, Any]:
    """Transition PENDING -> PAID atomically. Raises ValueError on bad state."""
    now = _now_iso()
    try:
        resp = _table.update_item(
            Key={"PK": f"USER#{user_id}", "SK": f"PAYMENT#{payment_id}"},
            UpdateExpression=(
                "SET #st = :paid,"
                "    confirmationId = :cid,"
                "    paidAt = :now,"
                "    updatedAt = :now,"
                "    GSI1PK = :gsi_pk,"
                "    GSI1SK = :gsi_sk"
            ),
            ConditionExpression="attribute_exists(PK) AND #st = :pending",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={
                ":pending": "PENDING",
                ":paid": "PAID",
                ":cid": confirmation_id,
                ":now": now,
                ":gsi_pk": "PAYMENT_STATUS#PAID",
                ":gsi_sk": f"{now}#{payment_id}",
            },
            ReturnValues="ALL_NEW",
        )
        return resp.get("Attributes", {})
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise ValueError(
                f"PaymentIntent {payment_id} not found or not in PENDING state"
            ) from e
        raise


def list_user_payments(
    user_id: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """All payments for a user, newest first (uses base table)."""
    resp = _table.query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
        ExpressionAttributeValues={
            ":pk": f"USER#{user_id}",
            ":prefix": "PAYMENT#",
        },
        ScanIndexForward=False,
        Limit=limit,
    )
    return resp.get("Items", [])


def list_payments_by_status(
    status: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Cross-user queue lookup via GSI1 (e.g. all PENDING payments)."""
    if status not in PAYMENT_STATUSES:
        raise ValueError(f"Unknown status: {status}")
    resp = _table.query(
        IndexName="GSI1",
        KeyConditionExpression="GSI1PK = :pk",
        ExpressionAttributeValues={":pk": f"PAYMENT_STATUS#{status}"},
        ScanIndexForward=True,
        Limit=limit,
    )
    return resp.get("Items", [])
