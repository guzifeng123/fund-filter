import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import (
    LEGACY_SNAPSHOT_GENERATION_ID,
    FundDataSnapshotState,
)
from app.jobs import sync_fund_data
from app.repositories.fund_archives import (
    MANIFEST_FILE_NAME,
    archive_generation,
    list_archive_generations,
    prune_fund_archives,
)
from app.repositories.fund_snapshots import SNAPSHOT_STATE_ROW_ID
from app.services.sample_data import FUNDS
from app.tests.test_snapshot_sync import SnapshotSourceStub, _install_source


def _read_manifest(archive_dir: Path) -> dict[str, Any]:
    result: dict[str, Any] = json.loads((archive_dir / MANIFEST_FILE_NAME).read_text(encoding="utf-8"))
    return result


def test_archive_generation_writes_verifiable_manifest(
    db_session: Session,
    tmp_path: Path,
) -> None:
    archive = archive_generation(
        db_session,
        LEGACY_SNAPSHOT_GENERATION_ID,
        archive_root=tmp_path,
    )
    archive_dir = Path(archive.archive_dir)
    manifest = _read_manifest(archive_dir)

    assert manifest["generation_id"] == LEGACY_SNAPSHOT_GENERATION_ID
    assert manifest["counts"] == {
        "funds": len(FUNDS),
        "navs": sum(len(fund.navs) for fund in FUNDS),
        "metrics": len(FUNDS),
    }
    assert set(manifest["files"]) == {"funds.jsonl", "fund_navs.jsonl", "fund_metrics.jsonl"}

    # Independently re-hash every payload file and confirm the manifest matches.
    for file_name, expected in manifest["files"].items():
        digest = hashlib.sha256((archive_dir / file_name).read_bytes()).hexdigest()
        assert digest == expected["sha256"]
        lines = (archive_dir / file_name).read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == expected["lines"]
        for line in lines:
            json.loads(line)  # every line must be valid JSON

    manifest_digest = hashlib.sha256((archive_dir / MANIFEST_FILE_NAME).read_bytes()).hexdigest()
    assert manifest_digest == archive.manifest_sha256


def test_archive_failure_does_not_block_promotion(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = SnapshotSourceStub([fund.model_copy(deep=True) for fund in FUNDS])
    _install_source(monkeypatch, source)
    monkeypatch.setattr(settings, "fund_archive_dir", tmp_path / "archives")

    original_archive = sync_fund_data.archive_generation  # type: ignore[attr-defined]

    def boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("disk on strike")

    monkeypatch.setattr(sync_fund_data, "archive_generation", boom)
    details = sync_fund_data.sync_all(db_session, source.name)
    monkeypatch.setattr(sync_fund_data, "archive_generation", original_archive)

    state = db_session.get(FundDataSnapshotState, SNAPSHOT_STATE_ROW_ID)
    assert state is not None
    assert state.active_generation_id == details["snapshot_generation_id"]
    assert details["archive_warning"] == "fund archive failed: disk on strike"
    assert "archive" not in details


def test_successful_archive_is_recorded_in_job_details(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = SnapshotSourceStub([fund.model_copy(deep=True) for fund in FUNDS])
    _install_source(monkeypatch, source)
    archive_root = tmp_path / "archives"
    monkeypatch.setattr(settings, "fund_archive_dir", archive_root)

    details = sync_fund_data.sync_all(db_session, source.name)

    assert details["write_path"] == "batch"
    assert "archive" in details
    archive_details: dict[str, Any] = dict(details["archive"])  # type: ignore[arg-type]
    assert archive_details["generation_id"] == LEGACY_SNAPSHOT_GENERATION_ID
    assert archive_details["fund_count"] == len(FUNDS)
    archived_dir = Path(str(archive_details["archive_dir"]))
    manifest = _read_manifest(archived_dir)
    assert manifest["counts"]["funds"] == len(FUNDS)
    assert hashlib.sha256(
        (archived_dir / MANIFEST_FILE_NAME).read_bytes()
    ).hexdigest() == archive_details["manifest_sha256"]


def _touch_archive(archive_root: Path, generation_id: str, when: str) -> None:
    directory = archive_root / generation_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "funds.jsonl").write_text('{"code": "x"}\n', encoding="utf-8")
    (directory / MANIFEST_FILE_NAME).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generation_id": generation_id,
                "created_at": when,
                "counts": {"funds": 1, "navs": 0, "metrics": 0},
                "files": {
                    "funds.jsonl": {"sha256": "0" * 64, "bytes": 12, "lines": 1}
                },
            }
        ),
        encoding="utf-8",
    )


