from panels.services.autolayout import (
    Device,
    EnclosureSpec,
    Section,
    pack,
    required_with_reserve,
    suggest_enclosure,
    total_modules,
)


def dev(key: str, modules: int) -> Device:
    return Device(key, modules, 1, "mcb")


def sec(*sizes: int, prefix: str = "x") -> Section:
    return Section(tuple(dev(f"{prefix}{i}", n) for i, n in enumerate(sizes)))


def slots(sections: list[Section], caps: list[int]) -> list[tuple[str, int, int]]:
    return [(s.key, s.row, s.start) for s in pack(sections, caps).slots]


def test_sequential_in_one_row() -> None:
    assert slots([sec(3, prefix="a"), sec(2, prefix="b")], [12]) == [("a0", 0, 0), ("b0", 0, 3)]


def test_section_moves_to_next_row_when_it_does_not_fit() -> None:
    res = slots([sec(8, prefix="a"), sec(5, prefix="b")], [12, 12])
    assert res == [("a0", 0, 0), ("b0", 1, 0)]


def test_section_exactly_fills_row() -> None:
    res = slots([sec(8, prefix="a"), sec(4, prefix="b"), sec(1, prefix="c")], [12, 12])
    assert res == [("a0", 0, 0), ("b0", 0, 8), ("c0", 1, 0)]


def test_section_kept_together_across_devices() -> None:
    res = slots([sec(9, prefix="a"), sec(2, 2, 2, prefix="b")], [12, 12])
    assert [r[1] for r in res if r[0].startswith("b")] == [1, 1, 1]


def test_oversized_section_is_split() -> None:
    sections = [sec(5, 5, 5, prefix="a")]  # 15 > 12
    r = pack(sections, [12, 12])
    assert r.ok and r.split_sections == 1
    assert [(s.row, s.start) for s in r.slots] == [(0, 0), (0, 5), (1, 0)]


def test_overflow_when_rows_run_out() -> None:
    r = pack([sec(8, prefix="a"), sec(8, prefix="b")], [12])
    assert not r.ok and r.overflow == ["b0"]


def test_device_wider_than_any_row_overflows() -> None:
    r = pack([sec(13, prefix="a")], [12, 12])
    assert r.overflow == ["a0"]


def test_empty_inputs() -> None:
    assert pack([], [12]).slots == []
    assert pack([sec(1)], []).overflow == ["x0"]


def test_narrow_rows_skipped_for_wide_sections() -> None:
    r = pack([sec(10, prefix="a")], [6, 12])
    assert [(s.row, s.start) for s in r.slots] == [(1, 0)]


def test_reserve_rounding() -> None:
    assert required_with_reserve(0) == 0
    assert required_with_reserve(5) == 6
    assert required_with_reserve(10) == 12  # exactly 12.0, no float noise rounding up
    assert required_with_reserve(11) == 14  # 13.2 -> 14
    assert required_with_reserve(18, 0) == 18
    assert required_with_reserve(20, 50) == 30


def test_total_modules() -> None:
    assert total_modules([sec(2, 3), sec(4)]) == 9


E12 = EnclosureSpec(1, 1, 12, 500)
E24 = EnclosureSpec(2, 2, 12, 900)
E24_CHEAP = EnclosureSpec(3, 2, 12, 800)
E24_SURF = EnclosureSpec(4, 2, 12, 700, ip=65, mounting="surface")
E48 = EnclosureSpec(5, 4, 12, 1500)


def test_suggest_smallest_with_reserve() -> None:
    cands = [E48, E24, E12]
    assert suggest_enclosure([sec(10)], cands) == E12  # 10 -> need 12 -> fits exactly
    assert suggest_enclosure([sec(11)], cands) == E24  # 11 -> need 14
    assert suggest_enclosure([sec(11)], cands, reserve_pct=0) == E12


def test_suggest_cheapest_among_equal() -> None:
    assert suggest_enclosure([sec(5, 5, 5)], [E24, E24_CHEAP]) == E24_CHEAP


def test_suggest_filters_and_none() -> None:
    assert suggest_enclosure([sec(5, 5, 5)], [E24, E24_SURF], mounting="surface") == E24_SURF
    assert suggest_enclosure([sec(5, 5, 5)], [E24, E24_SURF], min_ip=65) == E24_SURF
    assert suggest_enclosure([sec(*[6] * 10)], [E12, E24, E48]) is None
    assert suggest_enclosure([sec(1)], []) is None


def test_suggest_respects_fragmentation() -> None:
    # 3 sections of 7 modules: 21 modules total (need 26) but only one fits per 12-row
    sections = [sec(7, prefix="a"), sec(7, prefix="b"), sec(7, prefix="c")]
    e = EnclosureSpec(9, 3, 12, 1, ip=40)
    assert suggest_enclosure(sections, [e], reserve_pct=0) == e
    tight = EnclosureSpec(10, 2, 14, 1)  # capacity 28 >= 26, rows 14 -> 7+7 per row: 3 sections
    assert suggest_enclosure(sections, [tight]) == tight
    # capacity 26 >= 21, yet a 7-module device cannot straddle rows: third one has no room
    frag = EnclosureSpec(12, 2, 13, 1)
    assert suggest_enclosure(sections, [frag], reserve_pct=0) is None
    # a section wider than a row may be split across rows when each device fits
    narrow = EnclosureSpec(11, 7, 4, 1)
    assert suggest_enclosure([sec(2, 2, 3)], [narrow]) == narrow
