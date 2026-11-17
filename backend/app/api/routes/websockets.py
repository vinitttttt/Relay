import json

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.api.websocket_manager import connection_manager
from app.db.session import get_session_factory
from app.models import User
from app.schemas.conversations import MessageCreate
from app.schemas.websockets import WebSocketMessageRequest
from app.security.tokens import InvalidAccessToken, decode_access_token
from app.services.conversations import (
    ConversationAccessError,
    create_message,
    get_conversation_user,
)

router = APIRouter(tags=["websockets"])


def _authenticate_and_authorize(conversation_id: int, token: str | None) -> User | None:
    if not token:
        return None
    try:
        user_id = decode_access_token(token)
    except (InvalidAccessToken, jwt.InvalidTokenError, RuntimeError):
        return None
    with get_session_factory()() as session:
        try:
            return get_conversation_user(session, conversation_id, user_id)
        except ConversationAccessError:
            return None


def _persist_message(conversation_id: int, user_id: int, content: str) -> dict:
    with get_session_factory()() as session:
        user = session.get(User, user_id)
        if user is None:
            raise ConversationAccessError
        message = create_message(session, conversation_id, user, content)
        return {
            "type": "message.created",
            "data": {
                "id": message.id,
                "conversation_id": message.conversation_id,
                "sender_id": user.id,
                "sender_username": user.username,
                "content": message.content,
                "created_at": message.created_at.isoformat(),
            },
        }


@router.websocket("/ws/conversations/{conversation_id}")
async def conversation_websocket(websocket: WebSocket, conversation_id: int) -> None:
    user = _authenticate_and_authorize(conversation_id, websocket.query_params.get("token"))
    if user is None:
        await websocket.close(code=4401, reason="Invalid authentication or conversation access.")
        return

    user_id = user.id
    await connection_manager.connect(websocket, conversation_id, user_id)
    try:
        await websocket.send_json(
            {
                "type": "connection.ready",
                "data": {"conversation_id": conversation_id, "user_id": user_id},
            }
        )
        while True:
            try:
                raw_payload = await websocket.receive_text()
                request = WebSocketMessageRequest.model_validate_json(raw_payload)
                message_request = MessageCreate(content=request.content)
            except (json.JSONDecodeError, ValidationError, ValueError):
                await websocket.send_json(
                    {
                        "type": "error",
                        "data": {
                            "code": "invalid_message",
                            "detail": "Send a message.send event with non-empty content up to 5000 characters.",
                        },
                    }
                )
                continue

            try:
                event = _persist_message(conversation_id, user_id, message_request.content)
            except Exception:
                await websocket.send_json(
                    {
                        "type": "error",
                        "data": {
                            "code": "message_not_saved",
                            "detail": "The message could not be saved.",
                        },
                    }
                )
                continue
            await connection_manager.broadcast(conversation_id, event)
    except WebSocketDisconnect:
        pass
    finally:
        connection_manager.disconnect(websocket, conversation_id, user_id)
