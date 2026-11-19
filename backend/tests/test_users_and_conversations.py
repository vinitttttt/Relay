from unittest.mock import MagicMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Conversation, ConversationMember, ConversationType, User
from app.models import Message
from app.security.tokens import create_access_token
from app.services.conversations import start_or_get_direct_conversation


def seed_users(test_engine, *usernames: str) -> dict[str, int]:
    with Session(test_engine) as session:
        users = [
            User(
                username=username,
                email=f"{username}@example.test",
                hashed_password="test-only-hash",
            )
            for username in usernames
        ]
        session.add_all(users)
        session.commit()
        return {user.username: user.id for user in users}


def auth_headers(user_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def test_user_search_returns_partial_case_insensitive_public_results(
    auth_client, test_engine
) -> None:
    ids = seed_users(test_engine, "alice", "alicia", "MALIK", "robin")

    response = auth_client.get(
        "/api/v1/users/search",
        params={"q": "LI"},
        headers=auth_headers(ids["alice"]),
    )

    assert response.status_code == 200
    results = response.json()
    assert {result["username"] for result in results} == {"alicia", "MALIK"}
    assert all(set(result) == {"id", "username"} for result in results)
    assert all("email" not in result and "hashed_password" not in result for result in results)


def test_user_search_excludes_current_user(auth_client, test_engine) -> None:
    ids = seed_users(test_engine, "alex", "alexander")

    response = auth_client.get(
        "/api/v1/users/search",
        params={"q": "alex"},
        headers=auth_headers(ids["alex"]),
    )

    assert response.status_code == 200
    assert [result["username"] for result in response.json()] == ["alexander"]


def test_user_search_requires_authentication(auth_client) -> None:
    response = auth_client.get("/api/v1/users/search", params={"q": "relay"})

    assert response.status_code == 401


def test_user_search_rate_limit_is_per_authenticated_user(
    auth_client, test_engine, monkeypatch
) -> None:
    ids = seed_users(test_engine, "limited", "other")
    monkeypatch.setenv("RATE_LIMIT_USER_SEARCH", "1")
    url = "/api/v1/users/search?q=li"
    first = auth_client.get(url, headers=auth_headers(ids["limited"]))
    limited = auth_client.get(url, headers=auth_headers(ids["limited"]))
    other_user = auth_client.get(url, headers=auth_headers(ids["other"]))
    assert first.status_code == other_user.status_code == 200
    assert limited.status_code == 429


@pytest.mark.parametrize("query", ["", "a", "  "])
def test_user_search_rejects_empty_or_short_query(
    auth_client, test_engine, query: str
) -> None:
    ids = seed_users(test_engine, "searcher")
    response = auth_client.get(
        "/api/v1/users/search",
        params={"q": query},
        headers=auth_headers(ids["searcher"]),
    )

    assert response.status_code == 422


def test_user_search_rejects_excessively_long_query(auth_client, test_engine) -> None:
    ids = seed_users(test_engine, "searcher")

    response = auth_client.get(
        "/api/v1/users/search",
        params={"q": "x" * 51},
        headers=auth_headers(ids["searcher"]),
    )

    assert response.status_code == 422


def test_user_search_limits_results_to_twenty(auth_client, test_engine) -> None:
    usernames = tuple(f"member{index:02}" for index in range(25))
    ids = seed_users(test_engine, "searcher", *usernames)

    response = auth_client.get(
        "/api/v1/users/search",
        params={"q": "member"},
        headers=auth_headers(ids["searcher"]),
    )

    assert response.status_code == 200
    assert len(response.json()) == 20


def test_direct_conversation_creates_two_members(auth_client, test_engine) -> None:
    ids = seed_users(test_engine, "first", "second")

    response = auth_client.post(
        "/api/v1/conversations/direct",
        json={"target_user_id": ids["second"]},
        headers=auth_headers(ids["first"]),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["conversation_type"] == "direct"
    assert {member["id"] for member in body["members"]} == {
        ids["first"],
        ids["second"],
    }
    assert all(set(member) == {"id", "username"} for member in body["members"])

    with Session(test_engine) as session:
        assert session.scalar(
            select(func.count(ConversationMember.id)).where(
                ConversationMember.conversation_id == body["id"]
            )
        ) == 2


def test_direct_conversation_reuses_existing_pair(auth_client, test_engine) -> None:
    ids = seed_users(test_engine, "first", "second")
    headers = auth_headers(ids["first"])
    first = auth_client.post(
        "/api/v1/conversations/direct",
        json={"target_user_id": ids["second"]},
        headers=headers,
    )
    second = auth_client.post(
        "/api/v1/conversations/direct",
        json={"target_user_id": ids["second"]},
        headers=headers,
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    with Session(test_engine) as session:
        assert session.scalar(
            select(func.count(Conversation.id)).where(
                Conversation.conversation_type == ConversationType.DIRECT
            )
        ) == 1


def test_database_rejects_duplicate_direct_user_pair(test_engine) -> None:
    ids = seed_users(test_engine, "first", "second")
    low_id, high_id = sorted(ids.values())

    with Session(test_engine) as session:
        session.add(
            Conversation(
                conversation_type=ConversationType.DIRECT,
                direct_user_low_id=low_id,
                direct_user_high_id=high_id,
            )
        )
        session.commit()

    with Session(test_engine) as session:
        session.add(
            Conversation(
                conversation_type=ConversationType.DIRECT,
                direct_user_low_id=low_id,
                direct_user_high_id=high_id,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_direct_conversation_rejects_self(auth_client, test_engine) -> None:
    ids = seed_users(test_engine, "first")

    response = auth_client.post(
        "/api/v1/conversations/direct",
        json={"target_user_id": ids["first"]},
        headers=auth_headers(ids["first"]),
    )

    assert response.status_code == 400


def test_direct_conversation_returns_not_found_for_unknown_user(
    auth_client, test_engine
) -> None:
    ids = seed_users(test_engine, "first")

    response = auth_client.post(
        "/api/v1/conversations/direct",
        json={"target_user_id": 999999},
        headers=auth_headers(ids["first"]),
    )

    assert response.status_code == 404


def test_non_member_cannot_retrieve_another_pair_conversation(
    auth_client, test_engine
) -> None:
    ids = seed_users(test_engine, "alice", "bob", "charlie")
    alice_bob = auth_client.post(
        "/api/v1/conversations/direct",
        json={"target_user_id": ids["bob"]},
        headers=auth_headers(ids["alice"]),
    )

    charlie_bob = auth_client.post(
        "/api/v1/conversations/direct",
        json={"target_user_id": ids["bob"]},
        headers=auth_headers(ids["charlie"]),
    )

    assert alice_bob.status_code == charlie_bob.status_code == 201
    assert charlie_bob.json()["id"] != alice_bob.json()["id"]
    assert {member["id"] for member in charlie_bob.json()["members"]} == {
        ids["charlie"],
        ids["bob"],
    }


def test_group_conversation_is_not_returned_as_direct(auth_client, test_engine) -> None:
    ids = seed_users(test_engine, "first", "second")
    with Session(test_engine) as session:
        group = Conversation(conversation_type=ConversationType.GROUP, name="A group")
        session.add(group)
        session.add_all(
            [
                ConversationMember(conversation=group, user_id=ids["first"]),
                ConversationMember(conversation=group, user_id=ids["second"]),
            ]
        )
        session.commit()
        group_id = group.id

    response = auth_client.post(
        "/api/v1/conversations/direct",
        json={"target_user_id": ids["second"]},
        headers=auth_headers(ids["first"]),
    )

    assert response.status_code == 201
    assert response.json()["conversation_type"] == "direct"
    assert response.json()["id"] != group_id


def test_conversation_list_shows_member_direct_conversations_and_activity_order(
    auth_client, test_engine
) -> None:
    ids = seed_users(test_engine, "alice", "bob", "carol", "outsider", "dave")
    headers = auth_headers(ids["alice"])
    first = auth_client.post("/api/v1/conversations/direct", json={"target_user_id": ids["bob"]}, headers=headers).json()
    second = auth_client.post("/api/v1/conversations/direct", json={"target_user_id": ids["carol"]}, headers=headers).json()
    outsider = auth_client.post("/api/v1/conversations/direct", json={"target_user_id": ids["dave"]}, headers=auth_headers(ids["outsider"])).json()
    with Session(test_engine) as session:
        session.add_all([
            Message(conversation_id=first["id"], sender_id=ids["bob"], content="older activity"),
            Message(conversation_id=second["id"], sender_id=ids["alice"], content="newer activity"),
        ])
        session.commit()

    response = auth_client.get("/api/v1/conversations", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body] == [second["id"], first["id"]]
    assert all(item["id"] != outsider["id"] for item in body)
    assert body[0]["latest_message"]["content"] == "newer activity"
    assert body[0]["latest_message"]["sender"] == {"id": ids["alice"], "username": "alice"}
    assert {member["username"] for member in body[0]["members"]} == {"alice", "carol"}
    assert "email" not in str(body) and "hashed_password" not in str(body)


def test_message_create_validation_membership_and_response(auth_client, test_engine) -> None:
    ids = seed_users(test_engine, "alice", "bob", "outsider")
    conversation = auth_client.post("/api/v1/conversations/direct", json={"target_user_id": ids["bob"]}, headers=auth_headers(ids["alice"])).json()
    url = f"/api/v1/conversations/{conversation['id']}/messages"
    sent = auth_client.post(url, json={"content": "  Hello Relay!  "}, headers=auth_headers(ids["alice"]))
    assert sent.status_code == 201
    assert sent.json()["content"] == "  Hello Relay!  "
    assert sent.json()["conversation_id"] == conversation["id"]
    assert sent.json()["sender"] == {"id": ids["alice"], "username": "alice"}
    assert "email" not in str(sent.json()) and "hashed_password" not in str(sent.json())
    assert auth_client.post(url, json={"content": "   "}, headers=auth_headers(ids["alice"])).status_code == 422
    assert auth_client.post(url, json={"content": "x" * 5001}, headers=auth_headers(ids["alice"])).status_code == 422
    assert auth_client.post(url, json={"content": "Intrusion"}, headers=auth_headers(ids["outsider"])).status_code == 404


def test_message_history_is_chronological_and_paginated(auth_client, test_engine) -> None:
    ids = seed_users(test_engine, "alice", "bob", "outsider")
    conversation = auth_client.post("/api/v1/conversations/direct", json={"target_user_id": ids["bob"]}, headers=auth_headers(ids["alice"])).json()
    conversation_id = conversation["id"]
    with Session(test_engine) as session:
        session.add_all([
            Message(conversation_id=conversation_id, sender_id=ids["alice"], content=f"message {index}")
            for index in range(5)
        ])
        session.commit()
    url = f"/api/v1/conversations/{conversation_id}/messages"
    headers = auth_headers(ids["alice"])
    newest = auth_client.get(url, params={"limit": 2}, headers=headers)
    assert newest.status_code == 200
    newest_body = newest.json()
    assert [item["content"] for item in newest_body["items"]] == ["message 3", "message 4"]
    assert newest_body["next_cursor"] == newest_body["items"][0]["id"]
    older = auth_client.get(url, params={"limit": 2, "before_id": newest_body["next_cursor"]}, headers=headers)
    assert [item["content"] for item in older.json()["items"]] == ["message 1", "message 2"]
    assert older.json()["next_cursor"] == older.json()["items"][0]["id"]
    last = auth_client.get(url, params={"limit": 2, "before_id": older.json()["next_cursor"]}, headers=headers)
    assert [item["content"] for item in last.json()["items"]] == ["message 0"]
    assert last.json()["next_cursor"] is None
    assert auth_client.get(url, headers=auth_headers(ids["outsider"])).status_code == 404


def test_conversation_list_handles_no_messages_and_requires_auth(auth_client, test_engine) -> None:
    ids = seed_users(test_engine, "alice", "bob")
    auth_client.post("/api/v1/conversations/direct", json={"target_user_id": ids["bob"]}, headers=auth_headers(ids["alice"]))
    response = auth_client.get("/api/v1/conversations", headers=auth_headers(ids["alice"]))
    assert response.status_code == 200
    assert response.json()[0]["latest_message"] is None
    assert auth_client.get("/api/v1/conversations").status_code == 401


def test_concurrent_direct_pair_conflict_returns_winning_conversation() -> None:
    current_user = User(id=1)
    existing_conversation = Conversation(
        id=12,
        conversation_type=ConversationType.DIRECT,
        direct_user_low_id=1,
        direct_user_high_id=2,
    )
    session = MagicMock()
    session.get.return_value = User(id=2)
    session.scalar.side_effect = [None, existing_conversation]
    session.commit.side_effect = IntegrityError(
        "INSERT INTO conversations", {}, Exception("unique pair")
    )

    conversation, created = start_or_get_direct_conversation(
        session, current_user, 2
    )

    assert conversation is existing_conversation
    assert created is False
    session.rollback.assert_called_once()


def test_user_search_requires_authentication(auth_client) -> None:
    response = auth_client.get("/api/v1/users/search", params={"q": "relay"})

    assert response.status_code == 401


def test_user_search_rejects_excessively_long_query(auth_client, test_engine) -> None:
    ids = seed_users(test_engine, "searcher")

    response = auth_client.get(
        "/api/v1/users/search",
        params={"q": "x" * 51},
        headers=auth_headers(ids["searcher"]),
    )

    assert response.status_code == 422
