import math

import pytest

from calculations.breaker import NoStandardSizeError, next_standard, select_breaker, select_curve
from calculations.cable import (
    CableSelectionError,
    ampacity,
    select_cable,
    voltage_drop_pct,
)
from calculations.current import design_current
from calculations.selectivity import breaker_selectivity_ok, rcd_selectivity_ok


def test_design_current_1ph() -> None:
    assert design_current(3500, 1.0, False) == pytest.approx(15.217, abs=1e-3)
    assert design_current(2300, 0.5, False) == pytest.approx(20.0)


def test_design_current_3ph() -> None:
    assert design_current(11000, 0.95, True) == pytest.approx(16.713, abs=1e-3)
    assert design_current(400 * math.sqrt(3) * 10, 1.0, True) == pytest.approx(10.0)


@pytest.mark.parametrize("power,cos", [(0, 1.0), (-5, 1.0), (100, 0.05), (100, 1.01)])
def test_design_current_invalid(power: float, cos: float) -> None:
    with pytest.raises(ValueError):
        design_current(power, cos, False)


@pytest.mark.parametrize(
    "ib,expected",
    [(0.1, 6), (6.0, 6), (6.01, 10), (15.2, 16), (16.0, 16), (16.0001, 20), (125.0, 125)],
)
def test_next_standard(ib: float, expected: int) -> None:
    assert next_standard(ib) == expected


def test_next_standard_overflow() -> None:
    with pytest.raises(NoStandardSizeError):
        next_standard(125.1)


def test_select_breaker_practical_minimums() -> None:
    assert select_breaker(2.6, "lighting") == 10
    assert select_breaker(2.6, "sockets") == 16
    assert select_breaker(8.7, "boiler") == 10
    assert select_breaker(30.4, "cooker") == 32
    assert select_breaker(5.0, "unknown-type") == 10


def test_select_curve() -> None:
    assert select_curve("lighting") == "B"
    assert select_curve("ac") == "C"
    assert select_curve("whatever") == "C"


def test_voltage_drop_1ph_formula() -> None:
    assert voltage_drop_pct(16, 60, 2.5, 1.0, False) == pytest.approx(7.513, abs=1e-3)
    assert voltage_drop_pct(16, 60, 4.0, 1.0, False) == pytest.approx(4.696, abs=1e-3)


def test_voltage_drop_3ph_formula() -> None:
    # sqrt3*0.0225*50*20/(4*400)*100
    assert voltage_drop_pct(20, 50, 4.0, 1.0, True) == pytest.approx(2.435, abs=1e-3)


def test_voltage_drop_invalid() -> None:
    with pytest.raises(ValueError):
        voltage_drop_pct(10, -1, 2.5, 1.0, False)


def test_ampacity_tables_and_derating() -> None:
    assert ampacity(2.5, False) == 27
    assert ampacity(2.5, True) == 25
    assert ampacity(2.5, False, 0.8) == pytest.approx(21.6)


def _cable(**kw: object) -> tuple[float, float]:
    args: dict[str, object] = dict(
        group_type="sockets",
        breaker_a=16,
        ib_a=15.2,
        length_m=20,
        cos_phi=1.0,
        three_phase=False,
        dv_limit_pct=5.0,
    )
    args.update(kw)
    return select_cable(**args)  # type: ignore[arg-type]


def test_cable_minimums_by_type() -> None:
    assert _cable(group_type="lighting", breaker_a=10, ib_a=3.0, length_m=10)[0] == 1.5
    assert _cable()[0] == 2.5
    assert _cable(group_type="cooker", breaker_a=32, ib_a=30.4, length_m=15)[0] == 4.0


def test_cable_upsized_for_ampacity() -> None:
    # In=40 needs Iz>=40: 4 mm² is 36 A, 6 mm² is 46 A
    assert _cable(group_type="cooker", breaker_a=40, ib_a=39.1, length_m=10)[0] == 6.0


def test_cable_upsized_for_voltage_drop() -> None:
    s, dv = _cable(breaker_a=16, ib_a=16.0, length_m=60)
    assert s == 4.0 and dv == pytest.approx(4.696, abs=1e-3)


def test_cable_voltage_drop_boundary_inclusive() -> None:
    # lighting 10 A, 1.5 mm²: dU = 0.13043 * L  -> exactly 3.0% at L=23
    s, dv = _cable(group_type="lighting", breaker_a=10, ib_a=10.0, length_m=23, dv_limit_pct=3.0)
    assert s == 1.5 and dv == pytest.approx(3.0)
    s2, _ = _cable(group_type="lighting", breaker_a=10, ib_a=10.0, length_m=23.1, dv_limit_pct=3.0)
    assert s2 == 2.5


def test_cable_derating() -> None:
    assert _cable(group_type="kitchen", breaker_a=25, ib_a=24.0, length_m=5)[0] == 2.5
    assert _cable(group_type="kitchen", breaker_a=25, ib_a=24.0, length_m=5, derating=0.8)[0] == 4.0


def test_cable_three_phase_uses_3_loaded_table() -> None:
    # 2.5 mm²: 27 A (2 loaded) but 25 A (3 loaded) -> In=25 ok, In=26 not
    assert _cable(three_phase=True, breaker_a=25, ib_a=20.0, length_m=5)[0] == 2.5
    assert _cable(three_phase=True, breaker_a=40, ib_a=20.0, length_m=5, group_type="ac")[0] == 6.0
    # 4 mm² is 33 A with 3 loaded conductors: enough for In=32
    assert _cable(three_phase=True, breaker_a=32, ib_a=20.0, length_m=5, group_type="ac")[0] == 4.0


def test_cable_not_found() -> None:
    with pytest.raises(CableSelectionError):
        _cable(group_type="other", breaker_a=125, ib_a=120.0, length_m=10, three_phase=True)
    with pytest.raises(CableSelectionError):
        _cable(breaker_a=16, ib_a=16.0, length_m=2000)


def test_selectivity() -> None:
    assert breaker_selectivity_ok(32, 20)  # 1.6 exactly
    assert not breaker_selectivity_ok(32, 25)
    assert breaker_selectivity_ok(63, 32)
    assert rcd_selectivity_ok(300, True, 30)
    assert not rcd_selectivity_ok(300, False, 30)
    assert not rcd_selectivity_ok(100, True, 100)
