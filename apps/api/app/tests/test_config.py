import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app


def test_cors_origins_are_trimmed_and_empty_values_are_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "development")
    monkeypatch.setenv(
        "CORS_ORIGINS",
        " http://localhost:3100, ,http://127.0.0.1:3100 ",
    )

    loaded = Settings()

    assert loaded.cors_origins == (
        "http://localhost:3100",
        "http://127.0.0.1:3100",
    )


def test_cors_origins_are_normalized_and_deduplicated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "development")
    monkeypatch.setenv(
        "CORS_ORIGINS",
        "HTTPS://Example.COM:443/,https://example.com,http://[::1]:80/",
    )

    loaded = Settings()

    assert loaded.cors_origins == ("https://example.com", "http://[::1]")


@pytest.mark.parametrize(
    "cors_origins",
    (
        "*",
        "https://example.com/app",
        "ftp://example.com",
        "https://user:secret@example.com",
    ),
)
def test_cors_rejects_unsafe_or_invalid_origins(
    monkeypatch: pytest.MonkeyPatch,
    cors_origins: str,
) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "development")
    monkeypatch.setenv("CORS_ORIGINS", cors_origins)

    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        Settings()


def test_production_requires_explicit_cors_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.setenv("WEB_ORIGIN", "https://fund.example.com")

    with pytest.raises(ValueError, match="CORS_ORIGINS must be explicitly set"):
        Settings()


def test_production_requires_explicit_web_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("CORS_ORIGINS", "https://fund.example.com")
    monkeypatch.delenv("WEB_ORIGIN", raising=False)

    with pytest.raises(ValueError, match="WEB_ORIGIN must be explicitly set"):
        Settings()


def test_production_requires_web_origin_in_cors_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("WEB_ORIGIN", "https://fund.example.com:8443")
    monkeypatch.setenv("CORS_ORIGINS", "https://fund.example.com")

    with pytest.raises(ValueError, match="must exactly match"):
        Settings()


def test_production_accepts_non_default_web_origin_when_allowlisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("WEB_ORIGIN", "https://fund.example.com:8443/")
    monkeypatch.setenv(
        "CORS_ORIGINS",
        "https://admin.example.com,https://fund.example.com:8443",
    )

    loaded = Settings()

    assert loaded.web_origin == "https://fund.example.com:8443"
    assert loaded.web_origin in loaded.cors_origins


def test_settings_rejects_unknown_application_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "prodution")

    with pytest.raises(ValueError, match="APP_ENVIRONMENT"):
        Settings()


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


def test_scheduler_settings_support_cron_jitter_and_lock_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FUND_SYNC_SCHEDULE_MODE", "cron")
    monkeypatch.setenv("FUND_SYNC_CRON", "30 3 * * 1-5")
    monkeypatch.setenv("FUND_SYNC_JITTER_SECONDS", "120")
    monkeypatch.setenv("FUND_SYNC_LOCK_TIMEOUT_MINUTES", "45")

    loaded = Settings()

    assert loaded.fund_sync_schedule_mode == "cron"
    assert loaded.fund_sync_cron == "30 3 * * 1-5"
    assert loaded.fund_sync_jitter_seconds == 120
    assert loaded.fund_sync_lock_timeout_minutes == 45


def test_public_fund_data_max_pages_is_configurable_and_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PUBLIC_FUND_DATA_MAX_PAGES", raising=False)

    assert Settings().public_fund_data_max_pages == 100

    monkeypatch.setenv("PUBLIC_FUND_DATA_MAX_PAGES", "7")

    loaded = Settings()

    assert loaded.public_fund_data_max_pages == 7

    monkeypatch.setenv("PUBLIC_FUND_DATA_MAX_PAGES", "0")

    assert Settings().public_fund_data_max_pages == 1


def test_public_fund_data_profile_defaults_and_accepts_registry_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PUBLIC_FUND_DATA_PROFILE", raising=False)

    assert Settings().public_fund_data_profile == "generic_aliases_v1"

    monkeypatch.setenv("PUBLIC_FUND_DATA_PROFILE", " normalized_v1 ")

    assert Settings().public_fund_data_profile == "normalized_v1"