def test_prune_fund_archives_dry_run_then_apply(tmp_path: Path) -> None:
    archive_root = tmp_path / "archives"
    _touch_archive(archive_root, "gen-oldest", "2026-01-01T00:00:00+00:00")
    _touch_archive(archive_root, "gen-middle", "2026-06-01T00:00:00+00:00")
    _touch_archive(archive_root, "gen-newest", "2026-09-01T00:00:00+00:00")

    dry = prune_fund_archives(archive_root, keep_generations=2, dry_run=True)
    assert dry.dry_run is True
    assert dry.deleted_generations == ["gen-oldest"]
    assert dry.kept_generations == ["gen-newest", "gen-middle"]
    assert (archive_root / "gen-oldest").exists()

    applied = prune_fund_archives(archive_root, keep_generations=2, dry_run=False)
    assert applied.dry_run is False
    assert applied.deleted_generations == ["gen-oldest"]
    assert not (archive_root / "gen-oldest").exists()
    assert list_archive_generations(archive_root) == [
        archive_root / "gen-newest",
        archive_root / "gen-middle",
    ]


def test_prune_keeps_everything_when_keep_is_zero(tmp_path: Path) -> None:
    archive_root = tmp_path / "archives"
    _touch_archive(archive_root, "gen-a", "2026-01-01T00:00:00+00:00")
    _touch_archive(archive_root, "gen-b", "2026-06-01T00:00:00+00:00")
    report = prune_fund_archives(archive_root, keep_generations=0, dry_run=False)
    assert report.deleted_generations == []
    assert (archive_root / "gen-a").exists()
    assert (archive_root / "gen-b").exists()


def test_prune_rejects_negative_keep(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="keep_generations"):
        prune_fund_archives(tmp_path, keep_generations=-1)


def test_cleanup_script_dry_run_reports_without_deleting_then_apply(tmp_path: Path) -> None:
    import json as _json
    import subprocess
    import sys

    archive_root = tmp_path / "archives"
    _touch_archive(archive_root, "gen-oldest", "2026-01-01T00:00:00+00:00")
    _touch_archive(archive_root, "gen-newest", "2026-06-01T00:00:00+00:00")
    workspace_root = Path(__file__).resolve().parents[4]
    script = workspace_root / "scripts" / "cleanup_fund_archives.py"

    dry = subprocess.run(
        [
            sys.executable,
            str(script),
            "--archive-dir",
            archive_root.as_posix(),
            "--keep-generations",
            "1",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert dry.returncode == 0, dry.stderr
    dry_report = _json.loads(dry.stdout)
    assert dry_report["dry_run"] is True
    assert dry_report["deleted_generations"] == ["gen-oldest"]
    assert (archive_root / "gen-oldest").exists()

    applied = subprocess.run(
        [
            sys.executable,
            str(script),
            "--archive-dir",
            archive_root.as_posix(),
            "--keep-generations",
            "1",
            "--apply",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert applied.returncode == 0, applied.stderr
    applied_report = _json.loads(applied.stdout)
    assert applied_report["dry_run"] is False
    assert applied_report["deleted_generations"] == ["gen-oldest"]
    assert not (archive_root / "gen-oldest").exists()
