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


def get_rate_limit(name: str, default: int) -> int:
    """Read and validate one request-count limit from the environment."""
    variable = f"RATE_LIMIT_{name.upper()}"
    try:
        value = int(os.getenv(variable, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{variable} must be a positive integer.") from exc
    if value < 1:
        raise RuntimeError(f"{variable} must be a positive integer.")
    return value


def get_rate_limit_window_seconds(name: str, default: int) -> int:
    variable = f"RATE_LIMIT_{name.upper()}_WINDOW_SECONDS"
    try:
        value = int(os.getenv(variable, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{variable} must be a positive integer.") from exc
    if value < 1:
        raise RuntimeError(f"{variable} must be a positive integer.")
    return value


def get_allowed_origins() -> list[str]:
    """Return a strict, comma-separated CORS and browser WebSocket allowlist."""
    configured = os.getenv("CORS_ALLOWED_ORIGINS")
    raw_origins = configured.split(",") if configured is not None else [
        "http://localhost:5173", "http://127.0.0.1:5173"
    ]
    origins = list(dict.fromkeys(origin.strip().rstrip("/") for origin in raw_origins if origin.strip()))
    if not origins or "*" in origins:
        raise RuntimeError("CORS_ALLOWED_ORIGINS must contain explicit origins, not '*'.")
    return origins
