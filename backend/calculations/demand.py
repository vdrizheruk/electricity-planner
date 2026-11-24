from collections.abc import Sequence

from .constants import (
    KC,
    KC_DEFAULT,
    KO_FACTOR,
    KO_THRESHOLD_GROUPS,
    VOLTAGE_1PH,
)
from .models import DemandSummary, SystemInput


def demand_factor(group_type: str) -> float:
    return KC.get(group_type, KC_DEFAULT)


def diversity_factor(n_groups: int) -> float:
    """Ko: 0.9 when the project has more than 5 groups, else 1.0."""
    return KO_FACTOR if n_groups > KO_THRESHOLD_GROUPS else 1.0


def summarize(
    system: SystemInput,
    powers_w: Sequence[float],
    demand_va: Sequence[float],
    demand_w: Sequence[float],
    phase_loads_va: dict[str, float],
) -> DemandSummary:
    """Project-level demand. ``demand_*`` are already multiplied by Kc (not Ko)."""
    ko = diversity_factor(len(powers_w))
    total_va = sum(demand_va) * ko
    total_w = sum(demand_w) * ko
    if system.grid == "3ph":
        worst_phase_va = max(phase_loads_va.values(), default=0.0) * ko
    else:
        worst_phase_va = total_va
    design_current = worst_phase_va / VOLTAGE_1PH
    return DemandSummary(
        installed_w=float(sum(powers_w)),
        demand_w=total_w,
        demand_va=total_va,
        diversity=ko,
        design_current_a=design_current,
        main_breaker_a=system.main_breaker_a,
        main_ok=design_current <= system.main_breaker_a + 1e-9,
    )
