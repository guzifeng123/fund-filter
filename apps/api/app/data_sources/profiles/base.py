from typing import Any, Protocol


class PublicFundDataProfile(Protocol):
    """Normalize one public JSON format without performing transport or database work."""

    name: str
    source: str
    upstream_provider: str | None

    def normalize_fund(self, row: dict[str, Any]) -> dict[str, Any]: ...

    def normalize_nav(self, row: dict[str, Any]) -> dict[str, Any]: ...
