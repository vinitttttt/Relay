from collections.abc import Generator
from functools import lru_cache
import logging
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_database_url
from app.core.logging import log_exception

logger = logging.getLogger("relay.database")


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Create and cache the process-wide SQLAlchemy engine."""
    return create_database_engine(get_database_url())


def create_database_engine(database_url: URL | str) -> Engine:
    """Build an engine and enable SQLite foreign keys on every connection."""
    url = make_url(database_url) if isinstance(database_url, str) else database_url
    connect_args: dict[str, object] = {}

    if url.get_backend_name() == "sqlite":
        database = url.database
        if database not in (None, "", ":memory:") and not url.query.get("uri"):
            Path(database).parent.mkdir(parents=True, exist_ok=True)
        connect_args["check_same_thread"] = False

    engine = create_engine(url, pool_pre_ping=True, connect_args=connect_args)

    if url.get_backend_name() == "sqlite":
        @event.listens_for(engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    """Return the shared factory used to create request-scoped sessions."""
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """Yield a session and ensure it is closed after the request."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def database_is_available() -> bool:
    """Check connectivity with a lightweight query, without leaking errors."""
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except (SQLAlchemyError, RuntimeError, ValueError) as exc:
        log_exception(logger, "database.connectivity_check_failed", exc)
        return False
    return True
