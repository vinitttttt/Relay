import pytest
from fastapi.testclient import TestClient

from app.core.config import get_allowed_origins, get_rate_limit, get_rate_limit_window_seconds
from app.main import create_app


def test_rate_limit_configuration_reads_environment(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_LOGIN", "7")
    monkeypatch.setenv("RATE_LIMIT_LOGIN_WINDOW_SECONDS", "90")
    assert get_rate_limit("LOGIN", 10) == 7
    assert get_rate_limit_window_seconds("LOGIN", 60) == 90


def test_cors_origins_parse_environment_list(monkeypatch) -> None:
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://relay.example, https://admin.example/")
    assert get_allowed_origins() == ["https://relay.example", "https://admin.example"]


def test_cors_allows_configured_origin(monkeypatch) -> None:
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://relay.example,https://admin.example")
    client = TestClient(create_app())
    response = client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "https://admin.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://admin.example"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_cors_rejects_unconfigured_origin(monkeypatch) -> None:
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://relay.example")
    client = TestClient(create_app())
    response = client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_cors_rejects_wildcard_with_credentials(monkeypatch) -> None:
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "*")
    with pytest.raises(RuntimeError, match="explicit origins"):
        create_app()
