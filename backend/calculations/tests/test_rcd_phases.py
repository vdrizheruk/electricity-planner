import pytest

from calculations.phases import PhaseLoad, balance, imbalance_pct
from calculations.rcd import RcdCandidate, choose_protection, pack_rcds


def test_protection_choice() -> None:
    assert choose_protection("lighting", 800, False).protection == "mcb"
    p = choose_protection("lighting", 800, True)
    assert (p.protection, p.rcd_ma, p.rcd_type) == ("rcd", 30, "A")
    assert choose_protection("cooker", 7000, False).protection == "rcbo"
    assert choose_protection("sockets", 3500, False).protection == "rcbo"  # boundary
    assert choose_protection("sockets", 3499, False).protection == "rcd"
    assert choose_protection("boiler", 1500, False).protection == "rcbo"
    assert choose_protection("kitchen", 2000, False).rcd_ma == 30


def test_pack_rcds_group_limit() -> None:
    cands = [RcdCandidate(i, 5.0, 16) for i in range(1, 7)]
    bins = pack_rcds(cands, max_groups=4)
    assert [len(b.group_ids) for b in bins] == [4, 2]
    assert bins[0].demand_a == pytest.approx(20.0)
    assert bins[0].rating_a == 25 and bins[1].rating_a == 25


def test_pack_rcds_capacity_split() -> None:
    cands = [RcdCandidate(1, 60.0, 63), RcdCandidate(2, 60.0, 63)]
    bins = pack_rcds(cands, max_groups=4)
    assert len(bins) == 2 and all(b.rating_a == 63 for b in bins)


def test_pack_rcds_rating_not_below_breaker() -> None:
    bins = pack_rcds([RcdCandidate(1, 3.0, 32)], max_groups=4)
    assert bins[0].rating_a == 40  # >= In of the member breaker (32) -> next RCD rating


def test_pack_rcds_invalid() -> None:
    with pytest.raises(ValueError):
        pack_rcds([RcdCandidate(1, 1.0, 16)], max_groups=0)
    with pytest.raises(ValueError):
        pack_rcds([RcdCandidate(1, 150.0, 16)], max_groups=4)


def test_imbalance_pct() -> None:
    assert imbalance_pct([]) == 0.0
    assert imbalance_pct([0.0, 0.0, 0.0]) == 0.0
    assert imbalance_pct([1000, 1000, 1000]) == 0.0
    assert imbalance_pct([1150, 1000, 850]) == pytest.approx(15.0)


def test_balance_greedy_lpt() -> None:
    loads = [PhaseLoad(i, "auto", v) for i, v in enumerate([3000, 3000, 2000, 2000, 2000], 1)]
    res = balance("3ph", loads)
    assert sorted(res.loads_va.values()) == [3000, 4000, 5000]
    assert res.imbalance_pct == pytest.approx(25.0)
    assert res.exceeds_limit


def test_balance_exactly_15_pct_not_flagged() -> None:
    loads = [PhaseLoad(1, "L1", 1150), PhaseLoad(2, "L2", 1000), PhaseLoad(3, "L3", 850)]
    res = balance("3ph", loads)
    assert res.imbalance_pct == pytest.approx(15.0)
    assert not res.exceeds_limit


def test_balance_fixed_and_three_phase_loads() -> None:
    loads = [
        PhaseLoad(1, "L1", 3000),
        PhaseLoad(2, "3ph", 9000),
        PhaseLoad(3, "auto", 1000),
    ]
    res = balance("3ph", loads)
    assert res.assignment == {1: "L1", 2: "3ph", 3: "L2"}
    assert res.loads_va == {"L1": 6000, "L2": 4000, "L3": 3000}


def test_balance_improves_over_greedy() -> None:
    # fixed pre-load on L1; autos must go elsewhere
    loads = [PhaseLoad(1, "L1", 5000)] + [PhaseLoad(i, "auto", 1000) for i in range(2, 8)]
    res = balance("3ph", loads)
    assert res.loads_va["L1"] == 5000
    assert res.loads_va["L2"] == 3000 and res.loads_va["L3"] == 3000


def test_balance_1ph_grid() -> None:
    res = balance("1ph", [PhaseLoad(1, "auto", 100), PhaseLoad(2, "L1", 50)])
    assert res.loads_va == {"L1": 150} and res.imbalance_pct == 0.0 and not res.exceeds_limit


def test_balance_invalid_phases() -> None:
    with pytest.raises(ValueError):
        balance("1ph", [PhaseLoad(1, "3ph", 100)])
    with pytest.raises(ValueError):
        balance("1ph", [PhaseLoad(1, "L2", 100)])
    with pytest.raises(ValueError):
        balance("3ph", [PhaseLoad(1, "L4", 100)])


def test_balance_deterministic() -> None:
    loads = [PhaseLoad(i, "auto", 1000.0) for i in range(1, 10)]
    assert balance("3ph", loads).assignment == balance("3ph", list(reversed(loads))).assignment
