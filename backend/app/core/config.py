import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import URL, make_url

load_dotenv()

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_PATH = BACKEND_ROOT / "data" / "relay.db"


def get_database_url() -> URL:
    """Return DATABASE_URL, defaulting to backend/data/relay.db."""
    configured_url = os.getenv("DATABASE_URL")
    if configured_url:
        url = make_url(configured_url)
        if (
            url.get_backend_name() == "sqlite"
            and url.database not in (None, "", ":memory:")
            and not Path(url.database).is_absolute()
        ):
            database_path = (BACKEND_ROOT / url.database).resolve()
            return url.set(database=str(database_path))
        return url

    return URL.create("sqlite", database=str(DEFAULT_DATABASE_PATH))


def get_jwt_secret_key() -> str:
    """Return a configured signing key; never fall back to a built-in secret."""
    secret = os.getenv("JWT_SECRET_KEY", "").strip()
    if (
        len(secret.encode("utf-8")) < 32
        or secret.lower().startswith(("replace-with-", "change-me"))
    ):
        raise RuntimeError(
            "JWT_SECRET_KEY must be set to a random value of at least 32 bytes."
        )
    return secret


def get_access_token_expire_minutes() -> int:
    """Return the configured access-token lifetime in minutes."""
    raw_value = os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30")
    try:
        expiration = int(raw_value)
    except ValueError as exc:
        raise RuntimeError("JWT_ACCESS_TOKEN_EXPIRE_MINUTES must be an integer.") from exc
    if expiration < 1:
        raise RuntimeError("JWT_ACCESS_TOKEN_EXPIRE_MINUTES must be positive.")
    return expiration
