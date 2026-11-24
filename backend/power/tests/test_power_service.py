import pytest

from power.services import (
    AtsSpec,
    BatterySpec,
    GeneratorSpec,
    InverterSpec,
    LoadInput,
    PowerInput,
    analyze,
)


def L(id, type_, p, *, cos=1.0, phase="L1", bk=True):
    return LoadInput(id, f"g{id}", type_, p, cos, phase, bk)


# P*Kc: sockets 1500 W, lighting 320 W, ac (2000 W, cos 0.8 -> 2500 VA) 1600 W / 2000 VA
BASE = (L(1, "sockets", 3000), L(2, "lighting", 400), L(3, "ac", 2000, cos=0.8))
GEN7 = GeneratorSpec(kva=7.0, kw=5.6, phases=1)
MODULAR2 = AtsSpec("modular", poles=2, rated_a=32)


def run(**kw):
    base = dict(grid="1ph", earthing="TN-C-S", scenario="grid1_gen1", loads=BASE)
    base.update(kw)
    return analyze(PowerInput(**base))


def codes(r, level=None):
    return {f.code for f in r.findings if level is None or f.level == level}


# ------------------------------------------------------------------ loads
def test_demand_and_starting_values():
    m = run(generator=GEN7, ats=MODULAR2).metrics
    assert m.p_backup_w == pytest.approx(3420)
    assert m.s_backup_va == pytest.approx(3820)
    # largest start: air conditioner 3x instead of 0.8x -> +2500*2.2 VA / +2000*2.2 W
    assert m.p_start_w == pytest.approx(7820)
    assert m.s_start_va == pytest.approx(9320)
    assert m.i_backup_a == pytest.approx(3820 / 230)
    assert m.imbalance_pct == 0


def test_only_backed_up_groups_count():
    loads = (*BASE, L(9, "boiler", 3000, bk=False))
    assert run(loads=loads, generator=GEN7, ats=MODULAR2).metrics.p_backup_w == pytest.approx(3420)


def test_no_backup_loads_warns():
    r = run(loads=(L(1, "sockets", 1000, bk=False),), generator=GEN7, ats=MODULAR2)
    assert "NO_BACKUP_LOADS" in codes(r, "warning")
    assert r.metrics.p_backup_w == 0


# -------------------------------------------------------------- generator
def test_valid_single_phase_generator_scheme():
    r = run(generator=GEN7, ats=MODULAR2)
    assert r.ok and not codes(r, "error")
    assert r.metrics.gen_required_kva == pytest.approx(3.82)
    assert r.metrics.gen_required_kw == pytest.approx(3.42)


def test_generator_missing():
    assert "GENERATOR_MISSING" in codes(run(ats=MODULAR2), "error")


def test_generator_undersized_kva_and_kw():
    r = run(generator=GeneratorSpec(3.0, 2.4), ats=MODULAR2)
    assert {"GEN_UNDERSIZED", "GEN_KW_UNDERSIZED"} <= codes(r, "error")
    assert not r.ok
    # kVA is enough (4.0 >= 3.82) but kW is not (3.0 < 3.42)
    r = run(generator=GeneratorSpec(4.0, 3.0), ats=MODULAR2)
    assert "GEN_UNDERSIZED" not in codes(r) and "GEN_KW_UNDERSIZED" in codes(r, "error")


def test_generator_surge_boundary():
    # 5 kVA tolerates 7.5 kVA of start; the air conditioner pushes it to 9.32 kVA
    assert "GEN_SURGE" in codes(run(generator=GeneratorSpec(5.0, 4.0), ats=MODULAR2), "error")
    # 6.3 kVA * 1.5 = 9.45 >= 9.32
    assert "GEN_SURGE" not in codes(run(generator=GeneratorSpec(6.3, 5.0), ats=MODULAR2))


def test_generator_phase_mismatch():
    g3 = GeneratorSpec(12.5, 10, phases=3)
    assert "GEN_PHASE_MISMATCH" in codes(run(generator=g3, ats=MODULAR2), "error")
    r = run(grid="3ph", generator=GEN7, scenario="grid_gen_ats", ats=AtsSpec("modular", 4, 32))
    assert "GEN_PHASE_MISMATCH" in codes(r, "error")


