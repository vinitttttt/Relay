from fastapi.testclient import TestClient
import pytest
from sqlalchemy import UniqueConstraint, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.routes import database as database_route
from app.core.config import BACKEND_ROOT, get_database_url
from app.db import session as database_session
from app.main import app
from app.models import Conversation, ConversationMember, ConversationType, Message, User

client = TestClient(app)


def test_database_url_defaults_to_backend_data(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    url = get_database_url()

    assert url.drivername == "sqlite"
    assert url.database == str(BACKEND_ROOT / "data" / "relay.db")


def test_database_url_supports_postgresql_environment_variable(monkeypatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://relay_user:p%40ss%2Fword@db.example:5544/relay_test",
    )

    url = get_database_url()

    assert url.drivername == "postgresql+psycopg"
    assert url.database == "relay_test"
    assert url.username == "relay_user"
    assert url.password == "p@ss/word"
    assert url.host == "db.example"
    assert url.port == 5544


def test_models_persist_and_relationships_round_trip(test_session: Session) -> None:
    user = User(
        username="sample",
        email="sample@example.test",
        hashed_password="hashed-value",
    )
    conversation = Conversation(conversation_type=ConversationType.DIRECT)
    membership = ConversationMember(user=user, conversation=conversation)
    message = Message(
        sender=user,
        conversation=conversation,
        content="A persisted relationship fixture",
    )
    test_session.add_all([user, conversation, membership, message])
    test_session.commit()

    loaded_user = test_session.get(User, user.id)
    loaded_conversation = test_session.get(Conversation, conversation.id)
    loaded_message = test_session.get(Message, message.id)

    assert loaded_user is not None
    assert loaded_conversation is not None
    assert loaded_message is not None
    assert loaded_user.memberships[0].conversation.id == conversation.id
    assert loaded_conversation.members[0].user.id == user.id
    assert loaded_conversation.messages[0].content == message.content
    assert loaded_message.sender.id == user.id


def test_membership_and_user_constraints_are_enforced(test_session: Session) -> None:
    user = User(
        username="unique-user",
        email="unique@example.test",
        hashed_password="hashed-value",
    )
    conversation = Conversation(conversation_type=ConversationType.GROUP)
    test_session.add_all([user, conversation])
    test_session.flush()
    test_session.add_all(
        [
            ConversationMember(user=user, conversation=conversation),
            ConversationMember(user=user, conversation=conversation),
        ]
    )

    with pytest.raises(IntegrityError):
        test_session.commit()
    test_session.rollback()

    member_constraints = {
        constraint.name
        for constraint in ConversationMember.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    user_constraints = {
        constraint.name
        for constraint in User.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert "uq_conversation_members_pair" in member_constraints
    assert user_constraints == {"uq_users_username", "uq_users_email"}


def test_sqlite_foreign_keys_are_enabled(test_engine) -> None:
    with test_engine.connect() as connection:
        assert connection.scalar(text("PRAGMA foreign_keys")) == 1

    with Session(test_engine) as session:
        session.add(ConversationMember(conversation_id=404, user_id=404))
        with pytest.raises(IntegrityError):
            session.commit()


def test_database_connectivity_check_runs_select_one(monkeypatch, test_engine) -> None:
    monkeypatch.setattr(database_session, "get_engine", lambda: test_engine)

    assert database_session.database_is_available() is True


def test_database_health_route_reports_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(database_route, "database_is_available", lambda: False)

    response = client.get("/health/database")

    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
