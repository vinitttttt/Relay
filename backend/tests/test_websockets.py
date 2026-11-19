from datetime import datetime, timedelta, timezone
import time
from concurrent.futures import ThreadPoolExecutor

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
from app.security.websocket_tickets import (
    TICKET_SUBPROTOCOL_PREFIX,
    WEBSOCKET_SUBPROTOCOL,
    WebSocketTicketStore,
    websocket_ticket_store,
)
from app.services.conversations import AuthenticationExpiredError


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


def issue_ticket(client: TestClient, user_id: int, token: str | None = None) -> str:
    access_token = token or create_access_token(user_id)
    response = client.post(
        "/api/v1/auth/websocket-ticket",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert response.status_code == 200
    return response.json()["ticket"]


def ticket_protocols(ticket: str | None = None) -> list[str]:
    protocols = [WEBSOCKET_SUBPROTOCOL]
    if ticket is not None:
        protocols.append(f"{TICKET_SUBPROTOCOL_PREFIX}{ticket}")
    return protocols


def test_websocket_authentication_success_and_rejections(
    websocket_client, test_engine, monkeypatch
) -> None:
    ids, first_id, _ = make_users_and_conversations(test_engine)
    url = f"/ws/conversations/{first_id}"
    alice_ticket = issue_ticket(websocket_client, ids["alice"])

    with websocket_client.websocket_connect(
        url, subprotocols=ticket_protocols(alice_ticket)
    ) as websocket:
        assert websocket.receive_json() == {
            "type": "connection.ready",
            "data": {"conversation_id": first_id, "user_id": ids["alice"]},
        }

    assert websocket_client.post("/api/v1/auth/websocket-ticket").status_code == 401
    assert websocket_client.post(
        "/api/v1/auth/websocket-ticket",
        headers={"Authorization": "Bearer not-a-jwt"},
    ).status_code == 401
    issuance = websocket_client.post(
        "/api/v1/auth/websocket-ticket",
        headers={"Authorization": f"Bearer {create_access_token(ids['alice'])}"},
    )
    assert issuance.status_code == 200
    assert set(issuance.json()) == {"ticket", "expires_in"}
    assert issuance.json()["ticket"] != create_access_token(ids["alice"])
    assert 1 <= issuance.json()["expires_in"] <= 30

    carol_ticket = issue_ticket(websocket_client, ids["carol"])
    for offered_protocols in (
        ticket_protocols(),
        ticket_protocols("invalid-ticket"),
        ticket_protocols(carol_ticket),
    ):
        with pytest.raises(WebSocketDisconnect) as disconnected:
            with websocket_client.websocket_connect(url, subprotocols=offered_protocols):
                pass
        assert disconnected.value.code in (4401, 4403)

    monkeypatch.setattr(websocket_ticket_store, "ttl_seconds", 0.02)
    expired_ticket = issue_ticket(websocket_client, ids["alice"])
    time.sleep(0.04)
    with pytest.raises(WebSocketDisconnect) as disconnected:
        with websocket_client.websocket_connect(
            url, subprotocols=ticket_protocols(expired_ticket)
        ):
            pass
    assert disconnected.value.code == 4401


def test_message_is_persisted_and_broadcast_only_in_its_conversation(
    websocket_client, test_engine
) -> None:
    ids, first_id, second_id = make_users_and_conversations(test_engine)
    sender_ticket = issue_ticket(websocket_client, ids["alice"])
    recipient_ticket = issue_ticket(websocket_client, ids["bob"])
    unrelated_ticket = issue_ticket(websocket_client, ids["carol"])
    with websocket_client.websocket_connect(
        f"/ws/conversations/{first_id}", subprotocols=ticket_protocols(sender_ticket)
    ) as sender, websocket_client.websocket_connect(
        f"/ws/conversations/{first_id}", subprotocols=ticket_protocols(recipient_ticket)
    ) as recipient, websocket_client.websocket_connect(
        f"/ws/conversations/{second_id}", subprotocols=ticket_protocols(unrelated_ticket)
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
        f"/ws/conversations/{first_id}",
        subprotocols=ticket_protocols(issue_ticket(websocket_client, ids["alice"])),
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
        f"/ws/conversations/{first_id}",
        subprotocols=ticket_protocols(issue_ticket(websocket_client, ids["alice"])),
    ) as websocket:
        websocket.receive_json()
        assert connection_manager.connection_count(first_id, ids["alice"]) == 1
    assert connection_manager.connection_count(first_id, ids["alice"]) == 0


def test_websocket_ticket_is_single_use(websocket_client, test_engine) -> None:
    ids, first_id, _ = make_users_and_conversations(test_engine)
    ticket = issue_ticket(websocket_client, ids["alice"])
    url = f"/ws/conversations/{first_id}"
    protocols = ticket_protocols(ticket)
    with websocket_client.websocket_connect(url, subprotocols=protocols) as websocket:
        assert websocket.receive_json()["type"] == "connection.ready"
        assert websocket.accepted_subprotocol == WEBSOCKET_SUBPROTOCOL
    with pytest.raises(WebSocketDisconnect) as disconnected:
        with websocket_client.websocket_connect(url, subprotocols=protocols):
            pass
    assert disconnected.value.code == 4401


def test_ticket_consumption_is_atomic_across_threads() -> None:
    store = WebSocketTicketStore()
    ticket, _ = store.issue(17, datetime.now(timezone.utc) + timedelta(minutes=1))
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(store.consume, [ticket] * 8))
    assert sum(result is not None for result in results) == 1


def test_websocket_closes_when_main_access_token_expires(
    websocket_client, test_engine
) -> None:
    ids, first_id, _ = make_users_and_conversations(test_engine)
    now = datetime.now(timezone.utc)
    short_token = jwt.encode(
        {
            "sub": str(ids["alice"]),
            "iat": now,
            "exp": now + timedelta(seconds=1.5),
            "type": "access",
        },
        get_jwt_secret_key(),
        algorithm="HS256",
    )
    ticket = issue_ticket(websocket_client, ids["alice"], short_token)
    with websocket_client.websocket_connect(
        f"/ws/conversations/{first_id}", subprotocols=ticket_protocols(ticket)
    ) as websocket:
        assert websocket.receive_json()["type"] == "connection.ready"
        time.sleep(1.6)
        with pytest.raises(WebSocketDisconnect) as disconnected:
            websocket.receive_json()
    assert disconnected.value.code == 4408
    assert connection_manager.connection_count(first_id, ids["alice"]) == 0


def test_message_persistence_rejects_expired_authentication(
    websocket_client, test_engine
) -> None:
    ids, first_id, _ = make_users_and_conversations(test_engine)
    expired_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    with pytest.raises(AuthenticationExpiredError):
        websocket_routes._persist_message(
            first_id, ids["alice"], "must not persist", expired_at
        )
    with Session(test_engine) as session:
        assert session.scalars(select(Message)).all() == []