def test_three_phase_generator_per_phase_limit_and_imbalance():
    loads = (L(1, "lighting", 5000, phase="L1"),)  # 4000 VA all on L1
    r = run(
        grid="3ph",
        scenario="grid_gen_ats",
        loads=loads,
        generator=GeneratorSpec(6.0, 4.8, phases=3),
        ats=AtsSpec("modular", 4, 32),
    )
    assert "GEN_PHASE_OVERLOAD" in codes(r, "error")  # 4.0 kVA > 6/3
    assert "GEN_PHASE_IMBALANCE" in codes(r, "warning")
    assert "GEN_UNDERSIZED" not in codes(r)


def test_imbalance_boundary_exactly_15_percent_is_not_flagged():
    def loads(a, b, c):
        return (
            L(1, "boiler", a, phase="L1"),
            L(2, "boiler", b, phase="L2"),
            L(3, "boiler", c, phase="L3"),
        )

    common = dict(
        grid="3ph",
        scenario="grid_gen_ats",
        generator=GeneratorSpec(30.0, 24, phases=3),
        ats=AtsSpec("modular", 4, 63),
    )
    r = run(loads=loads(1150, 1000, 850), **common)
    assert r.metrics.imbalance_pct == pytest.approx(15.0)
    assert "GEN_PHASE_IMBALANCE" not in codes(r)
    r = run(loads=loads(1160, 1000, 840), **common)
    assert "GEN_PHASE_IMBALANCE" in codes(r, "warning")


# ------------------------------------------------------- switching safety
def test_generator_without_ats_is_parallel_error():
    r = run(generator=GEN7)
    assert "PARALLEL_GEN_GRID" in codes(r, "error") and not r.ok


def test_contactor_ats_needs_both_interlocks():
    r = run(generator=GEN7, ats=AtsSpec("contactor", 2, 32))
    assert {"NO_MECHANICAL_INTERLOCK", "NO_ELECTRICAL_INTERLOCK"} <= codes(r, "error")
    r = run(generator=GEN7, ats=AtsSpec("contactor", 2, 32, mechanical_interlock=True))
    assert codes(r, "error") == {"NO_ELECTRICAL_INTERLOCK"}
    r = run(
        generator=GEN7,
        ats=AtsSpec("contactor", 2, 32, mechanical_interlock=True, electrical_interlock=True),
    )
    assert r.ok


@pytest.mark.parametrize("earthing", ["TN-S", "TN-C-S", "TT"])
def test_three_phase_needs_four_pole_ats(earthing):
    kw = dict(
        grid="3ph",
        earthing=earthing,
        scenario="grid_gen_ats",
        loads=(L(1, "sockets", 3000, phase="L1"), L(2, "sockets", 3000, phase="L2")),
        generator=GeneratorSpec(12.5, 10, phases=3),
    )
    assert "N_NOT_SWITCHED" in codes(run(ats=AtsSpec("modular", 3, 63), **kw), "error")
    assert "N_NOT_SWITCHED" not in codes(run(ats=AtsSpec("modular", 4, 63), **kw))


def test_single_phase_needs_two_poles():
    assert "N_NOT_SWITCHED" in codes(run(generator=GEN7, ats=AtsSpec("modular", 1, 32)), "error")


def test_ats_rating_must_cover_load_current():
    # I = 3820/230 = 16.6 A
    assert "ATS_UNDERSIZED" in codes(run(generator=GEN7, ats=AtsSpec("modular", 2, 16)), "error")
    assert "ATS_UNDERSIZED" not in codes(run(generator=GEN7, ats=AtsSpec("modular", 2, 20)))


def test_manual_switch_rules():
    kw = dict(generator=GEN7)
    assert "ATS_KIND_MISMATCH" in codes(run(scenario="manual_i0ii", ats=MODULAR2, **kw), "error")
    assert run(scenario="manual_i0ii", ats=AtsSpec("manual", 2, 32), **kw).ok
    assert "MANUAL_SWITCH" in codes(run(ats=AtsSpec("manual", 2, 32), **kw), "warning")


