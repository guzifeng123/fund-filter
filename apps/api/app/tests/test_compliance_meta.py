from datetime import datetime, timezone

from app.core.compliance import envelope, error_envelope, meta
from app.main import app


def test_meta_uses_null_when_no_data_timestamp_is_known() -> None:
    assert meta()["data_updated_at"] is None
    assert envelope({"ok": True})["meta"]["data_updated_at"] is None
    assert error_envelope("TEST_ERROR", "test")["meta"]["data_updated_at"] is None


def test_meta_preserves_a_real_data_timestamp() -> None:
    timestamp = datetime(2026, 7, 13, 8, 30, tzinfo=timezone.utc)

    assert meta(data_updated_at=timestamp)["data_updated_at"] == "2026-07-13T08:30:00+00:00"


def test_openapi_marks_meta_data_timestamp_nullable() -> None:
    schema = app.openapi()["components"]["schemas"]["ApiMeta"]["properties"]["data_updated_at"]

    assert {candidate.get("type") for candidate in schema["anyOf"]} == {"string", "null"}
