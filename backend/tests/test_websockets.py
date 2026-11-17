from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from starlette.websockets import WebSocketDisconnect

from app.api.routes import websockets as websocket_routes
from app.api.websocket_manager import connection_manager
from app.core.config import get_jwt_secret_key
from app.models import Conversation, ConversationMember, ConversationType, Message, User
from app.security.tokens import create_access_token


@pytest.fixture
def websocket_client(auth_client: TestClient, test_engine, monkeypatch) -> TestClient:
    factory = sessionmaker(bind=test_engine, expire_on_commit=False)
    monkeypatch.setattr(websocket_routes, "get_session_factory", lambda: factory)
    return auth_client


def make_users_and_conversations(test_engine):
    with Session(test_engine) as session:
        users = [
            User(username=name, email=f"{name}@example.test", hashed_password="test-hash")
            for name in ("alice", "bob", "carol", "dave")
        ]
        session.add_all(users)
        session.flush()
        by_name = {user.username: user for user in users}
        first = Conversation(conversation_type=ConversationType.GROUP, name="First room")
        second = Conversation(conversation_type=ConversationType.GROUP, name="Second room")
        session.add_all([first, second])
        session.flush()
        session.add_all(
            [
                ConversationMember(conversation_id=first.id, user_id=by_name["alice"].id),
                ConversationMember(conversation_id=first.id, user_id=by_name["bob"].id),
                ConversationMember(conversation_id=second.id, user_id=by_name["carol"].id),
                ConversationMember(conversation_id=second.id, user_id=by_name["dave"].id),
            ]
        )
        session.commit()
        return {name: user.id for name, user in by_name.items()}, first.id, second.id


def expired_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user_id),
            "iat": now - timedelta(minutes=2),
            "exp": now - timedelta(minutes=1),
            "type": "access",
        },
        get_jwt_secret_key(),
        algorithm="HS256",
    )


def test_websocket_authentication_success_and_rejections(
    websocket_client, test_engine
) -> None:
    ids, first_id, _ = make_users_and_conversations(test_engine)
    url = f"/ws/conversations/{first_id}"

    with websocket_client.websocket_connect(
        f"{url}?token={create_access_token(ids['alice'])}"
    ) as websocket:
        assert websocket.receive_json() == {
            "type": "connection.ready",
            "data": {"conversation_id": first_id, "user_id": ids["alice"]},
        }

    for token in (None, "not-a-jwt", expired_token(ids["alice"]), create_access_token(ids["carol"])):
        token_query = "" if token is None else f"?token={token}"
        with pytest.raises(WebSocketDisconnect) as disconnected:
            with websocket_client.websocket_connect(f"{url}{token_query}"):
                pass
        assert disconnected.value.code == 4401


def test_message_is_persisted_and_broadcast_only_in_its_conversation(
    websocket_client, test_engine
) -> None:
    ids, first_id, second_id = make_users_and_conversations(test_engine)
    with websocket_client.websocket_connect(
        f"/ws/conversations/{first_id}?token={create_access_token(ids['alice'])}"
    ) as sender, websocket_client.websocket_connect(
        f"/ws/conversations/{first_id}?token={create_access_token(ids['bob'])}"
    ) as recipient, websocket_client.websocket_connect(
        f"/ws/conversations/{second_id}?token={create_access_token(ids['carol'])}"
    ) as unrelated:
        sender.receive_json()
        recipient.receive_json()
        unrelated.receive_json()
        sender.send_json({"type": "message.send", "content": "Hello in room one"})
        delivered = recipient.receive_json()
        assert delivered["type"] == "message.created"
        assert delivered["data"] == {
            "id": delivered["data"]["id"],
            "conversation_id": first_id,
            "sender_id": ids["alice"],
            "sender_username": "alice",
            "content": "Hello in room one",
            "created_at": delivered["data"]["created_at"],
        }
        assert sender.receive_json() == delivered

        unrelated.send_json({"type": "message.send", "content": "Room two message"})
        second_event = unrelated.receive_json()
        assert second_event["data"]["conversation_id"] == second_id
        assert second_event["data"]["content"] == "Room two message"

    with Session(test_engine) as session:
        messages = session.scalars(select(Message).order_by(Message.id)).all()
        assert [(message.conversation_id, message.sender_id, message.content) for message in messages] == [
            (first_id, ids["alice"], "Hello in room one"),
            (second_id, ids["carol"], "Room two message"),
        ]


def test_invalid_payloads_are_rejected_and_sender_cannot_be_spoofed(
    websocket_client, test_engine
) -> None:
    ids, first_id, _ = make_users_and_conversations(test_engine)
    with websocket_client.websocket_connect(
        f"/ws/conversations/{first_id}?token={create_access_token(ids['alice'])}"
    ) as websocket:
        websocket.receive_json()
        for raw_payload in (
            "not json",
            {"type": "unrecognized", "content": "Hi"},
            {"type": "message.send", "content": "   "},
            {"type": "message.send", "content": "x" * 5001},
            {"type": "message.send", "content": "spoof", "sender_id": ids["bob"]},
        ):
            if isinstance(raw_payload, str):
                websocket.send_text(raw_payload)
            else:
                websocket.send_json(raw_payload)
            assert websocket.receive_json()["type"] == "error"

        websocket.send_json({"type": "message.send", "content": "trusted identity"})
        event = websocket.receive_json()
        assert event["data"]["sender_id"] == ids["alice"]
        assert event["data"]["sender_username"] == "alice"
        assert event["data"]["content"] == "trusted identity"


def test_disconnect_removes_connection(websocket_client, test_engine) -> None:
    ids, first_id, _ = make_users_and_conversations(test_engine)
    assert connection_manager.connection_count(first_id, ids["alice"]) == 0
    with websocket_client.websocket_connect(
        f"/ws/conversations/{first_id}?token={create_access_token(ids['alice'])}"
    ) as websocket:
        websocket.receive_json()
        assert connection_manager.connection_count(first_id, ids["alice"]) == 1
    assert connection_manager.connection_count(first_id, ids["alice"]) == 0