def test_three_phase_grid_with_single_phase_generator_on_one_phase():
    kw = dict(
        grid="3ph",
        scenario="grid3_gen1_phase",
        generator=GEN7,
        ats=AtsSpec("modular", 2, 32),
        backup_phase="L2",
    )
    ok = run(loads=(L(1, "sockets", 3000, phase="L2"), L(2, "lighting", 400, phase="L2")), **kw)
    assert ok.ok
    bad = run(loads=(L(1, "sockets", 3000, phase="L2"), L(2, "lighting", 400, phase="L3")), **kw)
    assert "BACKUP_LOADS_NOT_ON_ONE_PHASE" in codes(bad, "error")
    wrong_phase = run(loads=(L(1, "sockets", 3000, phase="L1"),), **kw)
    assert "BACKUP_LOADS_NOT_ON_ONE_PHASE" in codes(wrong_phase, "error")
    three = run(loads=(L(1, "cooker", 9000, phase="3ph"),), **kw)
    assert "BACKUP_LOADS_NOT_ON_ONE_PHASE" in codes(three, "error")
    # one-phase scheme switches phase + N only
    assert "N_NOT_SWITCHED" in codes(
        run(loads=(L(1, "sockets", 3000, phase="L2"),), **{**kw, "ats": AtsSpec("modular", 1, 32)})
    )


def test_three_phase_grid_with_single_phase_generator_combined_phases():
    kw = dict(grid="3ph", scenario="grid3_gen1_combine", generator=GEN7)
    loads = (L(1, "sockets", 3000, phase="L1"), L(2, "lighting", 400, phase="L2"))
    r = run(loads=loads, ats=AtsSpec("modular", 4, 63), **kw)
    assert r.ok and "COMBINED_PHASES" in codes(r, "info")
    # the whole load sits on one generator phase: 3.82 kVA ... compare with the generator
    assert r.metrics.gen_required_kva == pytest.approx(1.5 + 0.32)
    assert "N_NOT_SWITCHED" in codes(run(loads=loads, ats=AtsSpec("modular", 2, 63), **kw))
    r = run(loads=(L(1, "cooker", 9000, phase="3ph"),), ats=AtsSpec("modular", 4, 63), **kw)
    assert "THREE_PHASE_LOAD_ON_1PH_GEN" in codes(r, "error")
    # ATS must carry the sum of all phases
    big = (L(i, "boiler", 3000, phase=f"L{i}") for i in (1, 2, 3))
    r = run(loads=tuple(big), ats=AtsSpec("modular", 4, 32), **kw)
    assert "ATS_UNDERSIZED" in codes(r, "error")  # 9000/230 = 39 A > 32 A


# --------------------------------------------------------------- inverter
HYB = InverterSpec(kind="hybrid", phases=1, p_ac_w=5000, p_surge_w=10000, bypass_a=50, batt_v=48)
BAT = BatterySpec(kwh=5.12, voltage_v=51.2, max_discharge_a=100)


def inv(**kw):
    base = dict(scenario="grid_inverter", inverter=HYB, battery=BAT)
    base.update(kw)
    return run(**base)


def test_inverter_scheme_metrics():
    r = inv(battery=BatterySpec(kwh=5.12, voltage_v=48, max_discharge_a=100))
    assert r.ok
    m = r.metrics
    assert m.inverter_capacity_w == 5000 and m.inverter_required_w == pytest.approx(3420)
    assert m.battery_usable_kwh == pytest.approx(5.12 * 0.9)
    assert m.autonomy_h == pytest.approx(5.12 * 0.9 * 0.9 / 3.42)
    assert m.battery_dc_a == pytest.approx(3420 / (48 * 0.9))
    assert "AUTONOMY_LOW" in codes(r, "warning")  # 1.2 h < 4 h target


def test_autonomy_target_and_chemistry():
    big = BatterySpec(kwh=5.0, voltage_v=48, max_discharge_a=100, count=4)
    assert "AUTONOMY_LOW" not in codes(inv(battery=big))  # 4*5*.9*.9/3.42 = 4.74 h
    agm = BatterySpec(kwh=5.0, voltage_v=48, chemistry="AGM", max_discharge_a=100, count=4)
    r = inv(battery=agm)
    assert r.metrics.autonomy_h == pytest.approx(4 * 5 * 0.5 * 0.9 / 3.42)
    assert "AUTONOMY_LOW" in codes(r)


def test_inverter_not_backup_and_missing_parts():
    on = InverterSpec(kind="on-grid", p_ac_w=5000)
    assert "INVERTER_NOT_BACKUP" in codes(inv(inverter=on), "error")
    assert "INVERTER_MISSING" in codes(inv(inverter=None), "error")
    assert "BATTERY_MISSING" in codes(inv(battery=None), "error")


