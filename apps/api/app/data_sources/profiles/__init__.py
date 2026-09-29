from collections.abc import Callable

from app.data_sources.profiles.base import PublicFundDataProfile
from app.data_sources.profiles.eastmoney_snapshot import EastmoneySnapshotV1Profile
from app.data_sources.profiles.generic_aliases import GenericAliasesV1Profile
from app.data_sources.profiles.normalized import NormalizedV1Profile

_PROFILE_FACTORIES: dict[str, Callable[[], PublicFundDataProfile]] = {
    GenericAliasesV1Profile.name: lambda: GenericAliasesV1Profile(),
    NormalizedV1Profile.name: lambda: NormalizedV1Profile(),
    EastmoneySnapshotV1Profile.name: lambda: EastmoneySnapshotV1Profile(),
}


def available_public_fund_data_profiles() -> tuple[str, ...]:
    return tuple(sorted(_PROFILE_FACTORIES))


def get_public_fund_data_profile(name: str) -> PublicFundDataProfile:
    profile_name = name.strip()
    factory = _PROFILE_FACTORIES.get(profile_name)
    if factory is None:
        supported = ", ".join(available_public_fund_data_profiles())
        raise ValueError(
            f"unknown PUBLIC_FUND_DATA_PROFILE {profile_name!r}; supported profiles: {supported}"
        )
    return factory()


__all__ = [
    "PublicFundDataProfile",
    "available_public_fund_data_profiles",
    "get_public_fund_data_profile",
]
