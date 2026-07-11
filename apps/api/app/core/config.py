import os


class Settings:
    def __init__(self) -> None:
        self.database_url = os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://fund_user:fund_password@localhost:5432/fund_app",
        )
        self.database_connect_timeout_seconds = max(
            1,
            int(os.getenv("DATABASE_CONNECT_TIMEOUT_SECONDS", "2")),
        )
        self.data_status_timeout_seconds = max(
            0.1,
            float(os.getenv("DATA_STATUS_TIMEOUT_SECONDS", "2.5")),
        )
        self.cors_origins = tuple(
            origin.strip()
            for origin in os.getenv(
                "CORS_ORIGINS",
                "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001",
            ).split(",")
            if origin.strip()
        )
        self.fund_data_stale_days = int(os.getenv("FUND_DATA_STALE_DAYS", "7"))
        self.fund_data_source = os.getenv("FUND_DATA_SOURCE", "sample_local")
        self.fund_csv_dir = os.getenv("FUND_CSV_DIR", "data/funds")
        self.public_fund_data_base_url = os.getenv("PUBLIC_FUND_DATA_BASE_URL", "")
        self.public_fund_data_timeout_seconds = int(os.getenv("PUBLIC_FUND_DATA_TIMEOUT_SECONDS", "10"))
        self.fund_sync_scheduler_enabled = os.getenv("FUND_SYNC_SCHEDULER_ENABLED", "false").lower() == "true"
        self.fund_sync_interval_hours = int(os.getenv("FUND_SYNC_INTERVAL_HOURS", "24"))
        self.llm_provider = os.getenv("LLM_PROVIDER", "mock")
        self.llm_model = os.getenv("LLM_MODEL", "mock-compliance-v1")
        self.llm_api_key = os.getenv("LLM_API_KEY", "")
        self.llm_base_url = os.getenv("LLM_BASE_URL", "")


settings = Settings()