def test_inverter_undersized_and_surge():
    small = InverterSpec(p_ac_w=3000, p_surge_w=9000, batt_v=48)
    assert "INVERTER_UNDERSIZED" in codes(inv(inverter=small), "error")
    weak = InverterSpec(p_ac_w=5000, p_surge_w=6000, batt_v=48)
    assert "INVERTER_SURGE" in codes(inv(inverter=weak), "error")  # 7820 W start > 6000
    unknown_surge = InverterSpec(p_ac_w=5000, p_surge_w=0, batt_v=48)  # assumes 1.5x = 7500
    assert "INVERTER_SURGE" in codes(inv(inverter=unknown_surge), "error")
    assert "INVERTER_SURGE" not in codes(inv(inverter=HYB))


def test_parallel_inverters_add_up():
    two = InverterSpec(p_ac_w=2000, p_surge_w=4000, count=2, mode="parallel", batt_v=48)
    r = inv(inverter=two)
    assert r.metrics.inverter_capacity_w == 4000
    assert "INVERTER_UNDERSIZED" not in codes(r)


def test_bypass_current_warning():
    low = InverterSpec(p_ac_w=5000, p_surge_w=10000, bypass_a=10, batt_v=48)
    assert "INVERTER_BYPASS" in codes(inv(inverter=low), "warning")  # 16.6 A > 10 A


def test_battery_voltage_and_discharge_limit():
    wrong = BatterySpec(kwh=1.2, voltage_v=12, max_discharge_a=100)
    assert "BATTERY_VOLTAGE_MISMATCH" in codes(inv(battery=wrong), "error")
    weak = BatterySpec(kwh=5.12, voltage_v=48, max_discharge_a=50)
    r = inv(battery=weak)
    assert "BATTERY_DISCHARGE_LIMIT" in codes(r, "error")  # 79 A > 50 A
    two = BatterySpec(kwh=5.12, voltage_v=48, max_discharge_a=50, count=2)
    assert "BATTERY_DISCHARGE_LIMIT" not in codes(inv(battery=two))


def test_single_phase_inverter_in_three_phase_grid():
    spread = (L(1, "sockets", 3000, phase="L1"), L(2, "lighting", 400, phase="L2"))
    kw = dict(grid="3ph", battery=BatterySpec(5.12, 48, max_discharge_a=100))
    assert "INVERTER_PHASE_MISMATCH" in codes(inv(loads=spread, **kw), "error")
    one = (L(1, "sockets", 3000, phase="L1"), L(2, "lighting", 400, phase="L1"))
    assert "INVERTER_PHASE_MISMATCH" not in codes(inv(loads=one, **kw))
    three = InverterSpec(phases=3, p_ac_w=15000, p_surge_w=30000, batt_v=48)
    assert "INVERTER_PHASE_MISMATCH" not in codes(inv(loads=spread, inverter=three, **kw))


def test_phase_set_of_three_single_phase_inverters():
    loads = (L(1, "sockets", 3000, phase="L1"), L(2, "sockets", 3000, phase="L2"))
    bat = BatterySpec(5.12, 48, max_discharge_a=100, count=2)
    ok = InverterSpec(phases=1, p_ac_w=3000, p_surge_w=6000, count=3, mode="phase_set", batt_v=48)
    r = inv(grid="3ph", loads=loads, inverter=ok, battery=bat)
    assert "INVERTER_PHASE_MISMATCH" not in codes(r) and "PHASE_SET_INVALID" not in codes(r)
    bad = InverterSpec(phases=1, p_ac_w=3000, count=1, mode="phase_set", batt_v=48)
    assert "PHASE_SET_INVALID" in codes(inv(grid="3ph", loads=loads, inverter=bad, battery=bat))


def test_three_phase_inverter_per_phase_capacity():
    # 3 ph inverter 6 kW -> 2 kW per phase; 1500 W sockets + 320 W lighting on L1 = 1820 W ok
    three = InverterSpec(phases=3, p_ac_w=6000, p_surge_w=12000, batt_v=48)
    bat = BatterySpec(5.12, 48, max_discharge_a=100)
    loads = (L(1, "sockets", 3000, phase="L1"), L(2, "lighting", 400, phase="L1"))
    assert "INVERTER_PHASE_OVERLOAD" not in codes(
        inv(grid="3ph", loads=loads, inverter=three, battery=bat)
    )
    loads = (L(1, "sockets", 3000, phase="L1"), L(2, "boiler", 1000, phase="L1"))  # 2500 W
    r = inv(grid="3ph", loads=loads, inverter=three, battery=bat)
    assert "INVERTER_PHASE_OVERLOAD" in codes(r, "error")
    assert "INVERTER_PHASE_IMBALANCE" in codes(r, "warning")


