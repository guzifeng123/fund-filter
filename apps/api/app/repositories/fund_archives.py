"""Export superseded snapshot generations to on-disk archives with a manifest.

Archiving runs at promotion time, *before* the staging writes mutate the old
active generation's rows in place. It is best-effort: the caller must wrap it in
``try/except`` so a broken archive directory can never block promotion. The
manifest lists every payload file with its SHA-256 hex digest and row count so
an archive can be independently re-verified.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Fund, FundMetric, FundNav

ARCHIVE_SCHEMA_VERSION = 1
FUNDS_FILE_NAME = "funds.jsonl"
NAVS_FILE_NAME = "fund_navs.jsonl"
METRICS_FILE_NAME = "fund_metrics.jsonl"
MANIFEST_FILE_NAME = "manifest.json"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"object of type {type(value).__name__} is not JSON serializable")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> tuple[str, int]:
    payload = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, default=_json_default) + "\n"
        for row in rows
    )
    path.write_text(payload, encoding="utf-8")
    return _sha256_file(path), path.stat().st_size


def _fund_row_to_dict(row: Fund) -> dict[str, Any]:
    return {
        "code": row.code,
        "name": row.name,
        "fund_type": row.fund_type,
        "risk_level": row.risk_level,
        "manager_name": row.manager_name,
        "inception_date": row.inception_date.isoformat(),
        "fund_size_billion": row.fund_size_billion,
        "management_fee": row.management_fee,
        "custody_fee": row.custody_fee,
        "source": row.source,
        "data_updated_at": row.data_updated_at.isoformat(),
        "ai_summary": row.ai_summary,
        "raw_data": row.raw_data,
        "snapshot_generation_id": row.snapshot_generation_id,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _nav_row_to_dict(row: FundNav) -> dict[str, Any]:
    return {
        "fund_code": row.fund_code,
        "trade_date": row.trade_date,
        "trade_date_precision": row.trade_date_precision,
        "nav": row.nav,
        "accumulated_nav": row.accumulated_nav,
        "raw_data": row.raw_data,
        "snapshot_generation_id": row.snapshot_generation_id,
    }


def _metric_row_to_dict(row: FundMetric) -> dict[str, Any]:
    return {
        "fund_code": row.fund_code,
        "annualized_return_3y": row.annualized_return_3y,
        "annualized_return_5y": row.annualized_return_5y,
        "max_drawdown": row.max_drawdown,
        "sharpe_ratio": row.sharpe_ratio,
        "category_rank_percentile": row.category_rank_percentile,
        "manager_years": row.manager_years,
        "raw_data": row.raw_data,
        "snapshot_generation_id": row.snapshot_generation_id,
        "updated_at": row.updated_at.isoformat(),
    }


@dataclass(frozen=True)
class GenerationArchive:
    schema_version: int
    generation_id: str
    archive_dir: str
    manifest_path: str
    manifest_sha256: str
    fund_count: int
    nav_count: int
    metric_count: int
    files: dict[str, dict[str, Any]] = field(default_factory=dict)


def archive_generation(
    db: Session,
    generation_id: str,
    *,
    archive_root: Path,
    now: datetime | None = None,
) -> GenerationArchive:
    """Export every row belonging to ``generation_id`` under ``archive_root``.

    Raises on I/O or serialization failures; the caller decides whether to turn
    that into a warning. A generation with zero funds still produces a manifest
    with zero counts so promotions are auditable end to end.
    """
    created_at = now or _utc_now()
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    destination = Path(archive_root) / generation_id
    destination.mkdir(parents=True, exist_ok=True)

    funds = list(
        db.scalars(select(Fund).where(Fund.snapshot_generation_id == generation_id).order_by(Fund.code))
    )
    navs = list(
        db.scalars(
            select(FundNav)
            .where(FundNav.snapshot_generation_id == generation_id)
            .order_by(FundNav.fund_code, FundNav.trade_date, FundNav.id)
        )
    )
    metrics = list(
        db.scalars(
            select(FundMetric)
            .where(FundMetric.snapshot_generation_id == generation_id)
            .order_by(FundMetric.fund_code)
        )
    )

    funds_path = destination / FUNDS_FILE_NAME
    navs_path = destination / NAVS_FILE_NAME
    metrics_path = destination / METRICS_FILE_NAME

    funds_sha, funds_bytes = _write_jsonl(
        funds_path, [_fund_row_to_dict(row) for row in funds]
    )
    navs_sha, navs_bytes = _write_jsonl(
        navs_path, [_nav_row_to_dict(row) for row in navs]
    )
    metrics_sha, metrics_bytes = _write_jsonl(
        metrics_path, [_metric_row_to_dict(row) for row in metrics]
    )

    manifest: dict[str, Any] = {
        "schema_version": ARCHIVE_SCHEMA_VERSION,
        "generation_id": generation_id,
        "created_at": created_at.isoformat(),
        "counts": {
            "funds": len(funds),
            "navs": len(navs),
            "metrics": len(metrics),
        },
        "files": {
            FUNDS_FILE_NAME: {
                "sha256": funds_sha,
                "bytes": funds_bytes,
                "lines": len(funds),
            },
            NAVS_FILE_NAME: {
                "sha256": navs_sha,
                "bytes": navs_bytes,
                "lines": len(navs),
            },
            METRICS_FILE_NAME: {
                "sha256": metrics_sha,
                "bytes": metrics_bytes,
                "lines": len(metrics),
            },
        },
    }
    manifest_path = destination / MANIFEST_FILE_NAME
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest_sha = _sha256_file(manifest_path)
    return GenerationArchive(
        schema_version=ARCHIVE_SCHEMA_VERSION,
        generation_id=generation_id,
        archive_dir=destination.as_posix(),
        manifest_path=manifest_path.as_posix(),
        manifest_sha256=manifest_sha,
        fund_count=len(funds),
        nav_count=len(navs),
        metric_count=len(metrics),
        files=manifest["files"],
    )


def _read_manifest_generated_at(manifest_path: Path) -> datetime:
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _utc_now()
    raw_created_at = data.get("created_at")
    if isinstance(raw_created_at, str):
        try:
            return datetime.fromisoformat(raw_created_at)
        except ValueError:
            pass
    return _utc_now()


def list_archive_generations(archive_root: Path) -> list[Path]:
    """Return generation directories that contain a readable manifest, newest first."""
    root = Path(archive_root)
    if not root.exists():
        return []
    candidates = [
        entry
        for entry in root.iterdir()
        if entry.is_dir() and (entry / MANIFEST_FILE_NAME).exists()
    ]
    candidates.sort(
        key=lambda entry: _read_manifest_generated_at(entry / MANIFEST_FILE_NAME),
        reverse=True,
    )
    return candidates


@dataclass(frozen=True)
class ArchivePruneReport:
    schema_version: int
    ok: bool
    dry_run: bool
    keep_generations: int
    scanned_generations: list[str]
    kept_generations: list[str]
    deleted_generations: list[str]
    freed_bytes: int


def prune_fund_archives(
    archive_root: Path,
    *,
    keep_generations: int,
    dry_run: bool = True,
) -> ArchivePruneReport:
    """Keep the newest ``keep_generations`` archive generations.

    ``keep_generations <= 0`` keeps everything (the default: archive-only, no
    local file deletion). ``dry_run=True`` only reports what would be removed.
    """
    if keep_generations < 0:
        raise ValueError("keep_generations must be greater than or equal to 0")
    generations = list_archive_generations(archive_root)
    generation_ids = [entry.name for entry in generations]
    if keep_generations <= 0 or len(generations) <= keep_generations:
        return ArchivePruneReport(
            schema_version=ARCHIVE_SCHEMA_VERSION,
            ok=True,
            dry_run=dry_run,
            keep_generations=keep_generations,
            scanned_generations=generation_ids,
            kept_generations=generation_ids,
            deleted_generations=[],
            freed_bytes=0,
        )
    stale = generations[keep_generations:]
    kept = generations[:keep_generations]
    deleted: list[str] = []
    freed_bytes = 0
    for directory in stale:
        for child in directory.rglob("*"):
            if child.is_file():
                try:
                    freed_bytes += child.stat().st_size
                except OSError:
                    continue
        if not dry_run:
            for child in sorted(directory.rglob("*"), reverse=True):
                if child.is_dir():
                    child.rmdir()
                else:
                    child.unlink()
            directory.rmdir()
        deleted.append(directory.name)
    return ArchivePruneReport(
        schema_version=ARCHIVE_SCHEMA_VERSION,
        ok=True,
        dry_run=dry_run,
        keep_generations=keep_generations,
        scanned_generations=generation_ids,
        kept_generations=[entry.name for entry in kept],
        deleted_generations=deleted,
        freed_bytes=freed_bytes,
    )


def resolve_archive_root(configured: Path) -> Path:
    """Resolve a possibly-relative archive root against the repository root.

    ``settings.fund_archive_dir`` defaults to a repo-root-relative path; callers
    that pass an absolute path are used verbatim.
    """
    candidate = Path(configured)
    if candidate.is_absolute():
        return candidate
    workspace_root = Path(__file__).resolve().parents[4]
    return workspace_root / candidate


def append_archive_details(details: dict[str, Any], archive: GenerationArchive) -> None:
    """Best-effort helper to record archive provenance in a job's details JSON."""
    details["archive"] = {
        "generation_id": archive.generation_id,
        "archive_dir": archive.archive_dir,
        "manifest_path": archive.manifest_path,
        "manifest_sha256": archive.manifest_sha256,
        "fund_count": archive.fund_count,
        "nav_count": archive.nav_count,
        "metric_count": archive.metric_count,
    }


__all__ = [
    "ARCHIVE_SCHEMA_VERSION",
    "FUNDS_FILE_NAME",
    "MANIFEST_FILE_NAME",
    "METRICS_FILE_NAME",
    "NAVS_FILE_NAME",
    "ArchivePruneReport",
    "GenerationArchive",
    "append_archive_details",
    "archive_generation",
    "list_archive_generations",
    "prune_fund_archives",
    "resolve_archive_root",
]
