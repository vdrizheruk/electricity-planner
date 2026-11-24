import pytest

from calculations import GroupInput, SystemInput, calculate_project
from calculations.demand import demand_factor, diversity_factor


def g(i: int, t: str, p: float, **kw: object) -> GroupInput:
    return GroupInput(id=i, name=f"g{i}", type=t, power_w=p, **kw)  # type: ignore[arg-type]


def test_demand_and_diversity() -> None:
    assert demand_factor("sockets") == 0.5
    assert demand_factor("boiler") == 1.0
    assert demand_factor("nope") == 0.6
    assert diversity_factor(5) == 1.0
    assert diversity_factor(6) == 0.9


APARTMENT = [
    g(1, "lighting", 800, length_m=25),
    g(2, "sockets", 3000, length_m=20),
    g(3, "kitchen", 3000, length_m=15),
    g(4, "cooker", 7000, length_m=15),
    g(5, "boiler", 2000, length_m=10),
    g(6, "ac", 2500, cos_phi=0.9, length_m=20),
]


def test_apartment_1ph() -> None:
    res = calculate_project(APARTMENT, SystemInput(main_breaker_a=63))
    by = {r.group_id: r for r in res.groups}
    assert (by[1].breaker_a, by[1].curve, by[1].cable_mm2) == (10, "B", 1.5)
    assert (by[2].breaker_a, by[2].cable_mm2, by[2].protection) == (16, 2.5, "rcd")
    assert (by[3].breaker_a, by[3].curve) == (16, "C")
    assert (by[4].breaker_a, by[4].cable_mm2, by[4].protection) == (32, 4.0, "rcbo")
    assert (by[5].breaker_a, by[5].protection) == (10, "rcbo")
    assert (by[6].breaker_a, by[6].curve) == (16, "C")
    assert all(r.voltage_drop_pct <= 5.0 for r in by.values())
    assert by[1].voltage_drop_pct <= 3.0
    # 3 individual RCBOs + one shared RCD for sockets + kitchen
    shared = [r for r in res.rcds if len(r.group_ids) > 1]
    assert len(shared) == 1 and shared[0].group_ids == (2, 3) and shared[0].rating_a == 25
    assert len(res.rcds) == 4
    # demand: 6 groups -> Ko 0.9
    assert res.demand.diversity == 0.9
    assert res.demand.design_current_a == pytest.approx(52.29, abs=0.01)
    assert res.demand.main_ok and res.ok


def test_main_breaker_overload_is_error() -> None:
    res = calculate_project(APARTMENT, SystemInput(main_breaker_a=32))
    assert not res.demand.main_ok and not res.ok
    assert any(f.code == "main_breaker_overload" for f in res.findings)


def test_selectivity_warning() -> None:
    res = calculate_project(APARTMENT, SystemInput(main_breaker_a=40))
    warn = [f for f in res.findings if f.code == "selectivity"]
    assert [f.group_id for f in warn] == [4]  # 40/32 < 1.6


def test_group_too_large_warning_and_split_reco() -> None:
    res = calculate_project([g(1, "sockets", 5000)], SystemInput(main_breaker_a=40))
    assert any(f.code == "group_too_large" for f in res.findings)
    assert res.groups[0].breaker_a == 25


def test_three_phase_balance_and_flag() -> None:
    groups = [g(i, "sockets", 2000) for i in range(1, 4)] + [g(4, "boiler", 6000)]
    res = calculate_project(groups, SystemInput(grid="3ph", main_breaker_a=40))
    assert set(r.phase for r in res.groups) <= {"L1", "L2", "L3"}
    assert res.phases.imbalance_pct > 15 and any(f.code == "phase_imbalance" for f in res.findings)


def test_three_phase_group() -> None:
    res = calculate_project(
        [g(1, "ac", 9000, phase="3ph", cos_phi=0.9)], SystemInput(grid="3ph", main_breaker_a=40)
    )
    r = res.groups[0]
    assert r.phase == "3ph" and r.ib_a == pytest.approx(14.43, abs=0.01)
    assert r.breaker_a == 16 and r.cable_mm2 == 2.5
    assert res.rcds[0].poles == 4
    assert res.phases.imbalance_pct == pytest.approx(0.0)


def test_rcd_not_shared_between_backed_up_and_regular() -> None:
    groups = [g(1, "sockets", 1000), g(2, "sockets", 1000, backed_up=True)]
    res = calculate_project(groups, SystemInput())
    assert len(res.rcds) == 2
    assert {r.backed_up for r in res.rcds} == {False, True}


def test_rcd_split_by_phase() -> None:
    groups = [g(1, "sockets", 1000, phase="L1"), g(2, "sockets", 1000, phase="L2")]
    res = calculate_project(groups, SystemInput(grid="3ph"))
    assert len(res.rcds) == 2 and {r.phase for r in res.rcds} == {"L1", "L2"}


def test_wet_lighting_gets_rcd_dry_does_not() -> None:
    groups = [g(1, "lighting", 300), g(2, "lighting", 300, wet_zone=True)]
    res = calculate_project(groups, SystemInput())
    by = {r.group_id: r for r in res.groups}
    assert by[1].protection == "mcb" and by[1].rcd_ma is None
    assert by[2].protection == "rcd" and by[2].rcd_ma == 30


def test_unsolvable_group_reported_not_raised() -> None:
    res = calculate_project(
        [g(1, "sockets", 1000, length_m=5000), g(2, "sockets", 1000)], SystemInput()
    )
    assert [r.group_id for r in res.groups] == [2]
    assert any(f.code == "cable_not_found" and f.group_id == 1 for f in res.findings)
    assert not res.ok


def test_too_large_load_reported() -> None:
    res = calculate_project([g(1, "other", 40000)], SystemInput(main_breaker_a=63))
    assert any(f.code == "breaker_too_large" for f in res.findings)
    assert res.groups == []


def test_empty_project() -> None:
    res = calculate_project([], SystemInput())
    assert res.groups == [] and res.rcds == [] and res.demand.design_current_a == 0
    assert res.demand.main_ok and res.ok


@pytest.mark.parametrize(
    "bad",
    [
        g(1, "nope", 100),
        g(1, "sockets", 0),
        g(1, "sockets", 100, cos_phi=0.05),
        g(1, "sockets", 100, length_m=-1),
        g(1, "sockets", 100, phase="3ph"),
    ],
)
def test_invalid_input(bad: GroupInput) -> None:
    with pytest.raises(ValueError):
        calculate_project([bad], SystemInput())


def test_duplicate_ids() -> None:
    with pytest.raises(ValueError):
        calculate_project([g(1, "sockets", 100), g(1, "sockets", 100)], SystemInput())


def test_derating_changes_cable() -> None:
    groups = [g(1, "kitchen", 5500, length_m=5)]  # Ib 23.9 -> In 25
    base = calculate_project(groups, SystemInput(main_breaker_a=63))
    hot = calculate_project(groups, SystemInput(main_breaker_a=63, derating=0.8))
    assert base.groups[0].cable_mm2 == 2.5 and hot.groups[0].cable_mm2 == 4.0
