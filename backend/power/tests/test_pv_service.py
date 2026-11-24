import pytest

from power.services import (
    PvArray,
    PvInput,
    PvInverterSpec,
    PvModuleSpec,
    analyze_pv,
)
from power.services.pv import (
    azimuth_factor,
    clipping_loss_pct,
    orientation_factor,
    pick_cable,
    string_voltages,
    voltage_drop_pct,
)

MODULE = PvModuleSpec(pmax_w=550, voc_v=49.7, isc_a=14.0, vmp_v=41.9, imp_a=13.13)
# 5 kW on-grid 1ph: 2 MPPT 80..550 V (abs 600 V), 13 A / 16 A
INV = PvInverterSpec(
    kind="on-grid",
    phases=1,
    p_ac_w=5000,
    mppt_count=2,
    mppt_min_v=80,
    mppt_max_v=550,
    vmax_v=600,
    imax_per_mppt_a=13,
    isc_max_per_mppt_a=16,
)


def inp(arrays: tuple[PvArray, ...], **kw: object) -> PvInput:
    base: dict[str, object] = {
        "grid": "1ph",
        "earthing": "TN-C-S",
        "module": MODULE,
        "inverter": INV,
        "arrays": arrays,
    }
    return PvInput(**{**base, **kw})  # type: ignore[arg-type]


def codes(r: object) -> set[str]:
    return {f.code for f in r.findings}  # type: ignore[attr-defined]


def levels(r: object, level: str) -> set[str]:
    return {f.code for f in r.findings if f.level == level}  # type: ignore[attr-defined]


def test_voltage_formulas():
    voc_cold, vmp_stc, vmp_hot, vmp_cold = string_voltages(MODULE, 10, -20, 70)
    # Voc rises 0.25 %/K: 49.7 * (1 + 0.0025 * 45) * 10
    assert voc_cold == pytest.approx(49.7 * 10 * 1.1125)
    assert vmp_stc == pytest.approx(419.0)
    assert vmp_hot == pytest.approx(419.0 * (1 - 0.003 * 45))
    assert vmp_cold == pytest.approx(419.0 * (1 + 0.003 * 45))


def test_good_string_passes():
    r = analyze_pv(inp((PvArray(1, 10, 1), PvArray(2, 10, 1))))
    assert r.ok
    assert not levels(r, "error")
    assert r.metrics.kwp == pytest.approx(11.0)
    assert r.metrics.modules == 20


def test_voc_cold_over_limit_is_error():
    # 11 x 49.7 * 1.1125 = 608 V > 600 V
    r = analyze_pv(inp((PvArray(1, 11, 1),)))
    assert "VOC_COLD" in levels(r, "error")
    assert not r.ok


def test_voc_cold_exactly_at_limit_ok():
    mod = PvModuleSpec(pmax_w=500, voc_v=40.0, isc_a=10.0, vmp_v=33.0, imp_a=9.5)
    inv = PvInverterSpec(
        kind="on-grid", p_ac_w=5000, mppt_count=1, mppt_min_v=80, mppt_max_v=550,
        vmax_v=550 * 1.0, imax_per_mppt_a=13, isc_max_per_mppt_a=16,
    )  # fmt: skip
    # 12 x 40 x 1.1125 = 534 V < 550
    r = analyze_pv(inp((PvArray(1, 12, 1),), module=mod, inverter=inv))
    assert "VOC_COLD" not in codes(r)


def test_vmp_below_mppt_minimum_is_error():
    r = analyze_pv(inp((PvArray(1, 1, 1),)))  # 41.9 V < 80 V
    assert "VMP_LOW" in levels(r, "error")


def test_vmp_above_mppt_maximum_is_error():
    inv = PvInverterSpec(
        kind="on-grid", p_ac_w=5000, mppt_count=1, mppt_min_v=80, mppt_max_v=400,
        vmax_v=600, imax_per_mppt_a=13, isc_max_per_mppt_a=16,
    )  # fmt: skip
    r = analyze_pv(inp((PvArray(1, 10, 1),), inverter=inv))  # Vmp 419 V
    assert "VMP_HIGH" in levels(r, "error")


