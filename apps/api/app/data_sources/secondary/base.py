"""Contract for secondary, cross-check reconciliation data sources.

These sources are *read-only* independent feeds used to cross-validate the
primary NAV/profile pipeline. They never write to the database and never
fabricate data: when upstream is unreachable or a field is missing they report
that explicitly so the reconciliation engine can treat the gap as a missing
cross-check rather than a silent mismatch.
"""

from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable

from app.core.reconciliation import ReconcilableNavPoint, ReconcilableProfile


@dataclass(frozen=True)
class SourceHealth:
    """Lightweight reachability probe result for a secondary source.

    ``reachable`` must be ``False`` (with ``error`` set) whenever any part of
    the probe fails; a probe must never report success on a fabricated response.
    """

    reachable: bool
    latency_ms: float | None = None
    error: str | None = None


@runtime_checkable
class ReconciliationSource(Protocol):
    """Read-only secondary feed that can reconcile against the primary store."""

    source_name: str

    def health_check(self) -> SourceHealth:
        """Cheap probe: reachability + latency, never fabricate success."""
        ...

    def fetch_profile(self, code: str) -> ReconcilableProfile:
        """Fetch one fund's static profile (raw upstream fields)."""
        ...

    def fetch_navs(self, code: str, since: date | None = None) -> list[ReconcilableNavPoint]:
        """Fetch NAV points for ``code`` (newest-first), optionally incrementally."""
        ...
