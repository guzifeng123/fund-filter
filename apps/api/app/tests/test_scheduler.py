from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-untyped]
from apscheduler.triggers.interval import IntervalTrigger  # type: ignore[import-untyped]
import pytest

from app.core.config import settings
from app.jobs.scheduler import _sync_trigger


def test_interval_trigger_uses_configured_minutes_and_jitter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "fund_sync_schedule_mode", "interval")
    monkeypatch.setattr(settings, "fund_sync_interval_minutes", 5)
    monkeypatch.setattr(settings, "fund_sync_jitter_seconds", 90)

    trigger = _sync_trigger()

    assert isinstance(trigger, IntervalTrigger)
    assert trigger.interval.total_seconds() == 5 * 60
    assert trigger.jitter == 90


def test_cron_trigger_uses_five_fields_and_jitter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "fund_sync_schedule_mode", "cron")
    monkeypatch.setattr(settings, "fund_sync_cron", "30 3 * * 1-5")
    monkeypatch.setattr(settings, "fund_sync_jitter_seconds", 120)

    trigger = _sync_trigger()

    assert isinstance(trigger, CronTrigger)
    assert trigger.jitter == 120
    assert "hour='3'" in str(trigger)
    assert "minute='30'" in str(trigger)


def test_cron_trigger_rejects_nonstandard_field_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "fund_sync_schedule_mode", "cron")
    monkeypatch.setattr(settings, "fund_sync_cron", "0 3 * *")

    with pytest.raises(ValueError, match="five fields"):
        _sync_trigger()
