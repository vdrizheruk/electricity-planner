from dataclasses import replace

import pytest

from power.services import (
    AtsSpec,
    BatterySpec,
    GeneratorSpec,
    InverterSpec,
    LoadInput,
    PowerInput,
    SimInput,
    Switches,
    simulate,
)

LOADS = (
    LoadInput(1, "Свет", "lighting", 1000, phase="L1", backed_up=True),
    LoadInput(2, "Холодильник", "socket", 2000, phase="L2", backed_up=True),
    LoadInput(3, "Бойлер", "boiler", 3000, phase="L3", backed_up=False),
)


def sim(scenario="grid_gen_ats", *, grid="3ph", loads=LOADS, switches=None, **kw):  # noqa: ANN001, ANN003
    extra = {
        "generator": GeneratorSpec(kva=10, kw=8, phases=3 if grid == "3ph" else 1),
        "ats": AtsSpec(kind="modular", poles=4, rated_a=40),
    }
    extra.update(kw.pop("power", {}))
    power = PowerInput(grid=grid, earthing="TN-C-S", scenario=scenario, loads=loads, **extra)
    return simulate(SimInput(power=power, switches=switches or Switches(), **kw))


def powered(res):  # noqa: ANN001
    return {g.id: g.powered for g in res.groups}


def reason(res, gid):  # noqa: ANN001
    return next(g.reason for g in res.groups if g.id == gid)


def codes(res):  # noqa: ANN001
    return {f.code for f in res.findings}


def test_grid_on_everything_powered() -> None:
    r = sim()
    assert all(powered(r).values())
    assert r.backup_source == "grid" and r.main_source == "grid"
    assert r.dark_w == 0 and r.powered_w == 5000


def test_grid_lost_ats_takes_generator_non_backed_go_dark() -> None:
    r = sim(switches=Switches(grid=False, generator=True))
    assert powered(r) == {1: True, 2: True, 3: False}
    assert r.backup_source == "generator" and r.ats_state == "generator"
    assert reason(r, 3) == "not_backed_up"
    assert r.interruption_s == pytest.approx(15.15)


def test_grid_lost_generator_off_everything_dark() -> None:
    r = sim(switches=Switches(grid=False))
    assert not any(powered(r).values())
    assert r.backup_source is None and "BACKUP_DARK" in codes(r)


def test_forced_position_gen_without_generator_running() -> None:
    r = sim(switches=Switches(position="gen"))
    assert powered(r) == {1: False, 2: False, 3: True}
    assert reason(r, 1) == "position"


def test_forced_position_off_opens_backup_bus() -> None:
    r = sim(switches=Switches(position="off"))
    assert powered(r) == {1: False, 2: False, 3: True}


def test_backfeed_hazard_without_interlock() -> None:
    r = sim(
        switches=Switches(generator=True),
        power={"ats": AtsSpec(kind="contactor", poles=4, rated_a=40)},
    )
    assert "BACKFEED_HAZARD" in codes(r)
    assert not powered(r)[1]
    assert reason(r, 1) == "fault"


def test_grid_and_generator_safe_with_modular_ats() -> None:
    r = sim(switches=Switches(generator=True))
    assert r.backup_source == "grid" and "BACKFEED_HAZARD" not in codes(r)


def test_generator_overload_trips() -> None:
    big = (replace(LOADS[0], power_w=9000), *LOADS[1:])
    r = sim(loads=big, switches=Switches(grid=False, generator=True))
    assert "GEN_OVERLOAD" in codes(r)
    assert not powered(r)[1] and reason(r, 1) == "overload"


def test_main_breaker_trip() -> None:
    r = sim(grid="1ph", loads=tuple(replace(x, phase="L1") for x in LOADS), main_breaker_a=16)
    assert "MAIN_TRIP" in codes(r)
    assert not any(powered(r).values())
    assert reason(r, 3) == "tripped"


def test_manual_switch_needs_position() -> None:
    r = sim("manual_i0ii", power={"ats": AtsSpec(kind="manual", poles=4, rated_a=40)})
    assert "MANUAL_POSITION" in codes(r)
    assert powered(r) == {1: False, 2: False, 3: True}
    r2 = sim(
        "manual_i0ii",
        switches=Switches(grid=False, generator=True, position="gen"),
        power={"ats": AtsSpec(kind="manual", poles=4, rated_a=40)},
    )
    assert powered(r2) == {1: True, 2: True, 3: False}
    assert r2.interruption_s is None and "MANUAL_START" in codes(r2)


