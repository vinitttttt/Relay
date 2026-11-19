import logging

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.logging import log_exception
from app.models import User
from app.security.tokens import InvalidAccessToken, decode_access_token

logger = logging.getLogger("relay.auth")

_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    session: Session = Depends(get_db),
) -> User:
    """Require a valid bearer token and load its user from the database."""
    unauthorized = HTTPException(
        status_code=401,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        logger.warning(
            "Authentication required",
            extra={"event": "authentication.missing", "status_code": 401},
        )
        raise unauthorized

    try:
        user_id = decode_access_token(credentials.credentials)
    except (InvalidAccessToken, jwt.InvalidTokenError) as exc:
        logger.warning(
            "Authentication failed",
            extra={"event": "authentication.invalid_token", "status_code": 401},
        )
        raise unauthorized from exc

    try:
        user = session.scalar(select(User).where(User.id == user_id))
    except Exception as exc:
        log_exception(
            logger, "authentication.user_lookup_error", exc,
            user_id=user_id, status_code=500,
        )
        raise
    if user is None:
        logger.warning(
            "Authenticated user no longer exists",
            extra={"event": "authentication.missing_user", "user_id": user_id, "status_code": 401},
        )
        raise unauthorized
    return user