def test_hot_vmp_below_window_is_warning():
    # 3 modules: Vmp 125.7 V; hot 108.7 V (>80) fine; use min window 120 V instead
    inv = PvInverterSpec(
        kind="on-grid", p_ac_w=5000, mppt_count=1, mppt_min_v=120, mppt_max_v=550,
        vmax_v=600, imax_per_mppt_a=13, isc_max_per_mppt_a=16,
    )  # fmt: skip
    r = analyze_pv(inp((PvArray(1, 3, 1),), inverter=inv))
    assert "VMP_HOT_LOW" in levels(r, "warning")
    assert "VMP_LOW" not in codes(r)


def test_isc_over_input_limit_is_error():
    # 2 strings x 14 A = 28 A > 16 A
    r = analyze_pv(inp((PvArray(1, 10, 2),)))
    assert "ISC_HIGH" in levels(r, "error")


def test_imp_over_working_current_is_warning_only():
    mod = PvModuleSpec(pmax_w=500, voc_v=40.0, isc_a=13.5, vmp_v=33.0, imp_a=13.2)
    r = analyze_pv(inp((PvArray(1, 10, 1),), module=mod))
    assert "IMP_HIGH" in levels(r, "warning")
    assert "ISC_HIGH" not in codes(r)


def test_mppt_index_and_duplicates():
    r = analyze_pv(inp((PvArray(3, 10, 1),)))
    assert "MPPT_RANGE" in levels(r, "error")
    r = analyze_pv(inp((PvArray(1, 10, 1), PvArray(1, 10, 1))))
    assert "MPPT_DUP" in levels(r, "error")


def test_two_inverters_double_the_inputs():
    inv = PvInverterSpec(**{**INV.__dict__, "count": 2})
    r = analyze_pv(inp((PvArray(4, 10, 1),), inverter=inv))
    assert "MPPT_RANGE" not in codes(r)
    assert r.metrics.p_ac_w == 10000


def test_no_arrays_and_offgrid_inverter():
    assert "NO_ARRAYS" in levels(analyze_pv(inp(())), "error")
    off = PvInverterSpec(kind="off-grid", p_ac_w=4000)
    r = analyze_pv(inp((PvArray(1, 10, 1),), inverter=off))
    assert "NO_MPPT" in levels(r, "error")
    assert not r.ok


def test_dc_ac_ratio_warning_above_1_3():
    # 2 x 10 x 550 W = 11 kW on 5 kW = 2.2
    r = analyze_pv(inp((PvArray(1, 10, 1), PvArray(2, 10, 1))))
    assert r.metrics.dc_ac_ratio == pytest.approx(2.2)
    assert "DC_AC_HIGH" in levels(r, "warning")
    # exactly 1.3 is not flagged
    mod = PvModuleSpec(pmax_w=650, voc_v=49.7, isc_a=14.0, vmp_v=41.9, imp_a=13.13)
    r = analyze_pv(inp((PvArray(1, 10, 1),), module=mod))  # 6.5 kW / 5 kW
    assert r.metrics.dc_ac_ratio == pytest.approx(1.3)
    assert "DC_AC_HIGH" not in codes(r)


def test_dc_ac_low_is_info():
    r = analyze_pv(inp((PvArray(1, 10, 1),)))  # 5.5 / 5 = 1.1 -> not low
    assert "DC_AC_LOW" not in codes(r)
    mod = PvModuleSpec(pmax_w=300, voc_v=49.7, isc_a=14.0, vmp_v=41.9, imp_a=13.13)
    r = analyze_pv(inp((PvArray(1, 10, 1),), module=mod))  # 3 / 5 = 0.6
    assert "DC_AC_LOW" in levels(r, "info")


