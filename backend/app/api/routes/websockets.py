import json
import asyncio
from datetime import datetime, timezone
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.api.websocket_manager import connection_manager
from app.core.time import utc_isoformat
from app.core.config import get_allowed_origins, get_rate_limit, get_rate_limit_window_seconds
from app.core.logging import log_exception
from app.core.rate_limit import rate_limiter
from app.db.session import get_session_factory
from app.models import User
from app.schemas.conversations import MessageCreate
from app.schemas.websockets import WebSocketMessageRequest
from app.security.websocket_tickets import (
    WEBSOCKET_SUBPROTOCOL,
    ticket_from_subprotocols,
    websocket_ticket_store,
)
from app.services.conversations import (
    AuthenticationExpiredError,
    ConversationAccessError,
    MessageIdempotencyConflictError,
    create_message,
    get_conversation_user,
)

router = APIRouter(tags=["websockets"])
logger = logging.getLogger("relay.websocket")


def _authenticate_and_authorize(conversation_id: int, user_id: int) -> User | None:
    with get_session_factory()() as session:
        try:
            return get_conversation_user(session, conversation_id, user_id)
        except ConversationAccessError:
            return None


def _persist_message(
    conversation_id: int,
    user_id: int,
    content: str,
    authentication_expires_at: datetime,
    client_message_id: str | None = None,
) -> tuple[dict, bool]:
    with get_session_factory()() as session:
        user = session.get(User, user_id)
        if user is None:
            raise ConversationAccessError
        message, created = create_message(
            session,
            conversation_id,
            user,
            content,
            authentication_expires_at=authentication_expires_at,
            client_message_id=client_message_id,
        )
        return {
            "type": "message.created",
            "data": {
                "id": message.id,
                "conversation_id": message.conversation_id,
                "sender_id": user.id,
                "sender_username": user.username,
                "content": message.content,
                "client_message_id": message.client_message_id,
                "created_at": utc_isoformat(message.created_at),
            },
        }, created


