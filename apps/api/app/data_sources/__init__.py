from app.core.config import settings
from app.data_sources.base import FundDataSource
from app.data_sources.csv_local import CsvLocalFundDataSource
from app.data_sources.eastmoney_direct import EastmoneyDirectFundDataSource
from app.data_sources.public_http_json import PublicHttpJsonFundDataSource
from app.data_sources.sample_local import SampleLocalFundDataSource


def get_fund_data_source(name: str | None = None) -> FundDataSource:
    source_name = name or settings.fund_data_source
    if source_name == "sample_local":
        return SampleLocalFundDataSource()
    if source_name == "csv_local":
        return CsvLocalFundDataSource()
    if source_name == "public_http_json":
        return PublicHttpJsonFundDataSource()
    if source_name == "eastmoney_direct":
        return EastmoneyDirectFundDataSource()
    raise ValueError(f"unknown fund data source: {source_name}")