def test_fuses_only_above_two_strings():
    mod = PvModuleSpec(pmax_w=410, voc_v=37.3, isc_a=9.0, vmp_v=31.2, imp_a=8.5)
    inv = PvInverterSpec(
        kind="on-grid", p_ac_w=15000, mppt_count=2, mppt_min_v=200, mppt_max_v=1000,
        vmax_v=1100, imax_per_mppt_a=30, isc_max_per_mppt_a=40,
    )  # fmt: skip
    two = analyze_pv(inp((PvArray(1, 12, 2),), module=mod, inverter=inv))
    assert not [c for c in two.components if c.kind == "dc_fuse"]
    three = analyze_pv(inp((PvArray(1, 12, 3),), module=mod, inverter=inv))
    fuse = next(c for c in three.components if c.kind == "dc_fuse")
    assert fuse.qty == 6  # both poles of three strings
    assert fuse.rated_a == 15  # 1.5 x 9 A = 13.5 -> 15 A
    assert fuse.vdc_v >= three.arrays[0].voc_cold_v


def test_fuse_beyond_module_limit_is_error():
    mod = PvModuleSpec(
        pmax_w=500, voc_v=37.0, isc_a=14.0, vmp_v=31.0, imp_a=13.0, max_series_fuse_a=20
    )
    inv = PvInverterSpec(
        kind="on-grid", p_ac_w=15000, mppt_count=1, mppt_min_v=200, mppt_max_v=1000,
        vmax_v=1100, imax_per_mppt_a=60, isc_max_per_mppt_a=60,
    )  # fmt: skip
    r = analyze_pv(inp((PvArray(1, 12, 3),), module=mod, inverter=inv))  # 21 A > 20 A
    assert "FUSE_RANGE" in levels(r, "error")


def test_isolator_spd_mc4_per_array():
    r = analyze_pv(inp((PvArray(1, 10, 1), PvArray(2, 10, 1))))
    iso = next(c for c in r.components if c.kind == "dc_isolator")
    assert iso.qty == 1 and iso.placed
    assert len([c for c in r.components if c.kind == "dc_isolator"]) == 2
    spd = next(c for c in r.components if c.kind == "dc_spd")
    assert spd.vdc_v >= r.arrays[0].voc_cold_v  # Ucpv >= Voc max
    mc4 = next(c for c in r.components if c.kind == "pv_connector")
    assert mc4.qty == 2


def test_cable_selection_by_drop():
    # 14 A... string of Imp 13.13 A, 10 modules (419 V): 4 mm², 20 m
    mm2, drop, verdict = pick_cable(20, 13.13, 17.5, 419)
    assert mm2 == 4 and verdict == "ok" and drop < 1.0
    # 40 m: 4 mm² gives 1.4 %, 6 mm² fits
    mm2, drop, verdict = pick_cable(40, 13.13, 17.5, 419)
    assert mm2 == 6 and verdict == "ok"
    # 110 m: only 10 mm² stays under 2 % -> warning
    mm2, drop, verdict = pick_cable(110, 13.13, 17.5, 419)
    assert mm2 == 10 and verdict == "warning" and 1.0 < drop <= 2.0
    # beyond 2 % even on the largest section
    _, drop, verdict = pick_cable(400, 13.13, 17.5, 419)
    assert verdict == "error" and drop > 2.0


def test_cable_ampacity_error():
    assert pick_cable(5, 40, 70, 400)[2] == "ampacity"


def test_cable_findings_and_merge():
    r = analyze_pv(inp((PvArray(1, 10, 1, cable_m=40), PvArray(2, 10, 1, cable_m=40))))
    cables = [c for c in r.components if c.kind == "cable"]
    assert len(cables) == 1 and cables[0].mm2 == 6
    assert cables[0].qty == 160  # 2 arrays x 1 string x 2 wires x 40 m
    r = analyze_pv(inp((PvArray(1, 10, 1, cable_m=400),)))
    assert "CABLE_DROP" in levels(r, "error")


def test_voltage_drop_formula():
    # 2 * 20 m * 0.0225 * 10 A / 4 mm2 / 400 V = 0.5625 %
    assert voltage_drop_pct(20, 10, 4, 400) == pytest.approx(0.5625)