def test_public_fund_data_proxy_pool_is_explicit_and_deduplicated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "PUBLIC_FUND_DATA_PROXY_URLS",
        "http://proxy-a.example:8080, https://proxy-b.example:8443, http://proxy-a.example:8080",
    )

    assert Settings().public_fund_data_proxy_urls == (
        "http://proxy-a.example:8080",
        "https://proxy-b.example:8443",
    )

    monkeypatch.setenv("PUBLIC_FUND_DATA_PROXY_URLS", "http://proxy-a.example:8080/path")
    with pytest.raises(ValueError, match="must not contain a path"):
        Settings()


def test_snapshot_quality_thresholds_are_configurable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FUND_SNAPSHOT_MIN_FUND_COUNT", "100")
    monkeypatch.setenv("FUND_SNAPSHOT_MIN_NAV_COVERAGE_RATIO", "0.95")
    monkeypatch.setenv("FUND_SNAPSHOT_MAX_LATEST_NAV_AGE_DAYS", "5")
    monkeypatch.setenv("FUND_SNAPSHOT_MAX_FUND_COUNT_DROP_RATIO", "0.2")
    monkeypatch.setenv(
        "FUND_SNAPSHOT_QUALITY_OVERRIDES",
        '{"eastmoney_snapshot":{"min_fund_count":80,"min_nav_coverage_ratio":1}}',
    )

    loaded = Settings()

    assert loaded.fund_snapshot_min_fund_count == 100
    assert loaded.fund_snapshot_min_nav_coverage_ratio == 0.95
    assert loaded.fund_snapshot_max_latest_nav_age_days == 5
    assert loaded.fund_snapshot_max_fund_count_drop_ratio == 0.2
    assert loaded.fund_snapshot_quality_overrides == {
        "eastmoney_snapshot": {
            "min_fund_count": 80,
            "min_nav_coverage_ratio": 1.0,
        }
    }


@pytest.mark.parametrize(
    ("variable_name", "value"),
    (
        ("FUND_SNAPSHOT_MIN_FUND_COUNT", "-1"),
        ("FUND_SNAPSHOT_MIN_NAV_COVERAGE_RATIO", "1.1"),
        ("FUND_SNAPSHOT_MAX_LATEST_NAV_AGE_DAYS", "-1"),
        ("FUND_SNAPSHOT_MAX_FUND_COUNT_DROP_RATIO", "nan"),
    ),
)
def test_snapshot_quality_thresholds_reject_invalid_values(
    monkeypatch: pytest.MonkeyPatch,
    variable_name: str,
    value: str,
) -> None:
    monkeypatch.setenv(variable_name, value)

    with pytest.raises(ValueError, match=variable_name):
        Settings()


def test_snapshot_quality_overrides_reject_invalid_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "FUND_SNAPSHOT_QUALITY_OVERRIDES",
        '{"eastmoney_snapshot":{"min_nav_coverage_ratio":2}}',
    )

    with pytest.raises(ValueError, match="FUND_SNAPSHOT_QUALITY_OVERRIDES"):
        Settings()


def test_scheduler_rejects_unknown_schedule_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FUND_SYNC_SCHEDULE_MODE", "calendar")

    with pytest.raises(ValueError, match="interval or cron"):
        Settings()


def test_discovery_limit_defaults_off_and_supports_full_universe_sentinel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "development")
    monkeypatch.delenv("FUND_EASTMONEY_DISCOVERY_LIMIT", raising=False)

    assert Settings().fund_eastmoney_discovery_limit == 0  # disabled by default

    monkeypatch.setenv("FUND_EASTMONEY_DISCOVERY_LIMIT", "-1")
    assert Settings().fund_eastmoney_discovery_limit == -1  # full D0 universe

    # The old hard maximum=500 clamp is removed: large positive values pass.
    monkeypatch.setenv("FUND_EASTMONEY_DISCOVERY_LIMIT", "5000")
    assert Settings().fund_eastmoney_discovery_limit == 5000

    monkeypatch.setenv("FUND_EASTMONEY_DISCOVERY_LIMIT", "-2")
    with pytest.raises(ValueError, match="-1"):
        Settings()

    monkeypatch.setenv("FUND_EASTMONEY_DISCOVERY_LIMIT", "abc")
    with pytest.raises(ValueError, match="-1"):
        Settings()


