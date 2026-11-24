from .constants import BREAKER_SERIES, CURVE, EPS, MIN_BREAKER_A, MIN_BREAKER_DEFAULT_A


class NoStandardSizeError(ValueError):
    """Requested current exceeds the largest supported rating."""


def next_standard(value: float, series: tuple[int, ...] = BREAKER_SERIES) -> int:
    """Smallest standard rating >= value."""
    for n in series:
        if n + EPS >= value:
            return n
    raise NoStandardSizeError(f"{value:.1f} A exceeds the largest rating {series[-1]} A")


def select_breaker(ib_a: float, group_type: str = "other") -> int:
    """Smallest standard In with Ib <= In, not below the practical minimum for the type."""
    minimum = MIN_BREAKER_A.get(group_type, MIN_BREAKER_DEFAULT_A)
    return max(next_standard(ib_a), minimum)


def select_curve(group_type: str) -> str:
    return CURVE.get(group_type, "C")
