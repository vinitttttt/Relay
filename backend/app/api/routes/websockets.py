import json
import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.api.websocket_manager import connection_manager
from app.core.config import get_allowed_origins, get_rate_limit, get_rate_limit_window_seconds
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
                "created_at": message.created_at.isoformat(),
            },
        }, created


@router.websocket("/ws/conversations/{conversation_id}")
async def conversation_websocket(websocket: WebSocket, conversation_id: int) -> None:
    origin = websocket.headers.get("origin")
    if origin is not None and origin.rstrip("/") not in get_allowed_origins():
        await websocket.close(code=4403, reason="WebSocket origin is not allowed.")
        return

    ticket = websocket_ticket_store.consume(
        ticket_from_subprotocols(websocket.headers.get("sec-websocket-protocol"))
    )
    if ticket is None:
        await websocket.close(code=4401, reason="Invalid or expired WebSocket ticket.")
        return

    user_id = ticket.user_id
    user = _authenticate_and_authorize(conversation_id, user_id)
    if user is None:
        await websocket.close(code=4403, reason="Conversation access denied.")
        return

    if ticket.authentication_expires_at <= datetime.now(timezone.utc):
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
            except Exception:
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
        pass
    finally:
        connection_manager.disconnect(websocket, conversation_id, user_id)
