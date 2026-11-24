from .constants import SQRT3, VOLTAGE_1PH, VOLTAGE_3PH


def design_current(power_w: float, cos_phi: float, three_phase: bool) -> float:
    """Design current Ib, A. 1ph: P/(U*cos); 3ph: P/(sqrt3*U*cos)."""
    if power_w <= 0:
        raise ValueError("power_w must be > 0")
    if not 0.1 <= cos_phi <= 1.0:
        raise ValueError("cos_phi must be within [0.1, 1.0]")
    if three_phase:
        return power_w / (SQRT3 * VOLTAGE_3PH * cos_phi)
    return power_w / (VOLTAGE_1PH * cos_phi)
