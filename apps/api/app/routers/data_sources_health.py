from typing import Any

from fastapi import APIRouter

from app.core.compliance import envelope
from app.data_sources import get_fund_data_source
from app.schemas.common import ApiResponse
from app.schemas.data_source_health import DataSourceHealthReport

router = APIRouter()


def _unsupported_report(source_name: str) -> DataSourceHealthReport:
    return DataSourceHealthReport(
        source=source_name,
        checked_at="",
        overall_reachable=False,
        enabled=False,
        note="current data source does not support an upstream health probe",
    )


@router.get("/data/sources/health", response_model=ApiResponse[DataSourceHealthReport])
def data_sources_health() -> dict[str, Any]:
    source = get_fund_data_source()
    checker = getattr(source, "health_check", None)
    if not callable(checker):
        report = _unsupported_report(source.name)
        return envelope(report, source=source.name)
    # The health probe performs a single, rate-limited minimal request and never
    # writes to the database or triggers a full pull; errors are captured in the
    # report instead of raised.
    report = DataSourceHealthReport.model_validate(checker())
    return envelope(report, source=source.name)
