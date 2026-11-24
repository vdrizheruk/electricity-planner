"""Plain data types of the calculation layer (no Django imports allowed here)."""

from dataclasses import dataclass, field
from typing import Literal

Grid = Literal["1ph", "3ph"]
Level = Literal["error", "warning", "info"]
Protection = Literal["mcb", "rcd", "rcbo"]


@dataclass(frozen=True)
class SystemInput:
    """Project-wide parameters."""

    grid: Grid = "1ph"
    main_breaker_a: int = 32
    earthing: str = "TN-C-S"
    dv_limit_lighting_pct: float = 3.0
    dv_limit_other_pct: float = 5.0
    # Correction factor for temperature / grouping, applied to cable ampacity.
    derating: float = 1.0
    max_groups_per_rcd: int = 4


@dataclass(frozen=True)
class GroupInput:
    id: int
    name: str
    type: str  # GroupType value, e.g. "sockets"
    power_w: float
    cos_phi: float = 1.0
    phase: str = "auto"  # auto | L1 | L2 | L3 | 3ph
    length_m: float = 20.0
    backed_up: bool = False
    wet_zone: bool = False


@dataclass(frozen=True)
class Finding:
    level: Level
    code: str
    message: str
    group_id: int | None = None


@dataclass(frozen=True)
class GroupResult:
    group_id: int
    phase: str  # assigned phase: L1/L2/L3 or 3ph
    ib_a: float
    breaker_a: int
    curve: str
    cable_mm2: float
    voltage_drop_pct: float
    protection: Protection
    rcd_ma: int | None
    rcd_type: str
    demand_factor: float
    demand_va: float


@dataclass(frozen=True)
class RcdAssignment:
    """One shared RCD (or an individual RCBO) and the groups behind it."""

    id: int
    phase: str
    poles: int
    rating_a: int
    leakage_ma: int
    rcd_type: str
    group_ids: tuple[int, ...]
    backed_up: bool
    demand_a: float


@dataclass(frozen=True)
class PhaseBalance:
    loads_va: dict[str, float]
    imbalance_pct: float
    exceeds_limit: bool
    assignment: dict[int, str]


@dataclass(frozen=True)
class DemandSummary:
    installed_w: float
    demand_w: float
    demand_va: float
    diversity: float  # Ko
    design_current_a: float  # most loaded phase (1ph grid: the only phase)
    main_breaker_a: int
    main_ok: bool


@dataclass(frozen=True)
class ProjectCalculation:
    groups: list[GroupResult]
    rcds: list[RcdAssignment]
    demand: DemandSummary
    phases: PhaseBalance
    findings: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(f.level == "error" for f in self.findings)