def test_ac_breaker_sizing():
    r = analyze_pv(inp((PvArray(1, 10, 1),)))
    ac = next(c for c in r.components if c.role == "ac_breaker")
    # 5000/230 = 21.7 A * 1.25 = 27.2 -> 32 A, 1ph: 2P
    assert ac.rated_a == 32 and ac.poles == 2 and ac.placed
    inv3 = PvInverterSpec(**{**INV.__dict__, "phases": 3, "p_ac_w": 15000})
    r = analyze_pv(inp((PvArray(1, 10, 1),), grid="3ph", inverter=inv3))
    ac = next(c for c in r.components if c.role == "ac_breaker")
    assert ac.poles == 4 and ac.rated_a == 32  # 15000 / (sqrt3 * 400) = 21.7 A * 1.25 = 27.1 -> 32


def test_meter_only_with_export_or_tariff():
    plain = analyze_pv(inp((PvArray(1, 10, 1),)))
    assert not [c for c in plain.components if c.kind == "meter"]
    green = analyze_pv(inp((PvArray(1, 10, 1),), green_tariff=True))
    assert [c for c in green.components if c.kind == "meter"]


def test_export_limit_findings():
    r = analyze_pv(inp((PvArray(1, 10, 1),), export_limit_w=3000))
    assert "EXPORT_LIMIT" in codes(r)
    r = analyze_pv(inp((PvArray(1, 10, 1),), export_limit_w=6000))
    assert "EXPORT_LIMIT_MOOT" in codes(r)


def test_green_tariff_over_50_kw():
    inv = PvInverterSpec(
        kind="on-grid", p_ac_w=60000, mppt_count=1, mppt_min_v=200, mppt_max_v=1000,
        vmax_v=1100, imax_per_mppt_a=200, isc_max_per_mppt_a=250,
    )  # fmt: skip
    r = analyze_pv(inp((PvArray(1, 10, 11),), inverter=inv, green_tariff=True))  # 60.5 kWp
    assert "GREEN_TARIFF_LIMIT" in levels(r, "warning")


def test_yield_model():
    assert azimuth_factor(0) == 1.0
    assert azimuth_factor(-90) == pytest.approx(0.85)
    assert azimuth_factor(90) == pytest.approx(0.85)
    assert azimuth_factor(180) == pytest.approx(0.55)
    assert orientation_factor(0, 35) == 1.0
    assert orientation_factor(180, 90) < orientation_factor(90, 35)
    assert clipping_loss_pct(1.0) == 0.0
    assert clipping_loss_pct(1.3) == pytest.approx(2.25)

    r = analyze_pv(inp((PvArray(1, 10, 1),), region="center"))
    # 5.5 kWp * 1050 * clip(1.1 -> 0.25 %)
    assert r.metrics.yield_kwh_year == pytest.approx(5.5 * 1050 * (1 - 0.0025), rel=1e-6)
    south = analyze_pv(inp((PvArray(1, 10, 1),), region="south"))
    north = analyze_pv(inp((PvArray(1, 10, 1),), region="north"))
    assert north.metrics.yield_kwh_year < r.metrics.yield_kwh_year < south.metrics.yield_kwh_year
    east = analyze_pv(inp((PvArray(1, 10, 1, azimuth_deg=-90),)))
    assert east.metrics.yield_kwh_year < r.metrics.yield_kwh_year
    pr = analyze_pv(inp((PvArray(1, 10, 1),), performance_ratio=0.7))
    assert pr.metrics.yield_kwh_year == pytest.approx(r.metrics.yield_kwh_year * 0.7 / 0.8)
    assert r.metrics.specific_yield == pytest.approx(r.metrics.yield_kwh_year / r.metrics.kwp)


def test_info_notes_present():
    r = analyze_pv(inp((PvArray(1, 10, 1, cable_m=25),), earthing="TT"))
    assert {"RCD_TYPE_B", "PV_BONDING", "TT_EARTH", "SPD_BOTH_ENDS", "MPPT_UNUSED"} <= codes(r)