def test_llm_observability_defaults_and_thresholds_are_configurable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_OBSERVABILITY_WINDOW_MINUTES", "30")
    monkeypatch.setenv("LLM_OBSERVABILITY_MINIMUM_REQUESTS", "12")
    monkeypatch.setenv("LLM_ERROR_RATE_ALERT_THRESHOLD", "0.35")
    monkeypatch.setenv("LLM_TIMEOUT_RATE_ALERT_THRESHOLD", "0.15")
    monkeypatch.setenv("LLM_MAX_RESPONSE_BYTES", "2048")
    monkeypatch.setenv("LLM_MAX_OUTPUT_CHARS", "240")
    monkeypatch.setenv("LLM_OBSERVABILITY_QUEUE_CAPACITY", "64")
    monkeypatch.setenv("LLM_OBSERVABILITY_SHUTDOWN_TIMEOUT_SECONDS", "1.5")
    monkeypatch.setenv("LLM_OBSERVABILITY_RETENTION_DAYS", "14")
    monkeypatch.setenv("LLM_ALERT_WEBHOOK_URL", " https://hooks.example/llm-alert ")
    monkeypatch.setenv("LLM_ALERT_COOLDOWN_MINUTES", "15")
    monkeypatch.setenv("LLM_ALERT_TIMEOUT_SECONDS", "1.25")

    loaded = Settings()

    assert loaded.llm_observability_window_minutes == 30
    assert loaded.llm_observability_minimum_requests == 12
    assert loaded.llm_error_rate_alert_threshold == 0.35
    assert loaded.llm_timeout_rate_alert_threshold == 0.15
    assert loaded.llm_max_response_bytes == 2048
    assert loaded.llm_max_output_chars == 240
    assert loaded.llm_observability_queue_capacity == 64
    assert loaded.llm_observability_shutdown_timeout_seconds == 1.5
    assert loaded.llm_observability_retention_days == 14
    assert loaded.llm_alert_webhook_url == "https://hooks.example/llm-alert"
    assert loaded.llm_alert_cooldown_minutes == 15
    assert loaded.llm_alert_timeout_seconds == 1.25


def test_llm_connection_settings_are_trimmed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", " mock ")
    monkeypatch.setenv("LLM_MODEL", " mock-compliance-v1 ")
    monkeypatch.setenv("LLM_API_KEY", " provider-secret ")
    monkeypatch.setenv("LLM_BASE_URL", " https://provider.example/v1/ ")

    loaded = Settings()

    assert loaded.llm_provider == "mock"
    assert loaded.llm_model == "mock-compliance-v1"
    assert loaded.llm_api_key == "provider-secret"
    assert loaded.llm_base_url == "https://provider.example/v1/"


@pytest.mark.parametrize(
    ("variable_name", "value"),
    (
        ("LLM_OBSERVABILITY_WINDOW_MINUTES", "0"),
        ("LLM_OBSERVABILITY_MINIMUM_REQUESTS", "-1"),
        ("LLM_OBSERVABILITY_QUEUE_CAPACITY", "10001"),
        ("LLM_OBSERVABILITY_SHUTDOWN_TIMEOUT_SECONDS", "0"),
        ("LLM_OBSERVABILITY_RETENTION_DAYS", "0"),
        ("LLM_MAX_RESPONSE_BYTES", "0"),
        ("LLM_MAX_OUTPUT_CHARS", "100001"),
        ("LLM_ERROR_RATE_ALERT_THRESHOLD", "1.1"),
        ("LLM_TIMEOUT_RATE_ALERT_THRESHOLD", "nan"),
        ("LLM_ALERT_WEBHOOK_URL", "ftp://hooks.example/llm"),
        ("LLM_ALERT_WEBHOOK_URL", "https://user:secret@hooks.example/llm"),
        ("LLM_ALERT_WEBHOOK_URL", "https://hooks.example/llm?token=secret"),
        ("LLM_ALERT_COOLDOWN_MINUTES", "0"),
        ("LLM_ALERT_TIMEOUT_SECONDS", "0"),
    ),
)
def test_llm_observability_rejects_invalid_alert_configuration(
    monkeypatch: pytest.MonkeyPatch,
    variable_name: str,
    value: str,
) -> None:
    monkeypatch.setenv(variable_name, value)

    with pytest.raises(ValueError, match=variable_name):
        Settings()
