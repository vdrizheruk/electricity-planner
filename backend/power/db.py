"""Glue between the Django models and the pure ``power.services`` layer."""

import contextlib
from dataclasses import dataclass
from typing import Any

from calculations import calculate_project
from catalog.models import Product
from panels.catalog_pick import pick
from projects.models import Project
from projects.services import build_inputs

from .models import PowerSystem
from .services import (
    AtsSpec,
    BatterySpec,
    Component,
    GeneratorSpec,
    InverterSpec,
    LoadInput,
    PowerInput,
    PowerResult,
    analyze,
)


def _el(p: Product) -> dict[str, Any]:
    return p.electrical or {}


def generator_spec(p: Product) -> GeneratorSpec:
    e = _el(p)
    return GeneratorSpec(
        kva=float(e.get("kva", 0)),
        kw=float(e.get("kw", 0)),
        phases=int(e.get("phases", 1)),
        cos_phi=float(e.get("cos_phi", 0.8)),
        autostart=bool(e.get("autostart_ready", False)),
    )


def inverter_spec(p: Product, ps: PowerSystem) -> InverterSpec:
    e = _el(p)
    return InverterSpec(
        kind=e.get("kind", "hybrid"),
        phases=int(e.get("phases", 1)),
        p_ac_w=float(e.get("p_ac_w", 0)),
        p_surge_w=float(e.get("p_surge_w", 0)),
        bypass_a=float(e.get("bypass_a", 0)),
        batt_v=float(e.get("batt_v", 48)),
        count=ps.inverter_count,
        mode=ps.inverter_mode,  # type: ignore[arg-type]
        bonds_n_pe_offgrid=bool(e.get("bonds_n_pe_offgrid", True)),
        transformerless=bool(e.get("transformerless", True)),
    )


def battery_spec(p: Product, ps: PowerSystem) -> BatterySpec:
    e = _el(p)
    return BatterySpec(
        kwh=float(e.get("kwh", 0)),
        voltage_v=float(e.get("voltage_v", 48)),
        chemistry=e.get("chemistry", "LiFePO4"),
        dod=float(e.get("dod", 0)),
        max_discharge_a=float(e.get("max_discharge_a", 0)),
        count=ps.battery_count,
    )


def load_inputs(project: Project) -> tuple[LoadInput, ...]:
    """Groups with the phase they get from the balancing (stored value as a fallback)."""
    groups, system = build_inputs(project)
    phases: dict[int, str] = {}
    with contextlib.suppress(ValueError):  # keep the stored phases when balancing fails
        phases = {r.group_id: r.phase for r in calculate_project(groups, system).groups}
    stored = {g.pk: g.assigned_phase for g in project.groups.all()}
    return tuple(
        LoadInput(
            id=g.id,
            name=g.name,
            type=g.type,
            power_w=g.power_w,
            cos_phi=g.cos_phi,
            phase=phases.get(g.id) or stored.get(g.id) or "L1",
            backed_up=g.backed_up,
        )
        for g in groups
    )


def get_or_create_power(project: Project) -> PowerSystem:
    ps, _ = PowerSystem.objects.get_or_create(
        project=project,
        defaults={"scenario": "grid_gen_ats" if project.grid == "3ph" else "grid1_gen1"},
    )
    return ps


def power_input(project: Project, ps: PowerSystem) -> PowerInput:
    return PowerInput(
        grid=project.grid,  # type: ignore[arg-type]
        earthing=project.earthing,
        scenario=ps.scenario,  # type: ignore[arg-type]
        loads=load_inputs(project),
        generator=generator_spec(ps.generator) if ps.generator else None,
        inverter=inverter_spec(ps.inverter, ps) if ps.inverter else None,
        battery=battery_spec(ps.battery, ps) if ps.battery else None,
        ats=AtsSpec(
            kind=ps.ats_kind,  # type: ignore[arg-type]
            poles=ps.ats_poles,
            rated_a=float(ps.ats_rated_a),
            mechanical_interlock=ps.mechanical_interlock,
            electrical_interlock=ps.electrical_interlock,
        ),
        backup_phase=ps.backup_phase,  # type: ignore[arg-type]
        autonomy_target_h=ps.autonomy_target_h,
    )


@dataclass
class Suggestion:
    component: Component
    product: Product | None


def suggest_product(c: Component, tier: str) -> Product | None:
    """Cheapest catalog product (closest price tier) that satisfies the component."""
    rated = {"rated_a__gte": c.rated_a} if c.rated_a else {}
    exact = {"rated_a": c.rated_a} if c.rated_a else {}
    if c.kind == "mcb":
        return pick("mcb", tier, poles=c.poles, curve="C", **exact) or pick(
            "mcb", tier, poles=c.poles, curve="C", **rated
        )
    if c.kind == "interlock":
        return pick("ats", tier, electrical__mechanical_interlock=True)
    if c.kind == "contactor":
        return pick("contactor", tier, poles=c.poles, din_mountable=True, **rated)
    if c.kind == "ats_auto":
        return pick("ats", tier, poles=c.poles, electrical__automatic=True, **rated)
    if c.kind == "ats_manual":
        return pick("ats", tier, poles=c.poles, electrical__manual=True, **rated)
    if c.kind == "spd":
        return pick("spd", tier, poles=c.poles, electrical__spd_type="2")
    if c.kind == "rcd":
        return (
            pick("rcd", tier, poles=c.poles, leakage_ma=30, rcd_type="A", **exact)
            or pick("rcd", tier, poles=c.poles, leakage_ma=30, rcd_type="A", **rated)
            or pick("rcd", tier, poles=c.poles, leakage_ma=30, **rated)
        )
    if c.kind == "dc_breaker":
        return pick("dc_breaker", tier, poles__gte=c.poles, **rated)
    return None


def run_check(project: Project, ps: PowerSystem) -> tuple[PowerResult, list[Suggestion]]:
    result = analyze(power_input(project, ps))
    suggestions = [Suggestion(c, suggest_product(c, project.price_tier)) for c in result.components]
    return result, suggestions
