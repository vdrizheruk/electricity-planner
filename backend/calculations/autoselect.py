"""Project-level auto-selection: breaker, cable, RCD grouping, phases, demand."""

from collections import defaultdict
from collections.abc import Sequence

from .breaker import NoStandardSizeError, select_breaker, select_curve
from .cable import CableSelectionError, select_cable
from .constants import (
    GROUP_TYPES,
    MAX_BREAKER_A,
    SQRT3,
    VOLTAGE_1PH,
    VOLTAGE_3PH,
)
from .current import design_current
from .demand import demand_factor, summarize
from .models import (
    Finding,
    GroupInput,
    GroupResult,
    ProjectCalculation,
    RcdAssignment,
    SystemInput,
)
from .phases import PhaseLoad, balance
from .rcd import RcdCandidate, choose_protection, pack_rcds
from .selectivity import breaker_selectivity_ok


def validate_group(group: GroupInput, system: SystemInput) -> None:
    if group.type not in GROUP_TYPES:
        raise ValueError(f"group {group.id}: unknown type {group.type!r}")
    if group.power_w <= 0:
        raise ValueError(f"group {group.id}: power must be > 0")
    if not 0.1 <= group.cos_phi <= 1.0:
        raise ValueError(f"group {group.id}: cos_phi must be within [0.1, 1.0]")
    if group.length_m < 0:
        raise ValueError(f"group {group.id}: length must be >= 0")
    if group.phase == "3ph" and system.grid != "3ph":
        raise ValueError(f"group {group.id}: 3-phase load on a 1-phase supply")


def calculate_project(groups: Sequence[GroupInput], system: SystemInput) -> ProjectCalculation:
    ids = [g.id for g in groups]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate group ids")
    for g in groups:
        validate_group(g, system)

    findings: list[Finding] = []

    # 1. Phase assignment, based on demand (Kc-weighted) apparent power.
    demand_va = {g.id: g.power_w / g.cos_phi * demand_factor(g.type) for g in groups}
    phase_balance = balance(
        system.grid, [PhaseLoad(g.id, g.phase, demand_va[g.id]) for g in groups]
    )
    if system.grid == "3ph" and phase_balance.exceeds_limit:
        findings.append(
            Finding(
                "warning",
                "phase_imbalance",
                f"Перекос фаз {phase_balance.imbalance_pct:.1f}% > 15%",
            )
        )

    # 2. Per-group selection.
    results: dict[int, GroupResult] = {}
    for g in groups:
        three = g.phase == "3ph"
        ib = design_current(g.power_w, g.cos_phi, three)
        try:
            in_a = select_breaker(ib, g.type)
        except NoStandardSizeError as exc:
            findings.append(Finding("error", "breaker_too_large", str(exc), g.id))
            continue
        limit = system.dv_limit_lighting_pct if g.type == "lighting" else system.dv_limit_other_pct
        try:
            section, dv = select_cable(
                group_type=g.type,
                breaker_a=in_a,
                ib_a=ib,
                length_m=g.length_m,
                cos_phi=g.cos_phi,
                three_phase=three,
                dv_limit_pct=limit,
                derating=system.derating,
            )
        except CableSelectionError as exc:
            findings.append(Finding("error", "cable_not_found", str(exc), g.id))
            continue
        cap = MAX_BREAKER_A.get(g.type)
        if cap is not None and in_a > cap:
            findings.append(
                Finding(
                    "warning",
                    "group_too_large",
                    f"Группа «{g.name}»: In={in_a} А больше рекомендуемых {cap} А для типа "
                    f"{g.type}, разделите группу",
                    g.id,
                )
            )
        prot = choose_protection(g.type, g.power_w, g.wet_zone)
        results[g.id] = GroupResult(
            group_id=g.id,
            phase=phase_balance.assignment[g.id],
            ib_a=ib,
            breaker_a=in_a,
            curve=select_curve(g.type),
            cable_mm2=section,
            voltage_drop_pct=dv,
            protection=prot.protection,
            rcd_ma=prot.rcd_ma,
            rcd_type=prot.rcd_type,
            demand_factor=demand_factor(g.type),
            demand_va=demand_va[g.id],
        )

    # 3. RCD / RCBO assignment.
    by_id = {g.id: g for g in groups}
    rcds: list[RcdAssignment] = []
    next_id = 1
    shared: dict[tuple[bool, str], list[RcdCandidate]] = defaultdict(list)
    for gid in sorted(results):
        r = results[gid]
        g = by_id[gid]
        three = r.phase == "3ph"
        demand_a = r.demand_va / (SQRT3 * VOLTAGE_3PH if three else VOLTAGE_1PH)
        if r.protection == "rcbo":
            rcds.append(
                RcdAssignment(
                    id=next_id,
                    phase=r.phase,
                    poles=4 if three else 2,
                    rating_a=r.breaker_a,
                    leakage_ma=30,
                    rcd_type=r.rcd_type,
                    group_ids=(gid,),
                    backed_up=g.backed_up,
                    demand_a=demand_a,
                )
            )
            next_id += 1
        elif r.protection == "rcd":
            shared[(g.backed_up, r.phase)].append(RcdCandidate(gid, demand_a, r.breaker_a))
    for (backed_up, phase), cands in sorted(shared.items()):
        for b in pack_rcds(cands, system.max_groups_per_rcd):
            rcds.append(
                RcdAssignment(
                    id=next_id,
                    phase=phase,
                    poles=4 if phase == "3ph" else 2,
                    rating_a=b.rating_a,
                    leakage_ma=30,
                    rcd_type="A",
                    group_ids=b.group_ids,
                    backed_up=backed_up,
                    demand_a=b.demand_a,
                )
            )
            next_id += 1

    # 4. Demand and main breaker check (only groups that were calculated).
    ok_groups = [by_id[i] for i in sorted(results)]
    ok_va = [results[g.id].demand_va for g in ok_groups]
    ok_w = [g.power_w * demand_factor(g.type) for g in ok_groups]
    ok_phase_loads = _phase_loads(system, results)
    demand = summarize(system, [g.power_w for g in ok_groups], ok_va, ok_w, ok_phase_loads)
    if not demand.main_ok:
        findings.append(
            Finding(
                "error",
                "main_breaker_overload",
                f"Расчётный ток {demand.design_current_a:.1f} А превышает вводной автомат "
                f"{system.main_breaker_a} А",
            )
        )

    # 5. Selectivity by ratings.
    for gid in sorted(results):
        r = results[gid]
        if not breaker_selectivity_ok(system.main_breaker_a, r.breaker_a):
            findings.append(
                Finding(
                    "warning",
                    "selectivity",
                    f"Нет селективности по номиналам: вводной {system.main_breaker_a} А и "
                    f"группа «{by_id[gid].name}» {r.breaker_a} А (нужно ≥ 1.6×)",
                    gid,
                )
            )

    return ProjectCalculation(
        groups=[results[i] for i in sorted(results)],
        rcds=rcds,
        demand=demand,
        phases=phase_balance,
        findings=findings,
    )


def _phase_loads(system: SystemInput, results: dict[int, GroupResult]) -> dict[str, float]:
    phases = ("L1", "L2", "L3") if system.grid == "3ph" else ("L1",)
    totals = {p: 0.0 for p in phases}
    for r in results.values():
        if r.phase == "3ph":
            for p in phases:
                totals[p] += r.demand_va / 3
        else:
            totals[r.phase] += r.demand_va
    return totals
