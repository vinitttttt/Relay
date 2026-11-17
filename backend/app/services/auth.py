from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import User
from app.security.passwords import hash_password, verify_password


class DuplicateUserError(Exception):
    """Raised when a username or email is already registered."""


class InvalidCredentialsError(Exception):
    """Raised for either an unknown login identifier or a bad password."""


def register_user(session: Session, username: str, email: str, password: str) -> User:
    """Create a user while handling both ordinary and concurrent duplicates."""
    existing_user = session.scalar(
        select(User.id).where(or_(User.username == username, User.email == email))
    )
    if existing_user is not None:
        raise DuplicateUserError

    user = User(
        username=username,
        email=email,
        hashed_password=hash_password(password),
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise DuplicateUserError from exc
    session.refresh(user)
    return user


def authenticate_user(session: Session, identifier: str, password: str) -> User:
    """Authenticate by username or email without disclosing account existence."""
    normalized_email = identifier.casefold()
    user = session.scalar(
        select(User).where(
            or_(User.username == identifier, User.email == normalized_email)
        )
    )

    if user is None:
        # Do comparable Argon2 work for unknown accounts and wrong passwords.
        hash_password(password)
        raise InvalidCredentialsError
    if not verify_password(password, user.hashed_password):
        raise InvalidCredentialsError
    return user
