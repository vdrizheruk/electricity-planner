"""Glue between the project data and the pure power simulation."""

from projects.models import Project

from .db import get_or_create_power, power_input
from .pv_db import get_or_create_pv, run_pv_check
from .services import SimInput, SimResult, Switches, simulate


def build_sim_input(project: Project, switches: Switches) -> SimInput:
    ps = get_or_create_power(project)
    pv = get_or_create_pv(project)
    checked = run_pv_check(project, pv)
    return SimInput(
        power=power_input(project, ps),
        switches=switches,
        main_breaker_a=float(project.main_breaker_a),
        pv_kwp=checked[0].metrics.kwp if checked else 0.0,
        pv_on_backup_inverter=(ps.inverter_id is not None and ps.inverter_id == pv.inverter_id),
    )


def run_simulation(project: Project, switches: Switches) -> SimResult:
    return simulate(build_sim_input(project, switches))