def test_neutral_bond_and_rcd_after_inverter():
    assert "RCD_AFTER_INVERTER" in codes(inv(), "info")
    msg = next(f.message for f in inv().findings if f.code == "RCD_AFTER_INVERTER")
    assert "B/F" in msg
    transformer = InverterSpec(p_ac_w=5000, p_surge_w=10000, transformerless=False, batt_v=48)
    msg = next(
        f.message for f in inv(inverter=transformer).findings if f.code == "RCD_AFTER_INVERTER"
    )
    assert "тип A" in msg
    nobond = InverterSpec(p_ac_w=5000, p_surge_w=10000, bonds_n_pe_offgrid=False, batt_v=48)
    assert "NO_NPE_BOND_OFFGRID" in codes(inv(inverter=nobond), "warning")
    assert "NO_NPE_BOND_OFFGRID" not in codes(inv(inverter=nobond, earthing="TT"))
    assert "NPE_BOND_IN_TT" in codes(inv(earthing="TT"), "warning")
    assert "NPE_BOND_IN_TT" not in codes(inv(earthing="TN-S"))


def test_inverter_plus_generator_scenario():
    kw = dict(scenario="grid_inverter_gen", generator=GEN7, ats=MODULAR2)
    r = inv(**kw)
    assert r.ok and "PRIORITY" in codes(r, "info")
    roles = {c.role for c in r.components}
    assert {"ats", "gen_in_breaker", "inv_in_breaker", "inv_out_breaker", "rcd_inv_out"} <= roles
    r = inv(**{**kw, "ats": AtsSpec("none")})
    assert "PARALLEL_GEN_GRID" in codes(r, "error")
    assert "GENERATOR_MISSING" in codes(inv(scenario="grid_inverter_gen", ats=MODULAR2), "error")


def test_generator_ignored_in_inverter_only_scenario():
    assert "GENERATOR_IGNORED" in codes(inv(generator=GEN7), "warning")


# ------------------------------------------------------------- components
def by_role(r):
    return {c.role: c for c in r.components}


def test_components_for_single_phase_contactor_ats():
    r = run(
        generator=GEN7,
        ats=AtsSpec("contactor", 2, 32, mechanical_interlock=True, electrical_interlock=True),
    )
    c = by_role(r)
    assert (c["ats"].kind, c["ats"].qty, c["ats"].poles, c["ats"].rated_a) == (
        "contactor",
        2,
        2,
        25,
    )
    assert c["gen_in_breaker"].rated_a == 32  # 7 kVA / 230 V = 30.4 A
    assert c["gen_in_breaker"].poles == 2
    assert c["grid_in_breaker"].rated_a == 20  # 16.6 A
    assert c["spd"].poles == 2


def test_components_for_three_phase_generator():
    r = run(
        grid="3ph",
        scenario="grid_gen_ats",
        loads=(L(1, "sockets", 3000, phase="L1"), L(2, "sockets", 3000, phase="L2")),
        generator=GeneratorSpec(12.5, 10, phases=3),
        ats=AtsSpec("modular", 4, 63),
    )
    c = by_role(r)
    assert c["gen_in_breaker"].poles == 4 and c["gen_in_breaker"].rated_a == 20  # 18.04 A
    assert c["ats"].kind == "ats_auto" and c["ats"].poles == 4
    assert c["spd"].poles == 4


def test_components_for_inverter():
    r = inv(battery=BatterySpec(5.12, 48, max_discharge_a=100))
    c = by_role(r)
    assert c["inv_out_breaker"].rated_a == 25  # 5000 W / 230 V = 21.7 A
    assert c["rcd_inv_out"].rated_a == 25 and "B/F" in c["rcd_inv_out"].note
    assert c["battery_dc_breaker"].rated_a == 100  # 79.2 A * 1.25 = 99 A
    assert c["inv_in_breaker"].rated_a == 50  # bypass
    assert c["spd"].kind == "spd"


def test_no_components_without_sources_and_ok_flag():
    r = run()
    assert r.components == () and not r.ok
    assert r.description


@pytest.mark.parametrize("scenario", ["grid_gen_ats", "manual_i0ii", "grid1_gen1"])
def test_every_scenario_has_a_description(scenario):
    assert run(scenario=scenario, generator=GEN7, ats=MODULAR2).description
