"""Secondary, read-only cross-check reconciliation sources.

These feeds (danjuan + sina) are independent of the primary eastmoney pipeline.
They are exported here only; wiring them into the runtime registry / sync jobs is
done by the assembly step (they must not be registered in the top-level
``data_sources`` registry from this module).
"""

from app.data_sources.secondary.base import ReconciliationSource, SourceHealth
from app.data_sources.secondary.danjuan import DanjuanSource, DanjuanUpstreamError
from app.data_sources.secondary.sina import SinaQuote, SinaSource, SinaUpstreamError

__all__ = [
    "DanjuanSource",
    "DanjuanUpstreamError",
    "ReconciliationSource",
    "SinaQuote",
    "SinaSource",
    "SinaUpstreamError",
    "SourceHealth",
]
