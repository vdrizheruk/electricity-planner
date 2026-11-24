from .constants import BREAKER_SELECTIVITY_RATIO, RCD_SELECTIVITY_RATIO


def breaker_selectivity_ok(upstream_a: float, downstream_a: float) -> bool:
    """Ratings-based selectivity: upstream In >= 1.6 * downstream In."""
    return upstream_a + 1e-9 >= BREAKER_SELECTIVITY_RATIO * downstream_a


def rcd_selectivity_ok(upstream_ma: int, upstream_selective: bool, downstream_ma: int) -> bool:
    """Upstream RCD must be selective (type S) and IΔn >= 3 * downstream IΔn."""
    return upstream_selective and upstream_ma >= RCD_SELECTIVITY_RATIO * downstream_ma