def test_one_phase_generator_feeds_only_its_phase() -> None:
    r = sim(
        "grid3_gen1_phase",
        switches=Switches(grid=False, generator=True),
        power={
            "generator": GeneratorSpec(kva=5, kw=4, phases=1),
            "backup_phase": "L1",
        },
    )
    assert powered(r) == {1: True, 2: False, 3: False}
    assert reason(r, 2) == "phase" and "PHASE_DARK" in codes(r)


def test_one_phase_generator_combine_feeds_one_phase_groups_only() -> None:
    loads = (*LOADS[:2], replace(LOADS[0], id=4, name="Станок", phase="3ph", backed_up=True))
    r = sim(
        "grid3_gen1_combine",
        loads=loads,
        switches=Switches(grid=False, generator=True),
        power={"generator": GeneratorSpec(kva=8, kw=6, phases=1)},
    )
    assert powered(r)[1] and powered(r)[2] and not powered(r)[4]


INV = {
    "inverter": InverterSpec(kind="hybrid", phases=3, p_ac_w=5000, bypass_a=32),
    "battery": BatterySpec(kwh=10),
    "generator": None,
    "ats": AtsSpec(),
}


def test_inverter_feeds_backup_when_grid_lost() -> None:
    r = sim("grid_inverter", switches=Switches(grid=False), power=INV)
    assert powered(r) == {1: True, 2: True, 3: False}
    assert r.backup_source == "inverter"
    assert r.autonomy_h is not None and r.autonomy_h > 0
    assert r.interruption_s == pytest.approx(0.02)


def test_inverter_overload_trips() -> None:
    big = (replace(LOADS[0], power_w=9000), *LOADS[1:])
    r = sim("grid_inverter", loads=big, switches=Switches(grid=False), power=INV)
    assert "INVERTER_OVERLOAD" in codes(r)
    assert not powered(r)[1]


def test_inverter_off_without_bypass_darkens_backup() -> None:
    inv = {**INV, "inverter": InverterSpec(kind="hybrid", phases=3, p_ac_w=5000, bypass_a=0)}
    r = sim("grid_inverter", switches=Switches(inverter=False), power=inv)
    assert "INVERTER_OFF" in codes(r)
    assert powered(r) == {1: False, 2: False, 3: True}


def test_inverter_off_with_bypass_passes_grid() -> None:
    r = sim("grid_inverter", switches=Switches(inverter=False), power=INV)
    assert all(powered(r).values()) and r.backup_source == "grid"


def test_priority_inverter_over_grid() -> None:
    gen = {
        **INV,
        "generator": GeneratorSpec(kva=10, kw=8, phases=3),
        "priority": ("inverter", "grid", "generator"),
    }
    r = sim("grid_inverter_gen", switches=Switches(generator=True), power=gen)
    assert r.backup_source == "inverter"


def test_priority_grid_then_generator_when_inverter_empty() -> None:
    gen = {**INV, "generator": GeneratorSpec(kva=10, kw=8, phases=3)}
    r = sim("grid_inverter_gen", switches=Switches(grid=False, generator=True), power=gen)
    assert r.backup_source in ("inverter", "generator")
    assert powered(r)[1]


def test_pv_offsets_import_and_exports_surplus() -> None:
    r = sim(switches=Switches(pv=True, pv_pct=100), pv_kwp=10)
    assert r.pv_w == 10000
    assert r.grid_import_w == 0 and r.grid_export_w == pytest.approx(5000)


def test_pv_islanding_without_grid() -> None:
    r = sim(switches=Switches(grid=False, generator=True, pv=True), pv_kwp=5)
    assert "PV_ISLANDING" in codes(r)


def test_phase_imbalance_flagged() -> None:
    loads = (
        LoadInput(1, "A", "socket", 6000, phase="L1"),
        LoadInput(2, "B", "socket", 500, phase="L2"),
        LoadInput(3, "C", "socket", 500, phase="L3"),
    )
    assert "PHASE_IMBALANCE" in codes(sim(loads=loads))


def test_sources_report_load_and_roles() -> None:
    r = sim(switches=Switches(grid=False, generator=True))
    by = {s.name: s for s in r.sources}
    assert by["generator"].role == "feeding" and by["generator"].load_w == 2000
    assert by["grid"].role in ("off", "fault")
