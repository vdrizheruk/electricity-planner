from .constants import (
    CABLE_SIZES,
    EPS,
    IZ_2_LOADED,
    IZ_3_LOADED,
    MIN_CABLE_MM2,
    RHO_CU,
    SQRT3,
    VOLTAGE_1PH,
    VOLTAGE_3PH,
)


class CableSelectionError(ValueError):
    """No supported cross-section satisfies current / voltage-drop limits."""


def ampacity(section_mm2: float, three_phase: bool, derating: float = 1.0) -> float:
    table = IZ_3_LOADED if three_phase else IZ_2_LOADED
    return table[section_mm2] * derating


def voltage_drop_pct(
    ib_a: float, length_m: float, section_mm2: float, cos_phi: float, three_phase: bool
) -> float:
    """Voltage drop, % of nominal. Resistive model, one-way length ``length_m``.

    1ph: 2*rho*L*I*cos / (S*230); 3ph: sqrt3*rho*L*I*cos / (S*400).
    """
    if length_m < 0 or section_mm2 <= 0:
        raise ValueError("invalid length or section")
    if three_phase:
        return SQRT3 * RHO_CU * length_m * ib_a * cos_phi / (section_mm2 * VOLTAGE_3PH) * 100
    return 2 * RHO_CU * length_m * ib_a * cos_phi / (section_mm2 * VOLTAGE_1PH) * 100


def select_cable(
    *,
    group_type: str,
    breaker_a: int,
    ib_a: float,
    length_m: float,
    cos_phi: float,
    three_phase: bool,
    dv_limit_pct: float,
    derating: float = 1.0,
) -> tuple[float, float]:
    """Smallest standard Cu section with Iz >= In and dU <= limit.

    Returns (section_mm2, voltage_drop_pct).
    """
    minimum = MIN_CABLE_MM2.get(group_type, 2.5)
    for s in CABLE_SIZES:
        if s < minimum:
            continue
        if ampacity(s, three_phase, derating) + EPS < breaker_a:
            continue
        dv = voltage_drop_pct(ib_a, length_m, s, cos_phi, three_phase)
        if dv <= dv_limit_pct + EPS:
            return s, dv
    raise CableSelectionError(
        f"no cable up to {CABLE_SIZES[-1]} mm² fits In={breaker_a} A, L={length_m} m, "
        f"dU<={dv_limit_pct}%"
    )
