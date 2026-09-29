import math
import os
import json
from pathlib import Path
from urllib.parse import urlsplit


DEFAULT_CORS_ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
)
DEPLOYED_ENVIRONMENTS = {"staging", "production"}
DEFAULT_SQLITE_DATABASE = (
    Path(__file__).resolve().parents[4] / "output" / "dev" / "fund.db"
).as_posix()


def _positive_finite_float(variable_name: str, default: str) -> float:
    raw_value = os.getenv(variable_name, default).strip()
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{variable_name} must be a finite number greater than 0") from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{variable_name} must be a finite number greater than 0")
    return value


def _rate_threshold(variable_name: str, default: str) -> float:
    raw_value = os.getenv(variable_name, default).strip()
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{variable_name} must be a finite number between 0 and 1") from exc
    if not math.isfinite(value) or value < 0 or value > 1:
        raise ValueError(f"{variable_name} must be a finite number between 0 and 1")
    return value


def _non_negative_rate_threshold(variable_name: str, default: str) -> float:
    raw_value = os.getenv(variable_name, default).strip()
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{variable_name} must be a finite number between 0 and 1") from exc
    if not math.isfinite(value) or value < 0 or value > 1:
        raise ValueError(f"{variable_name} must be a finite number between 0 and 1")
    return value


def _positive_integer(
    variable_name: str,
    default: str,
    *,
    maximum: int | None = None,
) -> int:
    raw_value = os.getenv(variable_name, default).strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{variable_name} must be an integer greater than 0") from exc
    if value <= 0:
        raise ValueError(f"{variable_name} must be an integer greater than 0")
    if maximum is not None and value > maximum:
        raise ValueError(f"{variable_name} must be an integer no greater than {maximum}")
    return value


def _non_negative_integer(
    variable_name: str,
    default: str,
    *,
    maximum: int | None = None,
) -> int:
    raw_value = os.getenv(variable_name, default).strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{variable_name} must be an integer greater than or equal to 0") from exc
    if value < 0:
        raise ValueError(f"{variable_name} must be an integer greater than or equal to 0")
    if maximum is not None and value > maximum:
        raise ValueError(f"{variable_name} must be an integer no greater than {maximum}")
    return value


def _optional_http_webhook_url(variable_name: str) -> str:
    raw_value = os.getenv(variable_name, "").strip()
    if not raw_value:
        return ""
    parsed = urlsplit(raw_value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{variable_name} must be an HTTP(S) URL")
    if parsed.username or parsed.password:
        raise ValueError(f"{variable_name} must not include credentials")
    if parsed.query or parsed.fragment:
        raise ValueError(f"{variable_name} must not include a query or fragment")
    return raw_value


def _snapshot_quality_overrides() -> dict[str, dict[str, int | float]]:
    raw_value = os.getenv("FUND_SNAPSHOT_QUALITY_OVERRIDES", "").strip()
    if not raw_value:
        return {}
    try:
        decoded = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise ValueError("FUND_SNAPSHOT_QUALITY_OVERRIDES must be valid JSON") from exc
    if not isinstance(decoded, dict):
        raise ValueError("FUND_SNAPSHOT_QUALITY_OVERRIDES must be a JSON object")
    allowed_fields = {
        "min_fund_count",
        "min_nav_coverage_ratio",
        "max_latest_nav_age_days",
        "max_fund_count_drop_ratio",
    }
    overrides: dict[str, dict[str, int | float]] = {}
    for raw_key, raw_config in decoded.items():
        if not isinstance(raw_key, str) or not raw_key.strip():
            raise ValueError("FUND_SNAPSHOT_QUALITY_OVERRIDES keys must be non-empty strings")
        if not isinstance(raw_config, dict):
            raise ValueError(
                "FUND_SNAPSHOT_QUALITY_OVERRIDES values must be JSON objects"
            )
        unknown_fields = set(raw_config) - allowed_fields
        if unknown_fields:
            raise ValueError(
                "FUND_SNAPSHOT_QUALITY_OVERRIDES contains unsupported fields: "
                + ", ".join(sorted(unknown_fields))
            )
        normalized: dict[str, int | float] = {}
        for field_name, field_value in raw_config.items():
            if field_name in {"min_fund_count", "max_latest_nav_age_days"}:
                if not isinstance(field_value, int) or isinstance(field_value, bool) or field_value < 0:
                    raise ValueError(
                        f"FUND_SNAPSHOT_QUALITY_OVERRIDES.{raw_key}.{field_name} "
                        "must be an integer greater than or equal to 0"
                    )
                normalized[field_name] = field_value
            else:
                if (
                    not isinstance(field_value, int | float)
                    or isinstance(field_value, bool)
                    or not math.isfinite(float(field_value))
                    or float(field_value) < 0
                    or float(field_value) > 1
                ):
                    raise ValueError(
                        f"FUND_SNAPSHOT_QUALITY_OVERRIDES.{raw_key}.{field_name} "
                        "must be a finite number between 0 and 1"
                    )
                normalized[field_name] = float(field_value)
        overrides[raw_key.strip()] = normalized
    return overrides


def _strict_boolean(variable_name: str, default: str) -> bool:
    value = os.getenv(variable_name, default).strip().lower()
    if value not in {"true", "false"}:
        raise ValueError(f"{variable_name} must be true or false")
    return value == "true"


def _normalize_http_origin(raw_origin: str, *, variable_name: str) -> str:
    origin = raw_origin.strip()
    if not origin:
        raise ValueError(f"{variable_name} must not contain an empty origin")
    if "*" in origin:
        raise ValueError(
            f"{variable_name} must use explicit origins; wildcards are not allowed with credentials"
        )

    try:
        parsed = urlsplit(origin)
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"{variable_name} contains an invalid origin: {origin!r}") from exc

    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError(
            f"{variable_name} origins must use http:// or https:// and include a host: {origin!r}"
        )
    if parsed.username or parsed.password:
        raise ValueError(f"{variable_name} origins must not include credentials: {origin!r}")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError(
            f"{variable_name} origins must not include a path, query, or fragment: {origin!r}"
        )

    scheme = parsed.scheme.lower()
    hostname = parsed.hostname.lower()
    if ":" in hostname:
        hostname = f"[{hostname}]"
    is_default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    port_suffix = "" if port is None or is_default_port else f":{port}"
    return f"{scheme}://{hostname}{port_suffix}"


