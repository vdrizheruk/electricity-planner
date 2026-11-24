"""RCD / RCBO selection and grouping."""

from collections.abc import Sequence
from dataclasses import dataclass

from .breaker import next_standard
from .constants import INDIVIDUAL_RCBO_TYPES, RCD_SERIES
from .models import Protection


@dataclass(frozen=True)
class ProtectionChoice:
    protection: Protection
    rcd_ma: int | None
    rcd_type: str


def choose_protection(group_type: str, power_w: float, wet_zone: bool) -> ProtectionChoice:
    """30 mA everywhere except dry lighting; dedicated high-power lines get an RCBO."""
    if group_type == "lighting":
        if wet_zone:
            return ProtectionChoice("rcd", 30, "A")
        return ProtectionChoice("mcb", None, "")
    if group_type in INDIVIDUAL_RCBO_TYPES or power_w >= 3500:
        return ProtectionChoice("rcbo", 30, "A")
    return ProtectionChoice("rcd", 30, "A")


@dataclass(frozen=True)
class RcdCandidate:
    """Group needing a shared RCD: ``demand_a`` includes Kc, ``in_a`` is its breaker."""

    id: int
    demand_a: float
    in_a: int


@dataclass(frozen=True)
class RcdBin:
    group_ids: tuple[int, ...]
    demand_a: float
    rating_a: int


def pack_rcds(candidates: Sequence[RcdCandidate], max_groups: int) -> list[RcdBin]:
    """First-fit-decreasing packing under RCDs.

    Constraints per RCD: at most ``max_groups`` groups; sum of demand currents within
    the largest standard rating; rating >= the largest member breaker and >= demand.
    """
    if max_groups < 1:
        raise ValueError("max_groups must be >= 1")
    capacity = float(RCD_SERIES[-1])
    bins: list[list[RcdCandidate]] = []
    for c in sorted(candidates, key=lambda x: (-x.demand_a, x.id)):
        if c.demand_a > capacity or c.in_a > capacity:
            raise ValueError(f"group {c.id} exceeds the largest RCD rating {RCD_SERIES[-1]} A")
        for b in bins:
            if len(b) < max_groups and sum(x.demand_a for x in b) + c.demand_a <= capacity:
                b.append(c)
                break
        else:
            bins.append([c])
    result: list[RcdBin] = []
    for b in bins:
        demand = sum(x.demand_a for x in b)
        rating = next_standard(max(demand, max(x.in_a for x in b)), RCD_SERIES)
        result.append(RcdBin(tuple(sorted(x.id for x in b)), demand, rating))
    return sorted(result, key=lambda r: r.group_ids)
