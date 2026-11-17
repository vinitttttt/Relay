from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import get_access_token_expire_minutes, get_jwt_secret_key

JWT_ALGORITHM = "HS256"


class InvalidAccessToken(Exception):
    """Raised when an access token is invalid, expired, or malformed."""


def create_access_token(user_id: int) -> str:
    """Create a signed bearer token for a user ID."""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=get_access_token_expire_minutes())
    claims = {
        "sub": str(user_id),
        "iat": now,
        "exp": expires_at,
        "type": "access",
    }
    return jwt.encode(claims, get_jwt_secret_key(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> int:
    """Verify an access token and return its user ID subject."""
    claims = jwt.decode(
        token,
        get_jwt_secret_key(),
        algorithms=[JWT_ALGORITHM],
        options={"require": ["sub", "iat", "exp", "type"]},
    )
    subject = claims.get("sub")
    if (
        claims.get("type") != "access"
        or not isinstance(subject, str)
        or not subject.isascii()
        or not subject.isdigit()
        or int(subject) < 1
    ):
        raise InvalidAccessToken
    return int(subject)