def _parse_cors_origins(raw_origins: str) -> tuple[str, ...]:
    origins: list[str] = []
    for raw_origin in raw_origins.split(","):
        if not raw_origin.strip():
            continue
        normalized = _normalize_http_origin(raw_origin, variable_name="CORS_ORIGINS")
        if normalized not in origins:
            origins.append(normalized)
    return tuple(origins)


def _parse_proxy_urls(raw_proxy_urls: str) -> tuple[str, ...]:
    proxy_urls: list[str] = []
    for raw_proxy_url in raw_proxy_urls.split(","):
        proxy_url = raw_proxy_url.strip()
        if not proxy_url:
            continue
        parsed = urlsplit(proxy_url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise ValueError(
                "PUBLIC_FUND_DATA_PROXY_URLS entries must be explicit http(s) proxy URLs"
            )
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError(
                "PUBLIC_FUND_DATA_PROXY_URLS entries must not contain credentials, query, or fragment"
            )
        if parsed.path not in {"", "/"}:
            raise ValueError("PUBLIC_FUND_DATA_PROXY_URLS entries must not contain a path")
        if proxy_url not in proxy_urls:
            proxy_urls.append(proxy_url)
    return tuple(proxy_urls)


class Settings:
    def __init__(self) -> None:
        self.app_environment = os.getenv("APP_ENVIRONMENT", "development").strip().lower()
        if self.app_environment not in {"development", "test", *DEPLOYED_ENVIRONMENTS}:
            raise ValueError("APP_ENVIRONMENT must be development, test, staging, or production")
        # SQLite is the zero-configuration local development store. Deployments
        # can still provide DATABASE_URL explicitly (for example PostgreSQL).
        self.database_url = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_SQLITE_DATABASE}")
        self.database_connect_timeout_seconds = max(
            1,
            int(os.getenv("DATABASE_CONNECT_TIMEOUT_SECONDS", "2")),
        )
        self.data_status_timeout_seconds = max(
            0.1,
            float(os.getenv("DATA_STATUS_TIMEOUT_SECONDS", "2.5")),
        )
        configured_cors_origins = os.getenv("CORS_ORIGINS")
        if self.app_environment in DEPLOYED_ENVIRONMENTS and configured_cors_origins is None:
            raise ValueError(
                "CORS_ORIGINS must be explicitly set when APP_ENVIRONMENT is staging or production"
            )
        raw_cors_origins = configured_cors_origins or ",".join(DEFAULT_CORS_ORIGINS)
        self.cors_origins = _parse_cors_origins(raw_cors_origins)
        if not self.cors_origins:
            raise ValueError("CORS_ORIGINS must contain at least one explicit http(s) origin")

        raw_web_origin = os.getenv("WEB_ORIGIN", "")
        self.web_origin = (
            _normalize_http_origin(raw_web_origin, variable_name="WEB_ORIGIN")
            if raw_web_origin.strip()
            else ""
        )
        if self.app_environment in DEPLOYED_ENVIRONMENTS:
            if not self.web_origin:
                raise ValueError(
                    "WEB_ORIGIN must be explicitly set when APP_ENVIRONMENT is staging or production"
                )
            if self.web_origin not in self.cors_origins:
                raise ValueError(
                    "WEB_ORIGIN must exactly match an entry in CORS_ORIGINS; "
                    f"missing {self.web_origin!r}"
                )
        self.fund_data_stale_days = int(os.getenv("FUND_DATA_STALE_DAYS", "7"))
        self.fund_data_source = os.getenv("FUND_DATA_SOURCE", "sample_local")
        self.fund_csv_dir = os.getenv("FUND_CSV_DIR", "data/funds")
        self.fund_nav_value_min = _positive_finite_float("FUND_NAV_VALUE_MIN", "0.01")
        self.fund_nav_value_max = _positive_finite_float("FUND_NAV_VALUE_MAX", "100")
        self.fund_accumulated_nav_value_min = _positive_finite_float(
            "FUND_ACCUMULATED_NAV_VALUE_MIN",
            "0.01",
        )
        self.fund_accumulated_nav_value_max = _positive_finite_float(
            "FUND_ACCUMULATED_NAV_VALUE_MAX",
            "1000",
        )
        if self.fund_nav_value_min >= self.fund_nav_value_max:
            raise ValueError("FUND_NAV_VALUE_MIN must be less than FUND_NAV_VALUE_MAX")
        if self.fund_accumulated_nav_value_min >= self.fund_accumulated_nav_value_max:
            raise ValueError(
                "FUND_ACCUMULATED_NAV_VALUE_MIN must be less than FUND_ACCUMULATED_NAV_VALUE_MAX"
            )
        self.fund_nav_reject_anomalies = _strict_boolean(
            "FUND_NAV_REJECT_ANOMALIES",
            "false",
        )
        self.fund_snapshot_min_fund_count = _non_negative_integer(
            "FUND_SNAPSHOT_MIN_FUND_COUNT",
            "1",
        )
        self.fund_snapshot_min_nav_coverage_ratio = _non_negative_rate_threshold(
            "FUND_SNAPSHOT_MIN_NAV_COVERAGE_RATIO",
            "0",
        )
        self.fund_snapshot_max_latest_nav_age_days = _non_negative_integer(
            "FUND_SNAPSHOT_MAX_LATEST_NAV_AGE_DAYS",
            "0",
        )
        self.fund_snapshot_max_fund_count_drop_ratio = _non_negative_rate_threshold(
            "FUND_SNAPSHOT_MAX_FUND_COUNT_DROP_RATIO",
            "1",
        )
        self.fund_snapshot_quality_overrides = _snapshot_quality_overrides()
        self.public_fund_data_base_url = os.getenv("PUBLIC_FUND_DATA_BASE_URL", "")
        self.public_fund_data_profile = os.getenv(
            "PUBLIC_FUND_DATA_PROFILE",
            "generic_aliases_v1",
        ).strip()
        self.public_fund_data_timeout_seconds = int(
            os.getenv("PUBLIC_FUND_DATA_TIMEOUT_SECONDS", "10")
        )
        self.public_fund_data_cache_dir = os.getenv("PUBLIC_FUND_DATA_CACHE_DIR", "")
        self.public_fund_data_min_interval_seconds = max(
            0.0,
            float(os.getenv("PUBLIC_FUND_DATA_MIN_INTERVAL_SECONDS", "0")),
        )
        self.public_fund_data_batch_size = max(
            1,
            int(os.getenv("PUBLIC_FUND_DATA_BATCH_SIZE", "100")),
        )
        self.public_fund_data_max_pages = max(
            1,
            int(os.getenv("PUBLIC_FUND_DATA_MAX_PAGES", "100")),
        )
        self.public_fund_data_proxy_urls = _parse_proxy_urls(
            os.getenv("PUBLIC_FUND_DATA_PROXY_URLS", "")
        )
        self.yingmi_mcp_endpoint = os.getenv("YINGMI_MCP_ENDPOINT", "")
        self.fund_sync_scheduler_enabled = (
            os.getenv("FUND_SYNC_SCHEDULER_ENABLED", "true").lower() == "true"
        )
        self.fund_sync_schedule_mode = (
            os.getenv("FUND_SYNC_SCHEDULE_MODE", "interval").strip().lower()
        )
        if self.fund_sync_schedule_mode not in {"interval", "cron"}:
            raise ValueError("FUND_SYNC_SCHEDULE_MODE must be interval or cron")
        self.fund_sync_interval_minutes = _positive_integer(
            "FUND_SYNC_INTERVAL_MINUTES",
            "5",
        )
        self.fund_sync_cron = os.getenv("FUND_SYNC_CRON", "15 2 * * *").strip()
        self.fund_sync_jitter_seconds = max(0, int(os.getenv("FUND_SYNC_JITTER_SECONDS", "120")))
        self.fund_sync_misfire_grace_seconds = max(
            1,
            int(os.getenv("FUND_SYNC_MISFIRE_GRACE_SECONDS", "900")),
        )
        self.fund_sync_lock_timeout_minutes = max(
            1,
            int(os.getenv("FUND_SYNC_LOCK_TIMEOUT_MINUTES", "120")),
        )
        self.llm_provider = os.getenv("LLM_PROVIDER", "mock").strip()
        self.llm_model = os.getenv("LLM_MODEL", "mock-compliance-v1").strip()
        self.llm_api_key = os.getenv("LLM_API_KEY", "").strip()
        self.llm_base_url = os.getenv("LLM_BASE_URL", "").strip()
        self.llm_timeout_seconds = max(1, int(os.getenv("LLM_TIMEOUT_SECONDS", "15")))
        self.llm_max_retries = max(0, int(os.getenv("LLM_MAX_RETRIES", "1")))
        self.llm_max_response_bytes = _positive_integer(
            "LLM_MAX_RESPONSE_BYTES",
            "65536",
            maximum=10_485_760,
        )
        self.llm_max_output_chars = _positive_integer(
            "LLM_MAX_OUTPUT_CHARS",
            "1000",
            maximum=100_000,
        )
        self.llm_audit_enabled = _strict_boolean("LLM_AUDIT_ENABLED", "true")
        self.llm_observability_window_minutes = _positive_integer(
            "LLM_OBSERVABILITY_WINDOW_MINUTES",
            "60",
            maximum=525_600,
        )
        self.llm_observability_minimum_requests = _positive_integer(
            "LLM_OBSERVABILITY_MINIMUM_REQUESTS",
            "5",
            maximum=1_000_000,
        )
        self.llm_observability_queue_capacity = _positive_integer(
            "LLM_OBSERVABILITY_QUEUE_CAPACITY",
            "256",
            maximum=10_000,
        )
        self.llm_observability_shutdown_timeout_seconds = _positive_finite_float(
            "LLM_OBSERVABILITY_SHUTDOWN_TIMEOUT_SECONDS",
            "2",
        )
        self.llm_observability_retention_days = _positive_integer(
            "LLM_OBSERVABILITY_RETENTION_DAYS",
            "30",
            maximum=3650,
        )
        self.llm_error_rate_alert_threshold = _rate_threshold(
            "LLM_ERROR_RATE_ALERT_THRESHOLD",
            "0.2",
        )
        self.llm_timeout_rate_alert_threshold = _rate_threshold(
            "LLM_TIMEOUT_RATE_ALERT_THRESHOLD",
            "0.1",
        )
        self.llm_alert_webhook_url = _optional_http_webhook_url(
            "LLM_ALERT_WEBHOOK_URL"
        )
        self.llm_alert_cooldown_minutes = _positive_integer(
            "LLM_ALERT_COOLDOWN_MINUTES",
            "60",
            maximum=525_600,
        )
        self.llm_alert_timeout_seconds = _positive_finite_float(
            "LLM_ALERT_TIMEOUT_SECONDS",
            "2",
        )


settings = Settings()
