import pytest

from panels.services.layout import (
    PanelArea,
    PlacementSpec,
    RailSpec,
    required_width,
    validate_layout,
)

RAILS = [RailSpec(1, 12), RailSpec(2, 12)]
AREA = PanelArea(210, 300)


def rail(
    key: str, start: int, width: int = 1, rail_id: int = 1, mods: float = 1.0
) -> PlacementSpec:
    return PlacementSpec(
        key=key, din=True, product_modules=mods, rail_id=rail_id, start=start, width=width
    )


def codes(placements: list[PlacementSpec]) -> list[str]:
    return [i.code for i in validate_layout(RAILS, placements, AREA)]


def test_required_width() -> None:
    assert required_width(1.0) == 1
    assert required_width(0.5) == 1
    assert required_width(2.0000000001) == 2
    assert required_width(3.5) == 4
    assert required_width(0) == 0


def test_valid_layout() -> None:
    assert codes([rail("a", 0), rail("b", 1, 3, mods=3), rail("c", 0, rail_id=2)]) == []


def test_adjacent_is_not_collision_but_overlap_is() -> None:
    assert codes([rail("a", 0, 2, mods=2), rail("b", 2)]) == []
    assert codes([rail("a", 0, 2, mods=2), rail("b", 1)]) == ["collision"]
    assert codes([rail("a", 0, 2, mods=2), rail("b", 0)]) == ["collision"]


def test_same_start_on_different_rails_ok() -> None:
    assert codes([rail("a", 0), rail("b", 0, rail_id=2)]) == []


def test_rail_edges() -> None:
    assert codes([rail("a", 11)]) == []  # last module
    assert codes([rail("a", 12)]) == ["out_of_bounds"]
    assert codes([rail("a", 10, 3, mods=3)]) == ["out_of_bounds"]
    assert codes([rail("a", 9, 3, mods=3)]) == []  # exactly fits to the end
    p = PlacementSpec(key="n", din=True, product_modules=1, rail_id=1, start=-1, width=1)
    assert codes([p]) == ["out_of_bounds"]


def test_width_must_match_product() -> None:
    assert codes([rail("a", 0, 2, mods=1.0)]) == ["width_mismatch"]
    assert codes([rail("a", 0, 2, mods=1.5)]) == []  # fractional -> ceil


def test_zero_width_product_not_placeable() -> None:
    assert "not_placeable" in codes([rail("a", 0, 0, mods=0)])


def test_unknown_rail() -> None:
    assert codes([rail("a", 0, rail_id=99)]) == ["unknown_rail"]


def test_non_din_on_rail_and_din_on_panel() -> None:
    nd = PlacementSpec(key="a", din=False, product_modules=1, rail_id=1, start=0, width=1)
    assert "non_din_on_rail" in codes([nd])
    din = PlacementSpec(key="b", din=True, product_modules=1, x_mm=0, y_mm=0, w_mm=10, h_mm=10)
    assert codes([din]) == ["din_off_rail"]


def panel_item(key: str, x: int, y: int, w: int = 50, h: int = 50) -> PlacementSpec:
    return PlacementSpec(key=key, din=False, product_modules=0, x_mm=x, y_mm=y, w_mm=w, h_mm=h)


def test_panel_items() -> None:
    assert codes([panel_item("a", 0, 0)]) == []
    assert codes([panel_item("a", 160, 250)]) == []  # touches the edge exactly
    assert codes([panel_item("a", 161, 0)]) == ["out_of_bounds"]
    assert codes([panel_item("a", 0, 251)]) == ["out_of_bounds"]
    assert codes([panel_item("a", 0, 0), panel_item("b", 50, 0)]) == []  # adjacent
    assert codes([panel_item("a", 0, 0), panel_item("b", 49, 49)]) == ["collision"]


def test_panel_item_geometry_and_missing_panel() -> None:
    bad = PlacementSpec(key="a", din=False, product_modules=0, x_mm=0, y_mm=0)
    assert codes([bad]) == ["missing_geometry"]
    zero = panel_item("a", 0, 0, w=0)
    assert codes([zero]) == ["missing_geometry"]
    res = validate_layout(RAILS, [panel_item("a", 0, 0)], PanelArea())
    assert [i.code for i in res] == ["no_mounting_panel"]


def test_issue_points_to_both_items() -> None:
    issue = validate_layout(RAILS, [rail("a", 0), rail("b", 0)], AREA)[0]
    assert (issue.key, issue.other_key) == ("b", "a")


def test_duplicate_keys_rejected() -> None:
    with pytest.raises(ValueError):
        validate_layout(RAILS, [rail("a", 0), rail("a", 1)], AREA)


def test_many_items_in_a_row_no_false_positives() -> None:
    items = [rail(str(i), i) for i in range(12)]
    assert codes(items) == []
    assert codes([*items, rail("x", 5)]) == ["collision"]