@router.websocket("/ws/conversations/{conversation_id}")
async def conversation_websocket(websocket: WebSocket, conversation_id: int) -> None:
    origin = websocket.headers.get("origin")
    if origin is not None and origin.rstrip("/") not in get_allowed_origins():
        logger.warning(
            "WebSocket origin rejected",
            extra={
                "event": "websocket.origin_rejected",
                "conversation_id": conversation_id,
                "close_code": 4403,
            },
        )
        await websocket.close(code=4403, reason="WebSocket origin is not allowed.")
        return

    ticket = websocket_ticket_store.consume(
        ticket_from_subprotocols(websocket.headers.get("sec-websocket-protocol"))
    )
    if ticket is None:
        logger.warning(
            "WebSocket authentication failed",
            extra={
                "event": "websocket.authentication_failed",
                "conversation_id": conversation_id,
                "close_code": 4401,
            },
        )
        await websocket.close(code=4401, reason="Invalid or expired WebSocket ticket.")
        return

    user_id = ticket.user_id
    try:
        user = _authenticate_and_authorize(conversation_id, user_id)
    except Exception as exc:
        log_exception(
            logger,
            "websocket.authentication_error",
            exc,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        await websocket.close(code=1011, reason="Authentication service unavailable.")
        return
    if user is None:
        logger.warning(
            "WebSocket conversation access denied",
            extra={
                "event": "websocket.access_denied",
                "user_id": user_id,
                "conversation_id": conversation_id,
                "close_code": 4403,
            },
        )
        await websocket.close(code=4403, reason="Conversation access denied.")
        return

    if ticket.authentication_expires_at <= datetime.now(timezone.utc):
        logger.warning(
            "WebSocket authentication expired before connect",
            extra={
                "event": "websocket.authentication_expired",
                "user_id": user_id,
                "conversation_id": conversation_id,
                "close_code": 4408,
            },
        )
        await websocket.close(code=4408, reason="Authentication expired.")
        return

    user_id = user.id
    await connection_manager.connect(
        websocket,
        conversation_id,
        user_id,
        ticket.authentication_expires_at,
        subprotocol=WEBSOCKET_SUBPROTOCOL,
    )
    logger.info(
        "WebSocket connected",
        extra={"event": "websocket.connected", "user_id": user_id, "conversation_id": conversation_id},
    )
    try:
        await websocket.send_json(
            {
                "type": "connection.ready",
                "data": {"conversation_id": conversation_id, "user_id": user_id},
            }
        )
        while True:
            try:
                remaining = (
                    ticket.authentication_expires_at - datetime.now(timezone.utc)
                ).total_seconds()
                if remaining <= 0:
                    await connection_manager.close_if_expired(
                        websocket, conversation_id, user_id
                    )
                    return
                if await connection_manager.close_if_expired(websocket, conversation_id, user_id):
                    return
                raw_payload = await asyncio.wait_for(
                    websocket.receive_text(), timeout=remaining
                )
            except asyncio.TimeoutError:
                if await connection_manager.close_if_expired(
                    websocket, conversation_id, user_id
                ):
                    return
                continue
            except WebSocketDisconnect:
                raise

            request = None
            try:
                if await connection_manager.close_if_expired(
                    websocket, conversation_id, user_id
                ):
                    return
                request = WebSocketMessageRequest.model_validate_json(raw_payload)
                message_request = MessageCreate(content=request.content)
            except (json.JSONDecodeError, ValidationError, ValueError):
                await websocket.send_json(
                    {
                        "type": "error",
                        "data": {
                            "code": "invalid_message",
                            "client_message_id": getattr(request, "client_message_id", None),
                            "detail": "Send a message.send event with non-empty content up to 5000 characters.",
                        },
                    }
                )
                continue

            if not rate_limiter.allow(
                "websocket_message", str(user_id),
                get_rate_limit("WEBSOCKET_MESSAGE", 30),
                get_rate_limit_window_seconds("WEBSOCKET_MESSAGE", 10),
            ):
                logger.warning(
                    "WebSocket message rate limited",
                    extra={
                        "event": "rate_limit.rejected",
                        "category": "websocket_message",
                        "user_id": user_id,
                        "conversation_id": conversation_id,
                        "status_code": 429,
                    },
                )
                await websocket.send_json(
                    {
                        "type": "error",
                        "data": {
                            "code": "rate_limited",
                            "client_message_id": request.client_message_id,
                            "detail": "You are sending messages too quickly. Please try again shortly.",
                        },
                    }
                )
                continue

            try:
                event, created = _persist_message(
                    conversation_id,
                    user_id,
                    message_request.content,
                    ticket.authentication_expires_at,
                    request.client_message_id,
                )
            except AuthenticationExpiredError:
                await connection_manager.close_if_expired(
                    websocket, conversation_id, user_id
                )
                return
            except MessageIdempotencyConflictError:
                await websocket.send_json(
                    {
                        "type": "error",
                        "data": {
                            "code": "idempotency_conflict",
                            "client_message_id": request.client_message_id,
                            "detail": "client_message_id was already used with different message content.",
                        },
                    }
                )
                continue
            except Exception as exc:
                log_exception(
                    logger,
                    "websocket.message_save_error",
                    exc,
                    user_id=user_id,
                    conversation_id=conversation_id,
                )
                await websocket.send_json(
                    {
                        "type": "error",
                        "data": {
                            "code": "message_not_saved",
                            "client_message_id": request.client_message_id,
                            "detail": "The message could not be saved.",
                        },
                    }
                )
                continue
            if created:
                await connection_manager.broadcast(conversation_id, event)
            else:
                await websocket.send_json(event)
    except WebSocketDisconnect:
        logger.info(
            "WebSocket disconnected",
            extra={"event": "websocket.disconnected", "user_id": user_id, "conversation_id": conversation_id},
        )
    except Exception as exc:
        log_exception(
            logger,
            "websocket.unexpected_error",
            exc,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        try:
            await websocket.send_json(
                {"type": "error", "data": {"code": "internal_error", "detail": "An unexpected server error occurred."}}
            )
        except Exception:
            pass
        try:
            await websocket.close(code=1011, reason="Internal server error.")
        except Exception:
            pass
    finally:
        connection_manager.disconnect(websocket, conversation_id, user_id)
