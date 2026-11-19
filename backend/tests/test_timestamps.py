from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.time import as_utc, utc_now
from app.models import Conversation, ConversationMember, ConversationType, Message, User
from app.security.tokens import create_access_token


def test_new_api_timestamps_are_utc_and_use_z_suffix(auth_client, test_engine) -> None:
    alice = auth_client.post(
        "/api/v1/auth/register",
        json={"username": "utc-alice", "email": "utc-alice@example.com", "password": "valid password"},
    )
    bob = auth_client.post(
        "/api/v1/auth/register",
        json={"username": "utc-bob", "email": "utc-bob@example.com", "password": "valid password"},
    )
    assert alice.status_code == bob.status_code == 201
    for response in (alice, bob):
        stamp = response.json()["created_at"]
        assert stamp.endswith("Z")
        assert datetime.fromisoformat(stamp.replace("Z", "+00:00")).utcoffset().total_seconds() == 0

    conversation = auth_client.post(
        "/api/v1/conversations/direct",
        json={"target_user_id": bob.json()["id"]},
        headers={"Authorization": f"Bearer {create_access_token(alice.json()['id'])}"},
    )
    assert conversation.status_code == 201
    assert conversation.json()["created_at"].endswith("Z")

    message = auth_client.post(
        f"/api/v1/conversations/{conversation.json()['id']}/messages",
        json={"content": "timestamp check", "client_message_id": "utc-message"},
        headers={"Authorization": f"Bearer {create_access_token(alice.json()['id'])}"},
    )
    assert message.status_code == 201
    assert message.json()["created_at"].endswith("Z")

    with Session(test_engine) as session:
        saved = session.get(Message, message.json()["id"])
        assert saved is not None
        assert saved.created_at.tzinfo is None  # SQLite strips offsets; API restores UTC.
        assert as_utc(saved.created_at).utcoffset().total_seconds() == 0


def test_legacy_naive_sqlite_timestamp_serializes_as_utc(auth_client, test_engine) -> None:
    with Session(test_engine) as session:
        first = User(username="legacy-a", email="legacy-a@example.test", hashed_password="hash")
        second = User(username="legacy-b", email="legacy-b@example.test", hashed_password="hash")
        session.add_all([first, second])
        session.flush()
        conversation = Conversation(
            conversation_type=ConversationType.DIRECT,
            direct_user_low_id=first.id,
            direct_user_high_id=second.id,
        )
        session.add(conversation)
        session.flush()
        session.add_all([
            ConversationMember(conversation_id=conversation.id, user_id=first.id),
            ConversationMember(conversation_id=conversation.id, user_id=second.id),
        ])
        legacy_stamp = datetime(2020, 1, 2, 3, 4, 5)
        legacy_message = Message(
            conversation_id=conversation.id,
            sender_id=first.id,
            content="legacy record",
            created_at=legacy_stamp,
        )
        session.add(legacy_message)
        session.commit()
        conversation_id = conversation.id
        user_id = first.id

    response = auth_client.get(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers={"Authorization": f"Bearer {create_access_token(user_id)}"},
    )
    assert response.status_code == 200
    assert response.json()["items"][0]["created_at"] == "2020-01-02T03:04:05Z"


def test_utc_now_returns_aware_utc_datetime() -> None:
    now = utc_now()
    assert now.tzinfo is not None
    assert now.utcoffset().total_seconds() == 0
    assert as_utc(now).tzinfo == timezone.utc
