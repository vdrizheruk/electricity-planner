"""Entry point: run every backup-power check for a project and plan the switchgear."""

from dataclasses import replace

from .checks import (
    check_battery,
    check_generator,
    check_inverter,
    phase_imbalance,
)
from .loads import backed_up, demand, phase_current_a, starting
from .models import Finding, Metrics, PowerInput, PowerResult
from .plan import DESCRIPTIONS, WITH_GENERATOR, WITH_INVERTER, build_components, check_switching


def analyze(inp: PowerInput) -> PowerResult:
    p, s, per_phase = demand(inp.loads, inp.grid)
    p_start, s_start = starting(inp.loads, inp.grid)
    fs: list[Finding] = []
    if not backed_up(inp.loads):
        fs.append(
            Finding("warning", "NO_BACKUP_LOADS", "Нет резервируемых групп: нечего резервировать")
        )
    m = Metrics(
        p_backup_w=p,
        s_backup_va=s,
        p_start_w=p_start,
        s_start_va=s_start,
        phase_va=per_phase,
        i_backup_a=phase_current_a(per_phase),
        imbalance_pct=phase_imbalance(per_phase, inp.grid),
    )

    check_switching(inp, m, fs)
    if inp.scenario in WITH_GENERATOR and inp.generator is not None:
        req_kva, req_kw = check_generator(inp, inp.generator, m, fs)
        m = replace(m, gen_required_kva=req_kva, gen_required_kw=req_kw)
    if inp.scenario in WITH_INVERTER and inp.inverter is not None:
        cap, required = check_inverter(inp, inp.inverter, m, fs)
        autonomy, dc_a, usable = check_battery(inp, inp.battery, inp.inverter, m, fs)
        m = replace(
            m,
            inverter_capacity_w=cap,
            inverter_required_w=required,
            autonomy_h=autonomy,
            battery_dc_a=dc_a,
            battery_usable_kwh=usable,
        )
    if inp.scenario == "grid_inverter_gen":
        fs.append(
            Finding(
                "info",
                "PRIORITY",
                "Приоритет источников: " + " → ".join(inp.priority),
            )
        )

    components = build_components(inp, m)
    ok = not any(f.level == "error" for f in fs)
    return PowerResult(
        ok=ok,
        metrics=m,
        findings=tuple(fs),
        components=components,
        description=DESCRIPTIONS[inp.scenario],
    )
