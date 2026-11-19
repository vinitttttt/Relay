from collections.abc import Generator
import secrets

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine, URL
from sqlalchemy.orm import Session, sessionmaker

from app.db.session import get_db
from app.db.base import Base
from app.db.session import create_database_engine
from app.main import app
from app.core.rate_limit import rate_limiter
from app.models import Conversation, ConversationMember, Message, User  # noqa: F401


@pytest.fixture
def test_engine(tmp_path) -> Generator[Engine, None, None]:
    database_url = URL.create(
        "sqlite", database=str(tmp_path / "relay_test.sqlite3")
    )
    engine = create_database_engine(database_url)
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def test_session(test_engine: Engine) -> Generator[Session, None, None]:
    factory = sessionmaker(bind=test_engine, expire_on_commit=False)
    with factory() as session:
        yield session


@pytest.fixture
def auth_client(test_engine: Engine, monkeypatch) -> Generator[TestClient, None, None]:
    rate_limiter.reset()
    monkeypatch.setenv("JWT_SECRET_KEY", secrets.token_urlsafe(48))
    monkeypatch.setenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "15")

    def override_get_db() -> Generator[Session, None, None]:
        with Session(test_engine, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)
        rate_limiter.reset()
