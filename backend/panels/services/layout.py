"""Pure layout validation for board editors (no Django imports).

DIN-mountable devices sit on rails (``rail_id`` + ``start`` + ``width`` in modules,
1 module = 17.5 mm). Everything else sits on the mounting panel as a rectangle in mm.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class RailSpec:
    id: int
    capacity: int  # modules per rail


@dataclass(frozen=True)
class PanelArea:
    """Mounting panel size, mm. ``None`` means the enclosure has no mounting panel."""

    width_mm: int | None = None
    height_mm: int | None = None


@dataclass(frozen=True)
class PlacementSpec:
    key: str  # unique id of the placement inside the request (e.g. "12" or "new:1")
    din: bool  # product is DIN-mountable
    product_modules: float  # product width in modules (0 = not placeable on a rail)
    rail_id: int | None = None
    start: int | None = None
    width: int = 0
    x_mm: int | None = None
    y_mm: int | None = None
    w_mm: int | None = None
    h_mm: int | None = None


@dataclass(frozen=True)
class Issue:
    code: str
    message: str
    key: str
    other_key: str | None = None


def required_width(product_modules: float) -> int:
    """Modules a product occupies on a rail: ceil of its (possibly fractional) width."""
    return math.ceil(product_modules - 1e-9)


def validate_layout(
    rails: Sequence[RailSpec], placements: Sequence[PlacementSpec], area: PanelArea
) -> list[Issue]:
    issues: list[Issue] = []
    keys = [p.key for p in placements]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate placement keys")
    capacity = {r.id: r.capacity for r in rails}
    on_rail: dict[int, list[PlacementSpec]] = {}
    on_panel: list[PlacementSpec] = []

    for p in placements:
        if p.rail_id is not None:
            issues.extend(_check_rail_item(p, capacity))
            if p.rail_id in capacity:
                on_rail.setdefault(p.rail_id, []).append(p)
        else:
            issues.extend(_check_panel_item(p, area))
            on_panel.append(p)

    for rail_items in on_rail.values():
        issues.extend(_collisions_1d(rail_items))
    issues.extend(_collisions_2d(on_panel))
    return issues


def _check_rail_item(p: PlacementSpec, capacity: dict[int, int]) -> list[Issue]:
    out: list[Issue] = []
    if p.rail_id not in capacity:
        return [Issue("unknown_rail", "Рейка не принадлежит этому щиту", p.key)]
    if not p.din:
        out.append(Issue("non_din_on_rail", "Устройство не для DIN-рейки", p.key))
    need = required_width(p.product_modules)
    if need < 1:
        out.append(Issue("not_placeable", "Изделие не имеет модульной ширины", p.key))
    elif p.width != need:
        out.append(
            Issue(
                "width_mismatch", f"Ширина {p.width} мод. не равна ширине изделия ({need})", p.key
            )
        )
    if p.start is None or p.start < 0:
        out.append(Issue("out_of_bounds", "Позиция вне рейки", p.key))
    elif p.start + max(p.width, 1) > capacity[p.rail_id]:
        out.append(Issue("out_of_bounds", "Элемент выходит за край рейки", p.key))
    return out


def _check_panel_item(p: PlacementSpec, area: PanelArea) -> list[Issue]:
    if p.din:
        return [Issue("din_off_rail", "DIN-устройство нужно ставить на рейку", p.key)]
    geom = (p.x_mm, p.y_mm, p.w_mm, p.h_mm)
    if any(v is None for v in geom) or (p.w_mm or 0) <= 0 or (p.h_mm or 0) <= 0:
        return [Issue("missing_geometry", "Нужны x, y, ширина и высота (мм)", p.key)]
    if area.width_mm is None or area.height_mm is None:
        return [Issue("no_mounting_panel", "В корпусе нет монтажной панели", p.key)]
    assert p.x_mm is not None and p.y_mm is not None and p.w_mm is not None and p.h_mm is not None
    if (
        p.x_mm < 0
        or p.y_mm < 0
        or p.x_mm + p.w_mm > area.width_mm
        or p.y_mm + p.h_mm > area.height_mm
    ):
        return [Issue("out_of_bounds", "Элемент выходит за монтажную панель", p.key)]
    return []


def _collisions_1d(items: Sequence[PlacementSpec]) -> list[Issue]:
    valid = [p for p in items if p.start is not None and p.start >= 0 and p.width > 0]
    valid.sort(key=lambda p: (p.start or 0, p.key))
    issues: list[Issue] = []
    for i, a in enumerate(valid):
        assert a.start is not None
        a_end = a.start + a.width
        for b in valid[i + 1 :]:
            assert b.start is not None
            if b.start >= a_end:
                break
            issues.append(Issue("collision", "Элементы пересекаются на рейке", b.key, a.key))
    return issues


def _collisions_2d(items: Sequence[PlacementSpec]) -> list[Issue]:
    rects = [
        p
        for p in items
        if None not in (p.x_mm, p.y_mm, p.w_mm, p.h_mm) and (p.w_mm or 0) > 0 and (p.h_mm or 0) > 0
    ]
    issues: list[Issue] = []
    for i, a in enumerate(rects):
        for b in rects[i + 1 :]:
            assert a.x_mm is not None and a.y_mm is not None
            assert a.w_mm is not None and a.h_mm is not None
            assert b.x_mm is not None and b.y_mm is not None
            assert b.w_mm is not None and b.h_mm is not None
            if (
                a.x_mm < b.x_mm + b.w_mm
                and b.x_mm < a.x_mm + a.w_mm
                and a.y_mm < b.y_mm + b.h_mm
                and b.y_mm < a.y_mm + a.h_mm
            ):
                issues.append(Issue("collision", "Элементы пересекаются на панели", b.key, a.key))
    return issues
