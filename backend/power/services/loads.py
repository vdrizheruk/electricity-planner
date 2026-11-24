"""Backup load: demand with Kc, starting power and per-phase split."""

from collections.abc import Sequence

from calculations.constants import KC, KC_DEFAULT, VOLTAGE_1PH

from .models import LoadInput

PHASES = ("L1", "L2", "L3")

# Starting current multiplier by group type (motor loads); everything else starts at 1x.
START_FACTOR: dict[str, float] = {
    "ac": 3.0,
    "washer": 2.0,
    "dishwasher": 2.0,
    "kitchen": 1.5,
}


def kc_of(load: LoadInput) -> float:
    return KC.get(load.type, KC_DEFAULT)


def start_factor(load: LoadInput) -> float:
    return START_FACTOR.get(load.type, 1.0)


def backed_up(loads: Sequence[LoadInput]) -> list[LoadInput]:
    return [x for x in loads if x.backed_up]


def apparent_va(load: LoadInput) -> float:
    cos = load.cos_phi if load.cos_phi > 0 else 1.0
    return load.power_w / cos


def split_phases(load: LoadInput, grid: str) -> dict[str, float]:
    """Apparent power of the group (before Kc) per phase."""
    s = apparent_va(load)
    if grid == "1ph":
        return {"L1": s, "L2": 0.0, "L3": 0.0}
    if load.phase == "3ph":
        return {p: s / 3 for p in PHASES}
    phase = load.phase if load.phase in PHASES else "L1"
    return {p: (s if p == phase else 0.0) for p in PHASES}


def demand(loads: Sequence[LoadInput], grid: str) -> tuple[float, float, dict[str, float]]:
    """(P_w, S_va, per-phase S_va) of the backed-up loads, Kc applied."""
    p = 0.0
    s = 0.0
    per_phase = {ph: 0.0 for ph in PHASES}
    for x in backed_up(loads):
        k = kc_of(x)
        p += x.power_w * k
        s += apparent_va(x) * k
        for ph, v in split_phases(x, grid).items():
            per_phase[ph] += v * k
    return p, s, per_phase


def starting(loads: Sequence[LoadInput], grid: str) -> tuple[float, float]:
    """(P_w, S_va) while the worst single motor starts and everything else runs at demand."""
    p0, s0, _ = demand(loads, grid)
    best_p, best_s = p0, s0
    for x in backed_up(loads):
        k = kc_of(x)
        f = start_factor(x)
        best_p = max(best_p, p0 + x.power_w * (f - k))
        best_s = max(best_s, s0 + apparent_va(x) * (f - k))
    return best_p, best_s


def phase_current_a(per_phase_va: dict[str, float]) -> float:
    return max(per_phase_va.values(), default=0.0) / VOLTAGE_1PH


def next_rating(current_a: float, series: Sequence[int]) -> int:
    """Smallest standard rating >= current_a (last element when none is large enough)."""
    for n in series:
        if n >= current_a - 1e-9:
            return n
    return series[-1]
