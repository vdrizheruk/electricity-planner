"""Plain data types of the backup-power layer (no Django imports allowed here)."""

from dataclasses import dataclass, field
from typing import Literal

Grid = Literal["1ph", "3ph"]
Level = Literal["error", "warning", "info"]
Scenario = Literal[
    "grid_gen_ats",  # grid + generator through an ATS
    "grid_inverter",  # grid + inverter/UPS with battery
    "grid_inverter_gen",  # grid + inverter + generator (priorities)
    "manual_i0ii",  # manual changeover switch I-0-II
    "grid3_gen1_phase",  # 3-ph grid + 1-ph generator feeding ONE phase
    "grid3_gen1_combine",  # 3-ph grid + 1-ph generator tying the phases on the backup bus
    "grid1_gen1",  # 1-ph grid + 1-ph generator
]
AtsKind = Literal["none", "contactor", "modular", "manual"]
InverterKind = Literal["hybrid", "off-grid", "on-grid"]
InverterMode = Literal["single", "parallel", "phase_set"]
Chemistry = Literal["LiFePO4", "AGM"]
PhaseName = Literal["L1", "L2", "L3"]
Role = Literal[
    "grid_in_breaker",
    "gen_in_breaker",
    "ats",
    "spd",
    "inv_in_breaker",
    "inv_out_breaker",
    "rcd_inv_out",
    "battery_dc_breaker",
    "backup_out_breaker",
]

SCENARIOS: tuple[Scenario, ...] = (
    "grid_gen_ats",
    "grid_inverter",
    "grid_inverter_gen",
    "manual_i0ii",
    "grid3_gen1_phase",
    "grid3_gen1_combine",
    "grid1_gen1",
)


@dataclass(frozen=True)
class GeneratorSpec:
    kva: float
    kw: float
    phases: int = 1
    cos_phi: float = 0.8
    autostart: bool = True


@dataclass(frozen=True)
class InverterSpec:
    kind: InverterKind = "hybrid"
    phases: int = 1
    p_ac_w: float = 5000.0
    p_surge_w: float = 0.0  # 0: unknown, 1.5 x p_ac assumed
    bypass_a: float = 0.0  # 0: no bypass
    batt_v: float = 48.0
    count: int = 1
    mode: InverterMode = "single"
    # Inverter ties N to PE on its output in off-grid mode.
    bonds_n_pe_offgrid: bool = True
    transformerless: bool = True


@dataclass(frozen=True)
class BatterySpec:
    kwh: float
    voltage_v: float = 48.0
    chemistry: Chemistry = "LiFePO4"
    dod: float = 0.0  # 0: default for the chemistry
    max_discharge_a: float = 0.0  # per battery; 0: unknown
    count: int = 1


@dataclass(frozen=True)
class AtsSpec:
    kind: AtsKind = "none"
    poles: int = 2
    rated_a: float = 0.0
    mechanical_interlock: bool = False
    electrical_interlock: bool = False


@dataclass(frozen=True)
class LoadInput:
    id: int
    name: str
    type: str
    power_w: float
    cos_phi: float = 1.0
    phase: str = "L1"  # assigned phase: L1/L2/L3/3ph
    backed_up: bool = False


@dataclass(frozen=True)
class PowerInput:
    grid: Grid
    earthing: str
    scenario: Scenario
    loads: tuple[LoadInput, ...] = ()
    generator: GeneratorSpec | None = None
    inverter: InverterSpec | None = None
    battery: BatterySpec | None = None
    ats: AtsSpec = field(default_factory=AtsSpec)
    # Phase fed by a single-phase generator in scenario ``grid3_gen1_phase``.
    backup_phase: PhaseName = "L1"
    autonomy_target_h: float = 4.0
    # Source priorities for ``grid_inverter_gen`` (highest first).
    priority: tuple[str, ...] = ("grid", "inverter", "generator")


@dataclass(frozen=True)
class Finding:
    level: Level
    code: str
    message: str


@dataclass(frozen=True)
class Component:
    """A device the scenario needs; the Django layer maps it to a catalog product."""

    role: Role
    kind: str  # catalog family: mcb | contactor | ats | spd | rcd | dc_breaker
    poles: int
    rated_a: float
    note: str = ""
    qty: int = 1


@dataclass(frozen=True)
class Metrics:
    p_backup_w: float  # sum of P*Kc of backed-up groups
    s_backup_va: float
    p_start_w: float  # with the largest motor starting
    s_start_va: float
    phase_va: dict[str, float]  # L1/L2/L3 apparent power of the backup load
    i_backup_a: float  # current of the most loaded phase
    imbalance_pct: float
    gen_required_kva: float | None = None
    gen_required_kw: float | None = None
    inverter_capacity_w: float | None = None
    inverter_required_w: float | None = None
    autonomy_h: float | None = None
    battery_dc_a: float | None = None
    battery_usable_kwh: float | None = None


@dataclass(frozen=True)
class PowerResult:
    ok: bool
    metrics: Metrics
    findings: tuple[Finding, ...]
    components: tuple[Component, ...]
    description: str = ""
