from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app


def test_cors_origins_are_trimmed_and_empty_values_are_ignored(monkeypatch) -> None:
    monkeypatch.setenv(
        "CORS_ORIGINS",
        " http://localhost:3100, ,http://127.0.0.1:3100 ",
    )

    loaded = Settings()

    assert loaded.cors_origins == (
        "http://localhost:3100",
        "http://127.0.0.1:3100",
    )


def test_cors_preflight_allows_the_default_backup_web_port() -> None:
    response = TestClient(app).options(
        "/api/data/status",
        headers={
            "Origin": "http://localhost:3001",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3001"
