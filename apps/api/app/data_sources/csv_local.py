import csv
from collections.abc import Sequence
from datetime import date, datetime
import json
import math
from pathlib import Path
import sys
from typing import TypedDict

from app.core.config import settings
from app.core.nav_quality import NavQualityWarningPayload, assess_fund_navs
from app.schemas.funds import FundDetail, FundType, NavPoint, RiskLevel

FUND_FIELDS = {
    "code",
    "name",
    "fund_type",
    "risk_level",
    "manager_name",
    "inception_date",
    "fund_size_billion",
    "management_fee",
    "custody_fee",
    "annualized_return_3y",
    "annualized_return_5y",
    "max_drawdown",
    "sharpe_ratio",
    "category_rank_percentile",
    "manager_years",
    "data_updated_at",
}

NAV_FIELDS = {"fund_code", "trade_date", "nav", "accumulated_nav"}

FUND_TYPES_BY_VALUE: dict[str, FundType] = {
    "stock": "stock",
    "mixed": "mixed",
    "bond": "bond",
    "money": "money",
}

RISK_LEVELS_BY_VALUE: dict[str, RiskLevel] = {
    "R1": "R1",
    "R2": "R2",
    "R3": "R3",
    "R4": "R4",
    "R5": "R5",
}


class CsvLocalPreflightReport(TypedDict):
    ok: bool
    source: str
    data_dir: str
    fund_count: int
    nav_count: int
    quality_warnings: list[NavQualityWarningPayload]
    errors: list[str]


def preflight_csv_local(data_dir: str | Path | None = None) -> CsvLocalPreflightReport:
    source = CsvLocalFundDataSource(data_dir)
    errors: list[str] = []
    funds: list[FundDetail] = []
    navs_by_code: dict[str, list[NavPoint]] = {}
    try:
        funds = source.fetch_fund_profiles()
    except Exception as exc:
        errors.append(str(exc))
    try:
        navs_by_code = source._load_navs()
    except Exception as exc:
        errors.append(str(exc))

    fund_codes = {fund.code for fund in funds}
    unknown_nav_codes = sorted(set(navs_by_code) - fund_codes)
    if unknown_nav_codes and not any("funds.csv" in error for error in errors):
        errors.append(
            f"{source.data_dir / 'navs.csv'}: nav rows reference unknown fund codes: {', '.join(unknown_nav_codes)}"
        )
    errors = list(dict.fromkeys(errors))
    quality_warnings = [warning.as_dict() for fund in funds for warning in assess_fund_navs(fund)]
    if quality_warnings and settings.fund_nav_reject_anomalies:
        errors.append(
            "NAV anomaly rejection is enabled and "
            f"{len(quality_warnings)} value(s) are outside configured thresholds"
        )

    return {
        "ok": not errors,
        "source": source.name,
        "data_dir": str(source.data_dir),
        "fund_count": len(funds),
        "nav_count": sum(len(navs) for navs in navs_by_code.values()),
        "quality_warnings": quality_warnings,
        "errors": errors,
    }


