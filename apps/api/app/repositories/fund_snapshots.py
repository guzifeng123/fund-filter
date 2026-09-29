from datetime import datetime, timezone

from sqlalchemy import and_, func, literal, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.core.config import settings
from app.db.models import (
    LEGACY_SNAPSHOT_GENERATION_ID,
    Fund,
    FundDataSnapshot,
    FundDataSnapshotState,
    FundMetric,
    FundNav,
)

SNAPSHOT_STATE_ROW_ID = 1


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def active_snapshot_generation_id(db: Session) -> str:
    """Return the promoted generation, with an explicit legacy fallback.

    Alembic 0008 always creates the singleton state row. The fallback keeps
    metadata-created test databases and interrupted pre-0008 upgrades readable,
    but still limits reads to the known legacy generation instead of exposing
    arbitrary mixed generations.
    """
    generation_id = db.scalar(
        select(FundDataSnapshotState.active_generation_id).where(
            FundDataSnapshotState.id == SNAPSHOT_STATE_ROW_ID
        )
    )
    return generation_id or LEGACY_SNAPSHOT_GENERATION_ID


def active_snapshot_generation_expression() -> ColumnElement[str]:
    """Resolve the active generation inside the caller's data statement.

    Keeping the pointer lookup and row filtering in one SQL statement prevents
    a concurrent promotion from changing the generation between two reads.
    """
    active_generation = (
        select(FundDataSnapshotState.active_generation_id)
        .where(FundDataSnapshotState.id == SNAPSHOT_STATE_ROW_ID)
        .scalar_subquery()
    )
    return func.coalesce(
        active_generation,
        literal(LEGACY_SNAPSHOT_GENERATION_ID),
    )


def _snapshot_source(db: Session, generation_id: str, fallback: str) -> str:
    raw_sources = db.scalars(
        select(Fund.source)
        .where(Fund.snapshot_generation_id == generation_id)
        .distinct()
        .order_by(Fund.source)
    ).all()
    sources = [source.strip() for source in raw_sources if source and source.strip()]
    if not sources:
        return fallback
    if len(sources) == 1:
        return sources[0]
    return f"mixed({len(sources)} sources)"


def snapshot_row_counts(db: Session, generation_id: str) -> tuple[int, int, int]:
    fund_count = db.scalar(
        select(func.count()).select_from(Fund).where(
            Fund.snapshot_generation_id == generation_id
        )
    ) or 0
    nav_count = db.scalar(
        select(func.count()).select_from(FundNav).where(
            FundNav.snapshot_generation_id == generation_id
        )
    ) or 0
    metric_count = db.scalar(
        select(func.count()).select_from(FundMetric).where(
            FundMetric.snapshot_generation_id == generation_id
        )
    ) or 0
    return fund_count, nav_count, metric_count


def ensure_snapshot_state(db: Session) -> FundDataSnapshotState:
    snapshot = db.get(FundDataSnapshot, LEGACY_SNAPSHOT_GENERATION_ID)
    if snapshot is None:
        snapshot = FundDataSnapshot(
            generation_id=LEGACY_SNAPSHOT_GENERATION_ID,
            source=_snapshot_source(
                db,
                LEGACY_SNAPSHOT_GENERATION_ID,
                settings.fund_data_source,
            ),
            status="active",
            fund_count=0,
            nav_count=0,
            metric_count=0,
            promoted_at=_utc_now(),
        )
        (
            snapshot.fund_count,
            snapshot.nav_count,
            snapshot.metric_count,
        ) = snapshot_row_counts(db, LEGACY_SNAPSHOT_GENERATION_ID)
        db.add(snapshot)
        db.flush()

    state = db.get(FundDataSnapshotState, SNAPSHOT_STATE_ROW_ID)
    if state is None:
        state = FundDataSnapshotState(
            id=SNAPSHOT_STATE_ROW_ID,
            active_generation_id=LEGACY_SNAPSHOT_GENERATION_ID,
        )
        db.add(state)
        db.flush()
    return state


