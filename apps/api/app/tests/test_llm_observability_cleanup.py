from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import LlmProviderEvent
from app.repositories.llm_observability import cleanup_llm_provider_events


def _add_event(db: Session, *, created_at: datetime) -> None:
    db.add(
        LlmProviderEvent(
            provider_name="provider",
            model_name="model",
            outcome="success",
            attempt_count=1,
            retry_count=0,
            latency_ms=50,
            timed_out=False,
            error_category=None,
            created_at=created_at,
        )
    )


def test_cleanup_llm_provider_events_dry_run_reports_without_deleting(
    db_session: Session,
) -> None:
    now = datetime(2026, 7, 16, 8, 0, tzinfo=timezone.utc)
    _add_event(db_session, created_at=now - timedelta(days=45))
    _add_event(db_session, created_at=now - timedelta(days=5))
    db_session.commit()

    report = cleanup_llm_provider_events(
        db_session,
        retention_days=30,
        dry_run=True,
        now=now,
    )

    assert report.schema_version == 1
    assert report.ok is True
    assert report.dry_run is True
    assert report.retention_days == 30
    assert report.cutoff_at == now - timedelta(days=30)
    assert report.matched_count == 1
    assert report.deleted_count == 0
    assert report.remaining_count == 2
    assert db_session.scalar(select(func.count(LlmProviderEvent.id))) == 2


def test_cleanup_llm_provider_events_deletes_only_expired_events(
    db_session: Session,
) -> None:
    now = datetime(2026, 7, 16, 8, 0, tzinfo=timezone.utc)
    old_event_at = now - timedelta(days=31)
    recent_event_at = now - timedelta(days=1)
    _add_event(db_session, created_at=old_event_at)
    _add_event(db_session, created_at=recent_event_at)
    db_session.commit()

    report = cleanup_llm_provider_events(
        db_session,
        retention_days=30,
        now=now,
    )

    remaining_events = db_session.scalars(select(LlmProviderEvent)).all()
    assert report.dry_run is False
    assert report.matched_count == 1
    assert report.deleted_count == 1
    assert report.remaining_count == 1
    assert len(remaining_events) == 1
    assert remaining_events[0].created_at == recent_event_at.replace(tzinfo=None)


def test_cleanup_llm_provider_events_rejects_invalid_retention_days(
    db_session: Session,
) -> None:
    with pytest.raises(ValueError, match="retention_days"):
        cleanup_llm_provider_events(db_session, retention_days=0)
