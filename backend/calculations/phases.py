"""Phase balancing for 3-phase supplies."""

from collections.abc import Sequence
from dataclasses import dataclass

from .constants import EPS, IMBALANCE_LIMIT_PCT, PHASES_1PH, PHASES_3PH
from .models import Grid, PhaseBalance


@dataclass(frozen=True)
class PhaseLoad:
    """Load for balancing: ``phase`` is auto | L1 | L2 | L3 | 3ph; ``va`` includes Kc."""

    id: int
    phase: str
    va: float


def imbalance_pct(loads: Sequence[float]) -> float:
    """(Pmax - Pavg) / Pavg * 100. 0 if the system is unloaded."""
    if not loads:
        return 0.0
    avg = sum(loads) / len(loads)
    if avg <= 0:
        return 0.0
    return (max(loads) - avg) / avg * 100


def balance(grid: Grid, loads: Sequence[PhaseLoad]) -> PhaseBalance:
    phases = PHASES_3PH if grid == "3ph" else PHASES_1PH
    totals = {p: 0.0 for p in phases}
    assignment: dict[int, str] = {}

    for ld in loads:
        if ld.phase == "3ph":
            if grid != "3ph":
                raise ValueError(f"group {ld.id}: 3-phase load on a 1-phase supply")
            assignment[ld.id] = "3ph"
            for p in phases:
                totals[p] += ld.va / 3
        elif ld.phase in phases:
            assignment[ld.id] = ld.phase
            totals[ld.phase] += ld.va
        elif ld.phase == "auto":
            continue
        else:
            raise ValueError(f"group {ld.id}: phase {ld.phase!r} not available on {grid} supply")

    # Greedy LPT: biggest first into the least loaded phase (stable tie-break L1<L2<L3).
    auto = sorted((ld for ld in loads if ld.phase == "auto"), key=lambda x: (-x.va, x.id))
    for ld in auto:
        target = min(phases, key=lambda p: (totals[p], p))
        assignment[ld.id] = target
        totals[target] += ld.va

    _improve(auto, assignment, totals)

    pct = imbalance_pct(list(totals.values())) if grid == "3ph" else 0.0
    return PhaseBalance(
        loads_va=totals,
        imbalance_pct=pct,
        exceeds_limit=pct > IMBALANCE_LIMIT_PCT + EPS,
        assignment=assignment,
    )


def _improve(
    auto: Sequence[PhaseLoad], assignment: dict[int, str], totals: dict[str, float]
) -> None:
    """Local search: move a single auto load to another phase while it lowers Pmax."""
    if len(totals) < 2:
        return
    for _ in range(len(auto) * len(totals) + 1):
        worst = max(totals, key=lambda p: (totals[p], p))
        best_move: tuple[float, PhaseLoad, str] | None = None
        for ld in auto:
            if assignment[ld.id] != worst:
                continue
            for p in totals:
                if p == worst:
                    continue
                new_max = max(totals[worst] - ld.va, totals[p] + ld.va)
                if new_max < totals[worst] - 1e-9 and (best_move is None or new_max < best_move[0]):
                    best_move = (new_max, ld, p)
        if best_move is None:
            return
        _, ld, p = best_move
        totals[worst] -= ld.va
        totals[p] += ld.va
        assignment[ld.id] = p