def lock_snapshot_state(db: Session) -> FundDataSnapshotState:
    """Serialize all fund-data writers on the stable singleton state row."""
    ensure_snapshot_state(db)
    state = db.scalars(
        select(FundDataSnapshotState)
        .where(FundDataSnapshotState.id == SNAPSHOT_STATE_ROW_ID)
        .with_for_update()
    ).one()
    return state


def stage_snapshot(
    db: Session,
    *,
    generation_id: str,
    source: str,
    fund_count: int,
    nav_count: int,
    metric_count: int,
) -> FundDataSnapshot:
    snapshot = FundDataSnapshot(
        generation_id=generation_id,
        source=source,
        status="staging",
        fund_count=fund_count,
        nav_count=nav_count,
        metric_count=metric_count,
    )
    db.add(snapshot)
    db.flush()
    return snapshot


def validate_staged_snapshot(db: Session, snapshot: FundDataSnapshot) -> None:
    """Flush and prove that every expected candidate row belongs to one generation."""
    db.flush()
    actual = snapshot_row_counts(db, snapshot.generation_id)
    expected = (snapshot.fund_count, snapshot.nav_count, snapshot.metric_count)
    if actual != expected:
        raise RuntimeError(
            "staged snapshot row counts do not match the source snapshot: "
            f"expected={expected}, actual={actual}"
        )
    missing_metrics = db.scalar(
        select(func.count())
        .select_from(Fund)
        .outerjoin(
            FundMetric,
            and_(
                FundMetric.fund_code == Fund.code,
                FundMetric.snapshot_generation_id == snapshot.generation_id,
            ),
        )
        .where(
            Fund.snapshot_generation_id == snapshot.generation_id,
            FundMetric.fund_code.is_(None),
        )
    ) or 0
    orphan_navs = db.scalar(
        select(func.count())
        .select_from(FundNav)
        .outerjoin(
            Fund,
            and_(
                Fund.code == FundNav.fund_code,
                Fund.snapshot_generation_id == snapshot.generation_id,
            ),
        )
        .where(
            FundNav.snapshot_generation_id == snapshot.generation_id,
            Fund.code.is_(None),
        )
    ) or 0
    orphan_metrics = db.scalar(
        select(func.count())
        .select_from(FundMetric)
        .outerjoin(
            Fund,
            and_(
                Fund.code == FundMetric.fund_code,
                Fund.snapshot_generation_id == snapshot.generation_id,
            ),
        )
        .where(
            FundMetric.snapshot_generation_id == snapshot.generation_id,
            Fund.code.is_(None),
        )
    ) or 0
    if missing_metrics or orphan_navs or orphan_metrics:
        raise RuntimeError(
            "staged snapshot contains generation-inconsistent rows: "
            f"missing_metrics={missing_metrics}, orphan_navs={orphan_navs}, "
            f"orphan_metrics={orphan_metrics}"
        )


def refresh_snapshot_metadata(
    db: Session,
    *,
    generation_id: str,
    fallback_source: str,
) -> FundDataSnapshot:
    """Refresh counts after an explicitly in-place maintenance sync."""
    db.flush()
    snapshot = db.get(FundDataSnapshot, generation_id)
    if snapshot is None:
        raise RuntimeError(f"snapshot generation {generation_id!r} does not exist")
    snapshot.source = _snapshot_source(db, generation_id, fallback_source)
    snapshot.fund_count, snapshot.nav_count, snapshot.metric_count = snapshot_row_counts(
        db, generation_id
    )
    return snapshot


def promote_snapshot(
    db: Session,
    *,
    state: FundDataSnapshotState,
    snapshot: FundDataSnapshot,
) -> None:
    previous = db.get(FundDataSnapshot, state.active_generation_id)
    if previous is not None and previous.generation_id != snapshot.generation_id:
        previous.status = "superseded"
    promoted_at = _utc_now()
    snapshot.status = "active"
    snapshot.promoted_at = promoted_at
    state.active_generation_id = snapshot.generation_id
    state.updated_at = promoted_at
