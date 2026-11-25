"""Power-flow simulation: which sources are on, what feeds each group, how loaded they are.

Pure Python (no Django). The simulation is *static*: for given switch positions it decides which
source feeds the backup bus, which groups are energised and whether a source or the main breaker
trips on overload. Loads use the same demand (P·Kc) as the backup design checks.

Rules
-----
* Groups that are not ``backed_up`` hang on the grid only.
* ATS scenarios: automatic mode takes the grid, otherwise the generator; a forced position
  (I / II / 0) overrides it. Generator and grid together without a safe changeover is a fault.
* Inverter scenario: with the grid on the loads are fed through the inverter (charger/bypass);
  without it the inverter feeds them from the battery or, for a hybrid unit, from PV.
* A one-phase source (generator in ``grid3_gen1_phase``, one-phase inverter) energises only
  the groups on its phase; three-phase groups stay dark.
* Overload of a source (kVA/kW, per phase for three-phase) or of the main breaker de-energises
  what it feeds.
* A grid-tied inverter stops with the grid (anti-islanding): PV then gives nothing to the backup.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from calculations.constants import EPS, SQRT3, VOLTAGE_1PH, VOLTAGE_3PH

from .checks import INVERTER_EFF, battery_usable_kwh, phase_imbalance
from .loads import PHASES, apparent_va, kc_of, split_phases
from .models import Finding, GeneratorSpec, InverterSpec, LoadInput, PowerInput
from .plan import WITH_GENERATOR, WITH_INVERTER

Source = Literal["grid", "generator", "inverter"]
Position = Literal["auto", "grid", "gen", "off"]
SourceRole = Literal["feeding", "standby", "off", "fault"]
GROUP_DARK_REASONS = (
    "not_backed_up",
    "no_source",
    "position",
    "phase",
    "overload",
    "fault",
    "tripped",
)

GENERATOR_START_S = 15.0  # autostart generator: start + stabilisation
ATS_SWITCH_S = {"contactor": 0.5, "modular": 0.15, "manual": None, "none": None}
INVERTER_SWITCH_S = 0.02  # UPS-class changeover of an inverter/hybrid


@dataclass(frozen=True)
class Switches:
    grid: bool = True
    generator: bool = False
    inverter: bool = True
    pv: bool = False
    position: Position = "auto"  # ATS / I-0-II selector
    pv_pct: float = 70.0  # irradiance, % of the peak PV power


@dataclass(frozen=True)
class SimInput:
    power: PowerInput
    switches: Switches = field(default_factory=Switches)
    main_breaker_a: float = 63.0
    pv_kwp: float = 0.0
    # PV is connected to the same hybrid inverter as the backup (it keeps working off-grid).
    pv_on_backup_inverter: bool = False


@dataclass(frozen=True)
class GroupState:
    id: int
    name: str
    backed_up: bool
    powered: bool
    source: Source | None
    reason: str  # "" while powered, else one of GROUP_DARK_REASONS
    phase: str
    power_w: float


@dataclass(frozen=True)
class SourceState:
    name: str  # grid | generator | inverter | pv
    on: bool
    role: SourceRole
    load_w: float
    load_va: float
    current_a: float  # most loaded phase
    rating_va: float | None
    utilization_pct: float | None
    note: str = ""


@dataclass(frozen=True)
class SimResult:
    backup_source: Source | None
    main_source: Source | None
    ats_state: str  # grid | generator | inverter | open
    groups: tuple[GroupState, ...]
    sources: tuple[SourceState, ...]
    findings: tuple[Finding, ...]
    interruption_s: float | None  # supply gap of the backed-up groups after the grid is lost
    pv_w: float = 0.0
    grid_import_w: float = 0.0
    grid_export_w: float = 0.0
    battery_net_w: float = 0.0  # >0 discharging, <0 charging (not modelled: 0)
    autonomy_h: float | None = None
    powered_w: float = 0.0
    dark_w: float = 0.0


# ------------------------------------------------------------------------ helpers
def _va_per_phase(loads: Sequence[LoadInput], grid: str) -> dict[str, float]:
    out = {p: 0.0 for p in PHASES}
    for x in loads:
        k = kc_of(x)
        for ph, v in split_phases(x, grid).items():
            out[ph] += v * k
    return out


def _p_w(loads: Sequence[LoadInput]) -> float:
    return sum(x.power_w * kc_of(x) for x in loads)


def _s_va(loads: Sequence[LoadInput]) -> float:
    return sum(apparent_va(x) * kc_of(x) for x in loads)


def _i_max_a(per_phase_va: dict[str, float]) -> float:
    return max(per_phase_va.values(), default=0.0) / VOLTAGE_1PH


def _gen_limit_va(g: GeneratorSpec) -> float:
    return g.kva * 1000.0


def _inv_capacity_w(i: InverterSpec) -> float:
    return i.p_ac_w * max(i.count, 1)


def _inverter_three_phase(i: InverterSpec) -> bool:
    return i.phases == 3 or i.mode == "phase_set"


def _powerable(
    loads: Sequence[LoadInput], source: Source, inp: SimInput
) -> tuple[list[LoadInput], list[LoadInput]]:
    """Split loads into (can be fed, cannot be fed because of the source's phases)."""
    pw = inp.power
    if pw.grid == "1ph":
        return list(loads), []
    one_phase_gen = source == "generator" and pw.generator is not None and pw.generator.phases == 1
    one_phase_inv = (
        source == "inverter" and pw.inverter is not None and not _inverter_three_phase(pw.inverter)
    )
    if not (one_phase_gen or one_phase_inv):
        return list(loads), []
    if pw.scenario == "grid3_gen1_combine" and one_phase_gen:
        ok = [x for x in loads if x.phase != "3ph"]
    else:
        ok = [x for x in loads if x.phase == pw.backup_phase]
    return ok, [x for x in loads if x not in ok]


def _transfer_time(inp: SimInput, source: Source | None) -> float | None:
    pw = inp.power
    ats = ATS_SWITCH_S.get(pw.ats.kind)
    if source is None or source == "grid":
        return None
    if source == "inverter":
        return INVERTER_SWITCH_S
    gen = pw.generator
    if gen is None or not gen.autostart or ats is None:
        return None  # manual start / manual switching: depends on the operator
    return GENERATOR_START_S + ats


# ------------------------------------------------------------------ source choice
def _inverter_can_supply(inp: SimInput, load_w: float, pv_w: float) -> tuple[bool, str]:
    pw = inp.power
    if pw.inverter is None:
        return False, "Инвертор не выбран"
    if pw.inverter.kind == "on-grid":
        return False, "Сетевой инвертор не работает без сети (защита от островного режима)"
    if pw.battery is not None and battery_usable_kwh(pw.battery) > EPS:
        return True, ""
    if inp.pv_on_backup_inverter and pv_w >= load_w > 0:
        return True, ""
    return False, "Нет АКБ (и PV не покрывает нагрузку): инвертору нечем питать шину"


def _choose_backup_source(
    inp: SimInput, load_w: float, pv_w: float, fs: list[Finding]
) -> tuple[Source | None, str]:
    """Returns (source of the backup bus, ATS state label)."""
    pw, sw = inp.power, inp.switches
    sc = pw.scenario

    if sc in WITH_INVERTER:
        inv = pw.inverter
        if sc == "grid_inverter":
            order: tuple[str, ...] = ("grid", "inverter")
        else:
            order = tuple(x for x in pw.priority if x in ("grid", "inverter", "generator"))
        if inv is not None and not sw.inverter:
            # Inverter switched off: only a bypass can pass the grid or the generator through.
            if inv.bypass_a > 0 and sw.grid:
                return "grid", "grid"
            if inv.bypass_a > 0 and sc == "grid_inverter_gen" and sw.generator:
                return "generator", "generator"
            fs.append(
                Finding(
                    "warning", "INVERTER_OFF", "Инвертор выключен и байпаса нет: шина обесточена"
                )
            )
            return None, "open"
        for name in order:
            if name == "grid" and sw.grid:
                return "grid", "grid"
            if name == "generator" and sw.generator and pw.generator is not None:
                return "generator", "generator"
            if name == "inverter":
                ok, why = _inverter_can_supply(inp, load_w, pv_w)
                if ok and sw.inverter:
                    return "inverter", "inverter"
                if sw.inverter and not sw.grid and why:
                    fs.append(Finding("warning", "INVERTER_CANNOT_SUPPLY", why))
        return None, "open"

    # changeover scenarios: ATS / I-0-II between the grid and the generator
    ats = pw.ats
    gen_on = sw.generator and pw.generator is not None
    manual = sc == "manual_i0ii" or ats.kind == "manual"
    position: Position = sw.position
    if position == "auto" and manual:
        fs.append(
            Finding(
                "info",
                "MANUAL_POSITION",
                "Ручной переключатель: выберите положение I, 0 или II "
                "(в авто-режиме шина обесточена)",
            )
        )
        position = "off"
    unsafe = ats.kind == "none" or (
        ats.kind == "contactor" and not (ats.mechanical_interlock and ats.electrical_interlock)
    )
    if sw.grid and gen_on and position == "auto" and unsafe:
        fs.append(
            Finding(
                "error",
                "BACKFEED_HAZARD",
                "Сеть и генератор включены без надёжной блокировки АВР: параллельная работа "
                "и обратная трансформация, защита отключает шину",
            )
        )
        return None, "fault"
    if position == "grid":
        return ("grid", "grid") if sw.grid else (None, "grid")
    if position == "gen":
        return ("generator", "generator") if gen_on else (None, "generator")
    if position == "off":
        return None, "open"
    if sw.grid:
        return "grid", "grid"
    if gen_on:
        return "generator", "generator"
    return None, "open"


# ----------------------------------------------------------------- main entry point
def simulate(inp: SimInput) -> SimResult:
    pw, sw = inp.power, inp.switches
    fs: list[Finding] = []
    backed = [x for x in pw.loads if x.backed_up]
    other = [x for x in pw.loads if not x.backed_up]
    sc = pw.scenario
    pv_w = inp.pv_kwp * 1000.0 * max(min(sw.pv_pct, 100.0), 0.0) / 100.0 if sw.pv else 0.0

    state: dict[int, tuple[Source | None, str]] = {}  # group id -> (source, dark reason)

    # --- the main (non-backed) side: grid only
    grid_loads: list[LoadInput] = []
    if sw.grid:
        grid_loads.extend(other)

    # --- the backup side
    full_backup_w = _p_w(backed)
    src, ats_state = _choose_backup_source(inp, full_backup_w, pv_w, fs)
    if src is None and backed:
        reason = "position" if ats_state in ("grid", "generator") else "no_source"
        if ats_state == "fault":
            reason = "fault"
        for x in backed:
            state[x.id] = (None, reason)
    feed: list[LoadInput] = []
    if src is not None:
        feed, cannot = _powerable(backed, src, inp)
        for x in cannot:
            state[x.id] = (None, "phase")
        if cannot:
            where = (
                "одну фазу " + pw.backup_phase
                if sc != "grid3_gen1_combine"
                else "однофазные группы"
            )
            fs.append(
                Finding(
                    "warning",
                    "PHASE_DARK",
                    f"Источник «{src}» питает только {where}: без питания "
                    + ", ".join(x.name for x in cannot),
                )
            )
        for x in feed:
            state[x.id] = (src, "")

    # --- trips
    gen_load = feed if src == "generator" else []
    inv_load = feed if src == "inverter" else []
    through_inv_pass = feed if (src in ("grid", "generator") and sc in WITH_INVERTER) else []
    grid_via_backup = feed if src == "grid" else []
    grid_loads.extend(grid_via_backup)

    gen_fault = False
    gen = pw.generator
    if gen_load and gen is not None:
        s_va = _s_va(gen_load)
        per_phase = _va_per_phase(gen_load, pw.grid)
        limit_phase = _gen_limit_va(gen) / 3 if gen.phases == 3 else _gen_limit_va(gen)
        worst = max(per_phase.values()) if gen.phases == 3 else s_va
        if worst > limit_phase + EPS or _p_w(gen_load) > gen.kw * 1000.0 + EPS:
            gen_fault = True
            fs.append(
                Finding(
                    "error",
                    "GEN_OVERLOAD",
                    f"Перегрузка генератора: {s_va / 1000:.1f} кВА / {_p_w(gen_load) / 1000:.1f} "
                    f"кВт при номинале {gen.kva:g} кВА / {gen.kw:g} кВт: генератор отключается",
                )
            )
    inv_fault = False
    inv = pw.inverter
    if inv_load and inv is not None:
        cap = _inv_capacity_w(inv)
        per_phase = _va_per_phase(inv_load, pw.grid)
        phase_cap = cap / 3 if _inverter_three_phase(inv) and pw.grid == "3ph" else cap
        worst = max(per_phase.values()) if pw.grid == "3ph" else _s_va(inv_load)
        if _p_w(inv_load) > cap + EPS or worst > phase_cap + EPS:
            inv_fault = True
            fs.append(
                Finding(
                    "error",
                    "INVERTER_OVERLOAD",
                    f"Перегрузка инвертора: {_s_va(inv_load) / 1000:.1f} кВА при мощности "
                    f"{cap / 1000:.1f} кВт: инвертор отключается",
                )
            )
    bypass_fault = False
    if through_inv_pass and inv is not None and inv.bypass_a > 0:
        i_a = _i_max_a(_va_per_phase(through_inv_pass, pw.grid))
        if i_a > inv.bypass_a + EPS:
            bypass_fault = True
            fs.append(
                Finding(
                    "error",
                    "BYPASS_OVERLOAD",
                    f"Ток {i_a:.0f} А выше тока байпаса инвертора {inv.bypass_a:g} А",
                )
            )
    grid_tripped = False
    if sw.grid:
        i_a = _i_max_a(_va_per_phase(grid_loads, pw.grid))
        if i_a > inp.main_breaker_a + EPS:
            grid_tripped = True
            fs.append(
                Finding(
                    "error",
                    "MAIN_TRIP",
                    f"Ток {i_a:.0f} А выше вводного автомата {inp.main_breaker_a:g} А: "
                    "вводной автомат отключается",
                )
            )

    # apply the trips
    for x in feed:
        if (
            (src == "generator" and gen_fault)
            or (src == "inverter" and inv_fault)
            or bypass_fault
            or (src == "grid" and grid_tripped)
        ):
            state[x.id] = (None, "overload" if src != "grid" else "tripped")
    for x in other:
        if not sw.grid:
            state[x.id] = (None, "not_backed_up")
        elif grid_tripped:
            state[x.id] = (None, "tripped")
        else:
            state[x.id] = ("grid", "")

    # --- the picture of what is actually on
    powered_ids = {i for i, (s, _) in state.items() if s is not None}
    on_grid = [x for x in pw.loads if state.get(x.id, (None, ""))[0] == "grid"]
    on_gen = [x for x in pw.loads if state.get(x.id, (None, ""))[0] == "generator"]
    on_inv = [x for x in pw.loads if state.get(x.id, (None, ""))[0] == "inverter"]

    # PV effect
    export_w = 0.0
    import_w = _p_w(on_grid)
    pv_used = 0.0
    battery_net = 0.0
    if sw.pv and inp.pv_kwp > 0:
        if sw.grid and not grid_tripped:
            pv_used = min(pv_w, import_w)
            export_w = max(pv_w - import_w, 0.0)
            import_w -= pv_used
        elif src == "inverter" and inp.pv_on_backup_inverter and not inv_fault:
            pv_used = min(pv_w, _p_w(on_inv))
        elif not sw.grid:
            fs.append(
                Finding(
                    "info",
                    "PV_ISLANDING",
                    "Сеть пропала: сетевой инвертор PV отключается (защита от островного режима), "
                    "панели не питают нагрузку",
                )
            )
    if src == "inverter":
        battery_net = max(_p_w(on_inv) - pv_used, 0.0) / INVERTER_EFF
    autonomy: float | None = None
    if src == "inverter" and pw.battery is not None and battery_net > EPS and not inv_fault:
        autonomy = battery_usable_kwh(pw.battery) * 1000.0 / battery_net
        if autonomy < pw.autonomy_target_h - EPS:
            fs.append(
                Finding(
                    "warning",
                    "AUTONOMY_LOW",
                    f"Автономия {autonomy:.1f} ч меньше целевой {pw.autonomy_target_h:.1f} ч",
                )
            )

    # dark backed-up groups
    dark_backed = [x for x in backed if x.id not in powered_ids]
    if dark_backed and not sw.grid and src is None:
        fs.append(
            Finding(
                "warning",
                "BACKUP_DARK",
                "Резервируемые группы обесточены: нет доступного источника — "
                + ", ".join(x.name for x in dark_backed),
            )
        )

    # phase imbalance on the grid side
    if pw.grid == "3ph" and on_grid:
        imb = phase_imbalance(_va_per_phase(on_grid, pw.grid), pw.grid)
        if imb > 15 + EPS:
            fs.append(
                Finding("warning", "PHASE_IMBALANCE", f"Перекос фаз по вводу {imb:.0f}% > 15%")
            )

    sources = _sources(
        inp, gen_fault, inv_fault, grid_tripped, on_grid, on_gen, on_inv, pv_w, pv_used
    )

    groups = tuple(
        GroupState(
            id=x.id,
            name=x.name,
            backed_up=x.backed_up,
            powered=x.id in powered_ids,
            source=state.get(x.id, (None, ""))[0],
            reason=state.get(x.id, (None, "no_source"))[1] if x.id not in powered_ids else "",
            phase=x.phase,
            power_w=x.power_w,
        )
        for x in pw.loads
    )
    powered_w = _p_w([x for x in pw.loads if x.id in powered_ids])
    interruption = _transfer_time(inp, src) if (not sw.grid and src is not None) else None
    if not sw.grid and src is not None and interruption is None and src == "generator":
        fs.append(
            Finding(
                "info",
                "MANUAL_START",
                "Запуск генератора и переключение выполняются вручную: перерыв питания "
                "зависит от оператора",
            )
        )

    return SimResult(
        backup_source=src,
        main_source="grid" if (sw.grid and not grid_tripped and other) else None,
        ats_state=ats_state,
        groups=groups,
        sources=sources,
        findings=tuple(fs),
        interruption_s=interruption,
        pv_w=pv_w,
        grid_import_w=max(import_w, 0.0),
        grid_export_w=export_w,
        battery_net_w=battery_net,
        autonomy_h=autonomy,
        powered_w=powered_w,
        dark_w=_p_w([x for x in pw.loads if x.id not in powered_ids]),
    )


def _sources(
    inp: SimInput,
    gen_fault: bool,
    inv_fault: bool,
    grid_tripped: bool,
    on_grid: list[LoadInput],
    on_gen: list[LoadInput],
    on_inv: list[LoadInput],
    pv_w: float,
    pv_used: float,
) -> tuple[SourceState, ...]:
    pw, sw = inp.power, inp.switches
    out: list[SourceState] = []

    def state(
        name: str,
        on: bool,
        feeding: list[LoadInput],
        rating_va: float | None,
        fault: bool,
        note: str = "",
    ) -> SourceState:
        per_phase = _va_per_phase(feeding, pw.grid)
        va = sum(per_phase.values())
        role: SourceRole = (
            "fault" if fault else ("feeding" if feeding else ("standby" if on else "off"))
        )
        util = None if not rating_va else va / rating_va * 100.0
        return SourceState(
            name=name,
            on=on,
            role=role,
            load_w=_p_w(feeding),
            load_va=va,
            current_a=_i_max_a(per_phase),
            rating_va=rating_va,
            utilization_pct=util,
            note=note,
        )

    grid_rating = inp.main_breaker_a * (VOLTAGE_3PH * SQRT3 if pw.grid == "3ph" else VOLTAGE_1PH)
    out.append(state("grid", sw.grid, on_grid, grid_rating, grid_tripped))
    if pw.scenario in WITH_GENERATOR and pw.generator is not None:
        out.append(state("generator", sw.generator, on_gen, _gen_limit_va(pw.generator), gen_fault))
    if pw.scenario in WITH_INVERTER and pw.inverter is not None:
        out.append(
            state(
                "inverter",
                sw.inverter,
                on_inv,
                _inv_capacity_w(pw.inverter),
                inv_fault,
            )
        )
    if inp.pv_kwp > 0:
        out.append(
            SourceState(
                name="pv",
                on=sw.pv,
                role="feeding" if pv_used > 0 else ("standby" if sw.pv else "off"),
                load_w=pv_used,
                load_va=pv_used,
                current_a=pv_used / VOLTAGE_1PH if pv_used else 0.0,
                rating_va=inp.pv_kwp * 1000.0,
                utilization_pct=(pv_w / (inp.pv_kwp * 1000.0) * 100.0) if sw.pv else None,
            )
        )
    return tuple(out)
