from typing import Any


class NormalizedV1Profile:
    """Strict profile for payloads already using the internal FundDetail/NavPoint names."""

    name = "normalized_v1"
    source = "public_http_json"
    upstream_provider: str | None = None

    def normalize_fund(self, row: dict[str, Any]) -> dict[str, Any]:
        return dict(row)

    def normalize_nav(self, row: dict[str, Any]) -> dict[str, Any]:
        return dict(row)