class CsvLocalFundDataSource:
    name = "csv_local"

    def __init__(self, data_dir: str | Path | None = None) -> None:
        self.data_dir = Path(data_dir or settings.fund_csv_dir)

    def fetch_snapshot(self) -> list[FundDetail]:
        return self._load_funds()

    def fetch_fund_profiles(self) -> list[FundDetail]:
        return self._load_funds()

    def fetch_fund_navs(self) -> list[FundDetail]:
        return self._load_funds()

    def fetch_risk_levels(self) -> dict[str, str]:
        return {fund.code: fund.risk_level for fund in self._load_funds()}

    def _load_funds(self) -> list[FundDetail]:
        funds_path = self.data_dir / "funds.csv"
        if not funds_path.exists():
            raise FileNotFoundError(f"missing funds.csv: {funds_path}")

        navs_by_code = self._load_navs()
        funds: list[FundDetail] = []
        fund_code_lines: dict[str, int] = {}
        with funds_path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            self._validate_headers(funds_path, reader.fieldnames, FUND_FIELDS)
            for line_number, row in enumerate(reader, start=2):
                code = self._required(funds_path, line_number, row, "code")
                if code in fund_code_lines:
                    raise ValueError(
                        f"{funds_path}:{line_number}: duplicate fund code {code}; "
                        f"first seen at line {fund_code_lines[code]}"
                    )
                fund_code_lines[code] = line_number
                funds.append(
                    FundDetail(
                        code=code,
                        name=self._required(funds_path, line_number, row, "name"),
                        fund_type=self._fund_type(funds_path, line_number, row),
                        risk_level=self._risk_level(funds_path, line_number, row),
                        manager_name=self._required(funds_path, line_number, row, "manager_name"),
                        inception_date=self._date(funds_path, line_number, row, "inception_date"),
                        fund_size_billion=self._range_float(
                            funds_path, line_number, row, "fund_size_billion", minimum=0
                        ),
                        management_fee=self._range_float(
                            funds_path, line_number, row, "management_fee", minimum=0, maximum=100
                        ),
                        custody_fee=self._range_float(
                            funds_path, line_number, row, "custody_fee", minimum=0, maximum=100
                        ),
                        annualized_return_3y=self._float(
                            funds_path, line_number, row, "annualized_return_3y"
                        ),
                        annualized_return_5y=self._float(
                            funds_path, line_number, row, "annualized_return_5y"
                        ),
                        max_drawdown=self._range_float(
                            funds_path, line_number, row, "max_drawdown", minimum=-100, maximum=0
                        ),
                        sharpe_ratio=self._float(funds_path, line_number, row, "sharpe_ratio"),
                        category_rank_percentile=self._range_float(
                            funds_path,
                            line_number,
                            row,
                            "category_rank_percentile",
                            minimum=0,
                            maximum=100,
                        ),
                        manager_years=self._non_negative_integer(
                            funds_path, line_number, row, "manager_years"
                        ),
                        source="csv_local",
                        data_updated_at=self._datetime(
                            funds_path, line_number, row, "data_updated_at"
                        ),
                        ai_summary=(row.get("ai_summary") or "").strip(),
                        navs=navs_by_code.get(code, []),
                    )
                )
        return funds

    def _load_navs(self) -> dict[str, list[NavPoint]]:
        navs_path = self.data_dir / "navs.csv"
        if not navs_path.exists():
            return {}

        navs_by_code: dict[str, list[NavPoint]] = {}
        nav_key_lines: dict[tuple[str, str], int] = {}
        with navs_path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            self._validate_headers(navs_path, reader.fieldnames, NAV_FIELDS)
            for line_number, row in enumerate(reader, start=2):
                code = self._required(navs_path, line_number, row, "fund_code")
                trade_date = self._date(navs_path, line_number, row, "trade_date")
                nav_key = (code, trade_date)
                if nav_key in nav_key_lines:
                    raise ValueError(
                        f"{navs_path}:{line_number}: duplicate NAV key {code}/{trade_date}; "
                        f"first seen at line {nav_key_lines[nav_key]}"
                    )
                nav_key_lines[nav_key] = line_number
                navs_by_code.setdefault(code, []).append(
                    NavPoint(
                        trade_date=trade_date,
                        nav=self._positive_float(navs_path, line_number, row, "nav"),
                        accumulated_nav=self._positive_float(
                            navs_path, line_number, row, "accumulated_nav"
                        ),
                    )
                )
        for navs in navs_by_code.values():
            navs.sort(key=lambda item: item.trade_date)
        return navs_by_code

    @staticmethod
    def _validate_headers(
        path: Path,
        fieldnames: Sequence[str] | None,
        required_fields: set[str],
    ) -> None:
        actual_fields = set(fieldnames or [])
        missing = sorted(required_fields - actual_fields)
        if missing:
            raise ValueError(f"{path}: missing required CSV columns: {', '.join(missing)}")

    @staticmethod
    def _required(path: Path, line_number: int, row: dict[str, str | None], key: str) -> str:
        value = row.get(key)
        if value is None or value.strip() == "":
            raise ValueError(f"{path}:{line_number}: missing required CSV field: {key}")
        return value.strip()

    @classmethod
    def _fund_type(
        cls,
        path: Path,
        line_number: int,
        row: dict[str, str | None],
    ) -> FundType:
        value = cls._required(path, line_number, row, "fund_type")
        try:
            return FUND_TYPES_BY_VALUE[value]
        except KeyError as exc:
            supported = ", ".join(FUND_TYPES_BY_VALUE)
            raise ValueError(
                f"{path}:{line_number}: unsupported fund_type={value}; expected one of {supported}"
            ) from exc

    @classmethod
    def _risk_level(
        cls,
        path: Path,
        line_number: int,
        row: dict[str, str | None],
    ) -> RiskLevel:
        value = cls._required(path, line_number, row, "risk_level")
        try:
            return RISK_LEVELS_BY_VALUE[value]
        except KeyError as exc:
            supported = ", ".join(RISK_LEVELS_BY_VALUE)
            raise ValueError(
                f"{path}:{line_number}: unsupported risk_level={value}; expected one of {supported}"
            ) from exc

    @classmethod
    def _float(cls, path: Path, line_number: int, row: dict[str, str | None], key: str) -> float:
        value = cls._required(path, line_number, row, key)
        try:
            parsed = float(value)
        except ValueError as exc:
            raise ValueError(
                f"{path}:{line_number}: invalid numeric CSV field {key}={value}"
            ) from exc
        if not math.isfinite(parsed):
            raise ValueError(f"{path}:{line_number}: non-finite numeric CSV field {key}={value}")
        return parsed

    @classmethod
    def _range_float(
        cls,
        path: Path,
        line_number: int,
        row: dict[str, str | None],
        key: str,
        *,
        minimum: float,
        maximum: float | None = None,
    ) -> float:
        value = cls._float(path, line_number, row, key)
        if value < minimum or (maximum is not None and value > maximum):
            expected = f">= {minimum}" if maximum is None else f"between {minimum} and {maximum}"
            raise ValueError(
                f"{path}:{line_number}: numeric CSV field {key} must be {expected}; got {value}"
            )
        return value

    @classmethod
    def _positive_float(
        cls, path: Path, line_number: int, row: dict[str, str | None], key: str
    ) -> float:
        value = cls._float(path, line_number, row, key)
        if value <= 0:
            raise ValueError(
                f"{path}:{line_number}: numeric CSV field {key} must be > 0; got {value}"
            )
        return value

    @classmethod
    def _non_negative_integer(
        cls, path: Path, line_number: int, row: dict[str, str | None], key: str
    ) -> int:
        value = cls._float(path, line_number, row, key)
        if value < 0 or not value.is_integer():
            raise ValueError(
                f"{path}:{line_number}: numeric CSV field {key} must be a non-negative integer; got {value}"
            )
        return int(value)

    @classmethod
    def _date(cls, path: Path, line_number: int, row: dict[str, str | None], key: str) -> str:
        value = cls._required(path, line_number, row, key)
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{path}:{line_number}: invalid ISO date field {key}={value}") from exc
        return value

    @classmethod
    def _datetime(cls, path: Path, line_number: int, row: dict[str, str | None], key: str) -> str:
        value = cls._required(path, line_number, row, key)
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(
                f"{path}:{line_number}: invalid ISO datetime field {key}={value}"
            ) from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(
                f"{path}:{line_number}: ISO datetime field {key} must include a timezone offset; got {value}"
            )
        return value


def main() -> None:
    data_dir = sys.argv[1] if len(sys.argv) > 1 else None
    report = preflight_csv_local(data_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
