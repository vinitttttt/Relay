from datetime import datetime, timedelta, timezone
import secrets
from unittest.mock import MagicMock

import jwt
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_jwt_secret_key
from app.models import User
from app.security.passwords import hash_password, verify_password
from app.security.tokens import JWT_ALGORITHM, create_access_token, decode_access_token
from app.services.auth import DuplicateUserError, register_user


def registration_payload(**overrides: str) -> dict[str, str]:
    payload = {
        "username": "relay-user",
        "email": "Relay.User@example.com",
        "password": "correct horse battery staple",
    }
    payload.update(overrides)
    return payload


def test_registration_hashes_password_and_returns_public_user(auth_client, test_engine) -> None:
    response = auth_client.post(
        "/api/v1/auth/register", json=registration_payload()
    )

    assert response.status_code == 201
    body = response.json()
    assert body["username"] == "relay-user"
    assert body["email"] == "relay.user@example.com"
    assert "hashed_password" not in body
    assert "password" not in body

    with Session(test_engine) as session:
        user = session.query(User).filter_by(username="relay-user").one()
        assert user.hashed_password != "correct horse battery staple"
        assert verify_password("correct horse battery staple", user.hashed_password)


def test_registration_rejects_duplicate_email_and_username(auth_client) -> None:
    first = auth_client.post(
        "/api/v1/auth/register", json=registration_payload()
    )
    duplicate_email = auth_client.post(
        "/api/v1/auth/register",
        json=registration_payload(username="another-user", email="RELAY.USER@example.com"),
    )
    duplicate_username = auth_client.post(
        "/api/v1/auth/register",
        json=registration_payload(email="another@example.com"),
    )

    assert first.status_code == 201
    for response in (duplicate_email, duplicate_username):
        assert response.status_code == 409
        assert response.json() == {
            "detail": "Username or email is already registered."
        }


def test_registration_validation_rejects_invalid_input(auth_client) -> None:
    response = auth_client.post(
        "/api/v1/auth/register",
        json=registration_payload(email="not-an-email", password="short"),
    )

    assert response.status_code == 422


def test_registration_rate_limit_returns_429(auth_client, monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_REGISTER", "1")
    first = auth_client.post("/api/v1/auth/register", json=registration_payload())
    second = auth_client.post(
        "/api/v1/auth/register",
        json=registration_payload(username="second", email="second@example.com", password="another valid password"),
    )
    assert first.status_code == 201
    assert second.status_code == 429
    assert second.headers["retry-after"] == "3600"


def test_password_hashing_uses_argon2_and_verifies_password() -> None:
    password_hash = hash_password("a long test password")

    assert password_hash.startswith("$argon2id$")
    assert password_hash != "a long test password"
    assert verify_password("a long test password", password_hash)
    assert not verify_password("incorrect password", password_hash)


@pytest.mark.parametrize("identifier", ["Relay.User@example.com", "relay-user"])
def test_login_succeeds_with_email_or_username(auth_client, identifier: str) -> None:
    registered = auth_client.post(
        "/api/v1/auth/register", json=registration_payload()
    )
    response = auth_client.post(
        "/api/v1/auth/login",
        json={"identifier": identifier, "password": "correct horse battery staple"},
    )

    assert registered.status_code == 201
    assert response.status_code == 200
    token_response = response.json()
    assert token_response["token_type"] == "bearer"
    assert token_response["expires_in"] == 15 * 60
    assert decode_access_token(token_response["access_token"]) == registered.json()["id"]


def test_login_does_not_disclose_unknown_account(auth_client) -> None:
    auth_client.post("/api/v1/auth/register", json=registration_payload())
    wrong_password = auth_client.post(
        "/api/v1/auth/login",
        json={"identifier": "relay-user", "password": "wrong password"},
    )
    unknown_user = auth_client.post(
        "/api/v1/auth/login",
        json={"identifier": "missing-user", "password": "wrong password"},
    )

    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json()


def test_login_rate_limit_returns_429(auth_client, monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_LOGIN", "1")
    first = auth_client.post(
        "/api/v1/auth/login", json={"identifier": "missing", "password": "bad password"}
    )
    second = auth_client.post(
        "/api/v1/auth/login", json={"identifier": "missing", "password": "bad password"}
    )
    assert first.status_code == 401
    assert second.status_code == 429


def test_profile_requires_authentication_and_returns_public_fields(auth_client) -> None:
    registered = auth_client.post(
        "/api/v1/auth/register", json=registration_payload()
    )
    unauthenticated = auth_client.get("/api/v1/auth/me")
    token_response = auth_client.post(
        "/api/v1/auth/login",
        json={"identifier": "relay-user", "password": "correct horse battery staple"},
    )
    profile = auth_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token_response.json()['access_token']}"},
    )

    assert unauthenticated.status_code == 401
    assert registered.status_code == 201
    assert token_response.status_code == 200
    assert profile.status_code == 200
    assert profile.json() == {
        "id": registered.json()["id"],
        "username": "relay-user",
        "email": "relay.user@example.com",
        "created_at": registered.json()["created_at"],
    }
    assert "hashed_password" not in profile.json()


def test_invalid_and_expired_tokens_are_rejected(auth_client) -> None:
    malformed = auth_client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"}
    )
    now = datetime.now(timezone.utc)
    token_claims = {
        "sub": "1",
        "iat": now,
        "exp": now + timedelta(minutes=1),
        "type": "access",
    }
    invalid_signature_token = jwt.encode(
        token_claims,
        secrets.token_urlsafe(48),
        algorithm=JWT_ALGORITHM,
    )
    invalid_signature = auth_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {invalid_signature_token}"},
    )
    expired_token = jwt.encode(
        {
            "sub": "1",
            "iat": now - timedelta(minutes=2),
            "exp": now - timedelta(minutes=1),
            "type": "access",
        },
        get_jwt_secret_key(),
        algorithm=JWT_ALGORITHM,
    )
    expired = auth_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {expired_token}"}
    )

    assert malformed.status_code == invalid_signature.status_code == expired.status_code == 401
    assert malformed.json() == invalid_signature.json() == expired.json()


def test_valid_token_for_missing_user_is_rejected(auth_client) -> None:
    token = create_access_token(999)

    response = auth_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 401


def test_concurrent_unique_conflict_is_translated_to_duplicate_error() -> None:
    session = MagicMock()
    session.scalar.return_value = None
    session.commit.side_effect = IntegrityError(
        "INSERT INTO users", {}, Exception("unique constraint")
    )

    with pytest.raises(DuplicateUserError):
        register_user(
            session,
            username="racing-user",
            email="racing@example.test",
            password="correct horse battery staple",
        )

    session.rollback.assert_called_once()
