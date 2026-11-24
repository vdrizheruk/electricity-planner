"""Glue between Django models and the pure ``calculations`` layer."""

from django.db import transaction

from calculations import GroupInput, ProjectCalculation, SystemInput, calculate_project

from .models import ConsumerGroup, Project


def build_inputs(project: Project) -> tuple[list[GroupInput], SystemInput]:
    groups = [
        GroupInput(
            id=g.pk,
            name=g.name,
            type=g.type,
            power_w=float(g.power_w),
            cos_phi=float(g.cos_phi),
            phase=g.phase,
            length_m=float(g.length_m),
            backed_up=g.backed_up,
            wet_zone=g.wet_zone,
        )
        for g in project.groups.all()
    ]
    system = SystemInput(
        grid=project.grid,  # type: ignore[arg-type]
        main_breaker_a=project.main_breaker_a,
        earthing=project.earthing,
    )
    return groups, system


@transaction.atomic
def autoselect_project(project: Project, *, save: bool = True) -> ProjectCalculation:
    """Run the calculation and (optionally) store the selected values on the groups."""
    groups, system = build_inputs(project)
    result = calculate_project(groups, system)
    if save:
        by_id = {g.pk: g for g in project.groups.select_for_update()}
        for r in result.groups:
            g = by_id[r.group_id]
            g.assigned_phase = r.phase
            g.breaker_a = r.breaker_a
            g.curve = r.curve
            g.cable_mm2 = r.cable_mm2
            g.voltage_drop_pct = round(r.voltage_drop_pct, 2)  # type: ignore[assignment]
            g.rcd_ma = r.rcd_ma
        ConsumerGroup.objects.bulk_update(
            [by_id[r.group_id] for r in result.groups],
            ["assigned_phase", "breaker_a", "curve", "cable_mm2", "voltage_drop_pct", "rcd_ma"],
        )
    return result
