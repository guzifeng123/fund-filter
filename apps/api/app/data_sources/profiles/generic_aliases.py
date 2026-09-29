from typing import Any

from app.data_sources.profiles.normalized import NormalizedV1Profile


class GenericAliasesV1Profile(NormalizedV1Profile):
    """Backward-compatible aliases previously embedded in public_http_json."""

    name = "generic_aliases_v1"

    _fund_aliases = {
        "code": ("code", "fund_code", "fundCode", "jjdm", "FCODE"),
        "name": ("name", "fund_name", "fundName", "short_name", "SHORTNAME", "jjjc"),
        "fund_type": ("fund_type", "fundType", "type", "category", "fund_category"),
        "risk_level": ("risk_level", "riskLevel", "risk", "riskGrade"),
        "manager_name": (
            "manager_name",
            "managerName",
            "manager",
            "fund_manager",
            "FUNDMANAGER",
        ),
        "inception_date": (
            "inception_date",
            "inceptionDate",
            "establish_date",
            "establishDate",
            "FSRQ",
        ),
        "fund_size_billion": (
            "fund_size_billion",
            "fundSizeBillion",
            "size_billion",
            "scaleBillion",
            "ENDNAV",
        ),
        "management_fee": ("management_fee", "managementFee", "manage_fee", "manageFee"),
        "custody_fee": ("custody_fee", "custodyFee", "trustee_fee", "trusteeFee"),
        "annualized_return_3y": (
            "annualized_return_3y",
            "annualizedReturn3y",
            "return_3y",
            "syl_3n",
        ),
        "annualized_return_5y": (
            "annualized_return_5y",
            "annualizedReturn5y",
            "return_5y",
            "syl_5n",
        ),
        "max_drawdown": ("max_drawdown", "maxDrawdown", "mdd", "max_retracement"),
        "sharpe_ratio": ("sharpe_ratio", "sharpeRatio", "sharpe"),
        "category_rank_percentile": (
            "category_rank_percentile",
            "categoryRankPercentile",
            "rank_percentile",
        ),
        "manager_years": ("manager_years", "managerYears", "manager_tenure_years"),
        "data_updated_at": (
            "data_updated_at",
            "dataUpdatedAt",
            "updated_at",
            "updateTime",
            "jzrq",
        ),
    }
    _nav_aliases = {
        "trade_date": ("trade_date", "tradeDate", "date", "FSRQ", "jzrq"),
        "nav": ("nav", "unit_nav", "unitNav", "DWJZ", "dwjz"),
        "accumulated_nav": (
            "accumulated_nav",
            "accumulatedNav",
            "acc_nav",
            "LJJZ",
            "ljjz",
        ),
    }
    _fund_type_aliases = {
        "股票型": "stock",
        "stock": "stock",
        "混合型": "mixed",
        "mixed": "mixed",
        "债券型": "bond",
        "bond": "bond",
        "货币型": "money",
        "money": "money",
    }

    def normalize_fund(self, row: dict[str, Any]) -> dict[str, Any]:
        normalized = super().normalize_fund(row)
        for target, aliases in self._fund_aliases.items():
            value = self._first_value(row, aliases)
            if value is not None:
                normalized[target] = value
        if "fund_type" in normalized:
            normalized["fund_type"] = self._fund_type_aliases.get(
                str(normalized["fund_type"]),
                normalized["fund_type"],
            )
        return normalized

    def normalize_nav(self, row: dict[str, Any]) -> dict[str, Any]:
        normalized = super().normalize_nav(row)
        for target, aliases in self._nav_aliases.items():
            value = self._first_value(row, aliases)
            if value is not None:
                normalized[target] = value
        return normalized

    @staticmethod
    def _first_value(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
        for key in keys:
            value = row.get(key)
            if value is not None and value != "":
                return value
        return None
