import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

API_ROOT = Path(__file__).resolve().parents[2]


def run_alembic(database_url: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", *arguments],
        cwd=API_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_llm_provider_events_migration_enforces_safe_shape_and_round_trips(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'llm-observability.db').as_posix()}"
    before = run_alembic(database_url, "upgrade", "0008_add_snapshot_generation")
    assert before.returncode == 0, before.stderr

    upgraded = run_alembic(database_url, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr

    engine = create_engine(database_url)
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("llm_provider_events")}
    assert columns == {
        "id",
        "provider_name",
        "model_name",
        "outcome",
        "attempt_count",
        "retry_count",
        "latency_ms",
        "timed_out",
        "error_category",
        "created_at",
    }
    assert "ix_llm_provider_events_provider_model_created_at" in {
        index["name"] for index in inspector.get_indexes("llm_provider_events")
    }
    assert {
        "ck_llm_provider_events_outcome",
        "ck_llm_provider_events_attempt_retry",
        "ck_llm_provider_events_latency_ms",
        "ck_llm_provider_events_error_category",
        "ck_llm_provider_events_fallback_category",
        "ck_llm_provider_events_config_missing_attempt",
        "ck_llm_provider_events_provider_name_safe",
        "ck_llm_provider_events_model_name_safe",
    }.issubset(
        {
            constraint["name"]
            for constraint in inspector.get_check_constraints("llm_provider_events")
        }
    )

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO llm_provider_events (
                    provider_name, model_name, outcome, attempt_count,
                    retry_count, latency_ms, timed_out, error_category, created_at
                ) VALUES (
                    'openai-compatible', 'safe-model', 'success', 2,
                    1, 125, 0, 'network', '2026-07-14 00:00:00'
                )
                """
            )
        )
    insert_event = text(
        """
        INSERT INTO llm_provider_events (
            provider_name, model_name, outcome, attempt_count,
            retry_count, latency_ms, timed_out, error_category, created_at
        ) VALUES (
            :provider_name, :model_name, :outcome, :attempt_count,
            :retry_count, :latency_ms, :timed_out, :error_category, :created_at
        )
        """
    )
    valid_values: dict[str, object] = {
        "provider_name": "provider",
        "model_name": "model",
        "outcome": "success",
        "attempt_count": 1,
        "retry_count": 0,
        "latency_ms": 1,
        "timed_out": False,
        "error_category": None,
        "created_at": "2026-07-14 00:00:00",
    }
    invalid_cases = (
        ("ck_llm_provider_events_outcome", {"outcome": "raw-error"}),
        (
            "ck_llm_provider_events_attempt_retry",
            {"attempt_count": 1, "retry_count": 1},
        ),
        ("ck_llm_provider_events_latency_ms", {"latency_ms": -1}),
        (
            "ck_llm_provider_events_error_category",
            {"error_category": "raw_exception"},
        ),
        (
            "ck_llm_provider_events_fallback_category",
            {"outcome": "fallback", "error_category": None},
        ),
        (
            "ck_llm_provider_events_config_missing_attempt",
            {
                "outcome": "fallback",
                "attempt_count": 0,
                "error_category": "provider_error",
            },
        ),
        (
            "ck_llm_provider_events_provider_name_safe",
            {"provider_name": "api.internal.example:8443"},
        ),
        (
            "ck_llm_provider_events_model_name_safe",
            {"model_name": "https://private.example"},
        ),
    )
    for constraint_name, overrides in invalid_cases:
        with pytest.raises(IntegrityError) as error:
            with engine.begin() as connection:
                connection.execute(insert_event, valid_values | overrides)
        assert constraint_name in str(error.value)

    downgraded = run_alembic(
        database_url,
        "downgrade",
        "0008_add_snapshot_generation",
    )
    assert downgraded.returncode == 0, downgraded.stderr
    assert "llm_provider_events" not in inspect(engine).get_table_names()

    round_trip = run_alembic(database_url, "upgrade", "head")
    assert round_trip.returncode == 0, round_trip.stderr
    assert "llm_provider_events" in inspect(engine).get_table_names()
