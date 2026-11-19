import json
import logging

from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.api.routes import conversations as conversation_routes
from app.api.routes import auth as auth_routes
from app.api.routes import websockets as websocket_routes
from app.core.logging import JsonLogFormatter
from app.main import app
from app.models import Conversation, ConversationMember, ConversationType, User
from app.security.tokens import create_access_token
from app.security.websocket_tickets import TICKET_SUBPROTOCOL_PREFIX, WEBSOCKET_SUBPROTOCOL


@pytest.fixture
def websocket_client(auth_client, test_engine, monkeypatch):
    factory = sessionmaker(bind=test_engine, expire_on_commit=False)
    monkeypatch.setattr(websocket_routes, "get_session_factory", lambda: factory)
    return auth_client


def test_auth_and_validation_logs_and_responses_do_not_include_passwords(
    auth_client, caplog
) -> None:
    caplog.set_level(logging.WARNING)
    password = "secret-password-not-for-logs"
    response = auth_client.post(
        "/api/v1/auth/login",
        json={"identifier": "unknown-account", "password": password},
    )
    assert response.status_code == 401
    assert any(getattr(record, "event", None) == "authentication.failed" for record in caplog.records)
    assert password not in caplog.text

    invalid = auth_client.post(
        "/api/v1/auth/register",
        json={"username": "valid-user", "email": "valid@example.com", "password": "tiny"},
    )
    assert invalid.status_code == 422
    assert "input" not in str(invalid.json())
    assert "tiny" not in caplog.text


def test_unexpected_rest_error_is_safe_and_logs_traceback_without_exception_text(
    auth_client, test_engine, monkeypatch, caplog
) -> None:
    user = User(username="rest-error", email="rest-error@example.test", hashed_password="hash")
    with Session(test_engine) as session:
        session.add(user)
        session.commit()
        user_id = user.id

    secret_message = "never log private message content"

    def fail_create(*_args, **_kwargs):
        raise ValueError(secret_message)

    monkeypatch.setattr(conversation_routes, "create_message", fail_create)
    caplog.set_level(logging.ERROR)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/v1/conversations/1/messages",
            json={"content": "request body", "client_message_id": "error-test"},
            headers={"Authorization": f"Bearer {create_access_token(user_id)}"},
        )

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error."}
    record = next(record for record in caplog.records if getattr(record, "event", None) == "http.unexpected_error")
    assert record.exception_type == "ValueError"
    assert record.traceback
    assert secret_message not in caplog.text
    assert "request body" not in caplog.text


def test_unexpected_authentication_error_is_logged_without_credentials(
    auth_client, monkeypatch, caplog
) -> None:
    private_error = "internal auth backend included sensitive data"

    def fail_authentication(*_args, **_kwargs):
        raise RuntimeError(private_error)

    monkeypatch.setattr(auth_routes, "authenticate_user", fail_authentication)
    caplog.set_level(logging.ERROR)
    password = "credential-not-for-logs"
    response = auth_client.post(
        "/api/v1/auth/login",
        json={"identifier": "private-user", "password": password},
    )
    assert response.status_code == 500
    assert response.json() == {"detail": "Authentication could not be completed."}
    assert any(
        getattr(record, "event", None) == "authentication.login_error"
        for record in caplog.records
    )
    assert private_error not in caplog.text
    assert password not in caplog.text


def test_unexpected_websocket_error_logs_safely_and_returns_generic_error(
    websocket_client, test_engine, monkeypatch, caplog
) -> None:
    with Session(test_engine) as session:
        alice = User(username="ws-error", email="ws-error@example.test", hashed_password="hash")
        session.add(alice)
        session.flush()
        conversation = Conversation(conversation_type=ConversationType.GROUP, name="error room")
        session.add(conversation)
        session.flush()
        session.add(ConversationMember(conversation_id=conversation.id, user_id=alice.id))
        session.commit()
        user_id, conversation_id = alice.id, conversation.id

    secret_content = "private websocket message that must not be logged"

    def fail_persist(*_args, **_kwargs):
        raise RuntimeError(secret_content)

    monkeypatch.setattr(websocket_routes, "_persist_message", fail_persist)
    ticket_response = websocket_client.post(
        "/api/v1/auth/websocket-ticket",
        headers={"Authorization": f"Bearer {create_access_token(user_id)}"},
    )
    ticket = ticket_response.json()["ticket"]
    caplog.set_level(logging.ERROR)
    with websocket_client.websocket_connect(
        f"/ws/conversations/{conversation_id}",
        subprotocols=[WEBSOCKET_SUBPROTOCOL, f"{TICKET_SUBPROTOCOL_PREFIX}{ticket}"],
    ) as websocket:
        websocket.receive_json()
        websocket.send_json({
            "type": "message.send",
            "client_message_id": "safe-log-test",
            "content": secret_content,
        })
        response = websocket.receive_json()

    assert response["type"] == "error"
    assert response["data"]["code"] == "message_not_saved"
    record = next(record for record in caplog.records if getattr(record, "event", None) == "websocket.message_save_error")
    assert record.exception_type == "RuntimeError"
    assert record.user_id == user_id
    assert record.conversation_id == conversation_id
    assert secret_content not in caplog.text
    assert ticket not in caplog.text


def test_json_log_formatter_emits_safe_structured_context() -> None:
    record = logging.LogRecord("relay.test", logging.WARNING, "file.py", 3, "Rejected", (), None)
    record.event = "request.failed"
    record.status_code = 429
    record.path = "/api/v1/users/search"
    rendered = json.loads(JsonLogFormatter().format(record))
    assert rendered["event"] == "request.failed"
    assert rendered["status_code"] == 429
    assert rendered["path"] == "/api/v1/users/search"
    assert rendered["timestamp"].endswith("Z")
