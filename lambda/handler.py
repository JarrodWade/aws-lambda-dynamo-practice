"""API Gateway -> Lambda router for the practice chatbot.

Routes (HTTP API v2 routeKey strings):

    POST /chat
        body: {"userId": "...", "sessionId": "?", "message": "..."}
        -> calls Bedrock, persists turn, returns reply

    GET  /history?userId=...&limit=20&cursor=...
        -> paginated message history (newest first)

    POST /payments
        body: {"userId": "...", "amount": 142.67, "currency": "USD"}
        -> creates a PENDING PaymentIntent

    GET  /payments?userId=...
    GET  /payments?status=PENDING
        -> lists payments for one user, OR all payments by status (GSI1)

    POST /payments/{paymentId}/pay
        body: {"userId": "...", "confirmationId": "..."}
        -> conditional PENDING -> PAID transition
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any

import bedrock
import ddb

logger = logging.getLogger()
logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class _DecimalEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if isinstance(o, Decimal):
            return float(o) if o % 1 else int(o)
        return super().default(o)


def _response(status: int, body: Any) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body, cls=_DecimalEncoder),
    }


def _parse_body(event: dict[str, Any]) -> dict[str, Any]:
    raw = event.get("body")
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _qs(event: dict[str, Any]) -> dict[str, str]:
    return event.get("queryStringParameters") or {}


def _path_params(event: dict[str, Any]) -> dict[str, str]:
    return event.get("pathParameters") or {}


# ---------------------------------------------------------------------------
# handlers
# ---------------------------------------------------------------------------


def _handle_chat(event: dict[str, Any]) -> dict[str, Any]:
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


def _handle_history(event: dict[str, Any]) -> dict[str, Any]:
    qs = _qs(event)
    user_id = (qs.get("userId") or "").strip()
    if not user_id:
        return _response(400, {"error": "userId query param is required"})

    try:
        limit = int(qs.get("limit", "20"))
    except ValueError:
        return _response(400, {"error": "limit must be an integer"})

    cursor = qs.get("cursor")
    items, next_cursor = ddb.list_messages_page(user_id, limit=limit, cursor=cursor)
    return _response(
        200,
        {
            "userId": user_id,
            "count": len(items),
            "items": items,
            "nextCursor": next_cursor,
        },
    )


def _handle_create_payment(event: dict[str, Any]) -> dict[str, Any]:
    body = _parse_body(event)
    user_id = (body.get("userId") or "").strip()
    amount = body.get("amount")
    currency = (body.get("currency") or "USD").strip().upper()

    if not user_id or amount is None:
        return _response(400, {"error": "userId and amount are required"})

    try:
        item = ddb.create_payment_intent(
            user_id=user_id,
            amount=amount,
            currency=currency,
            payment_id=body.get("paymentId"),
        )
    except ValueError as e:
        return _response(409, {"error": str(e)})
    except Exception:  # noqa: BLE001
        logger.exception("create_payment_intent failed")
        return _response(500, {"error": "could not create payment intent"})

    return _response(201, {"payment": item})


def _handle_list_payments(event: dict[str, Any]) -> dict[str, Any]:
    qs = _qs(event)
    user_id = (qs.get("userId") or "").strip()
    status = (qs.get("status") or "").strip().upper()
    try:
        limit = int(qs.get("limit", "20"))
    except ValueError:
        return _response(400, {"error": "limit must be an integer"})

    if status:
        try:
            items = ddb.list_payments_by_status(status, limit=limit)
        except ValueError as e:
            return _response(400, {"error": str(e)})
        return _response(200, {"status": status, "count": len(items), "items": items})

    if not user_id:
        return _response(400, {"error": "provide userId or status"})

    items = ddb.list_user_payments(user_id, limit=limit)
    return _response(200, {"userId": user_id, "count": len(items), "items": items})


def _handle_mark_paid(event: dict[str, Any]) -> dict[str, Any]:
    body = _parse_body(event)
    payment_id = (_path_params(event).get("paymentId") or "").strip()
    user_id = (body.get("userId") or "").strip()
    confirmation_id = (body.get("confirmationId") or "").strip()

    if not user_id or not payment_id or not confirmation_id:
        return _response(
            400, {"error": "paymentId, userId, and confirmationId are required"}
        )

    try:
        updated = ddb.mark_payment_paid(user_id, payment_id, confirmation_id)
    except ValueError as e:
        return _response(409, {"error": str(e)})
    except Exception:  # noqa: BLE001
        logger.exception("mark_payment_paid failed")
        return _response(500, {"error": "could not mark payment paid"})

    return _response(200, {"payment": updated})


# ---------------------------------------------------------------------------
# router
# ---------------------------------------------------------------------------


_ROUTES = {
    "POST /chat": _handle_chat,
    "GET /history": _handle_history,
    "POST /payments": _handle_create_payment,
    "GET /payments": _handle_list_payments,
    "POST /payments/{paymentId}/pay": _handle_mark_paid,
}


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    route_key = event.get("routeKey") or ""
    logger.info("route=%s rawPath=%s", route_key, event.get("rawPath"))

    handler = _ROUTES.get(route_key)
    if handler is None:
        return _response(404, {"error": f"no route for {route_key}"})

    try:
        return handler(event)
    except Exception:  # noqa: BLE001
        logger.exception("unhandled error in %s", route_key)
        return _response(500, {"error": "internal server error"})
