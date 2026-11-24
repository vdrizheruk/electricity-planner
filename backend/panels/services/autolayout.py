"""Pure auto-layout: pack device sections onto DIN rails and pick an enclosure."""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Device:
    key: str
    modules: int
    product_id: int
    kind: str
    group_id: int | None = None


@dataclass(frozen=True)
class Section:
    """Devices that should stay on one row (e.g. an RCD with the breakers behind it)."""

    devices: tuple[Device, ...]

    @property
    def modules(self) -> int:
        return sum(d.modules for d in self.devices)


@dataclass(frozen=True)
class Slot:
    key: str
    row: int
    start: int


@dataclass
class PackResult:
    slots: list[Slot] = field(default_factory=list)
    overflow: list[str] = field(default_factory=list)  # device keys that did not fit
    split_sections: int = 0

    @property
    def ok(self) -> bool:
        return not self.overflow


def total_modules(sections: Sequence[Section]) -> int:
    return sum(s.modules for s in sections)


def pack(sections: Sequence[Section], capacities: Sequence[int]) -> PackResult:
    """Fill rails top to bottom, left to right, without gaps inside a row.

    A section moves to the next row when it does not fit into the rest of the current one
    (and is small enough for a fresh row). A section wider than every row is split.
    """
    res = PackResult()
    row, col = 0, 0
    max_cap = max(capacities, default=0)

    def place(dev: Device) -> None:
        nonlocal row, col
        while row < len(capacities) and col + dev.modules > capacities[row]:
            row, col = row + 1, 0
        if row >= len(capacities) or dev.modules > capacities[row]:
            res.overflow.append(dev.key)
            return
        res.slots.append(Slot(dev.key, row, col))
        col += dev.modules

    for sec in sections:
        if sec.modules <= max_cap:
            # does the whole section fit in the rest of this row? if not, start a new row
            if row < len(capacities) and col > 0 and col + sec.modules > capacities[row]:
                row, col = row + 1, 0
            # skip rows that are too narrow for the whole section
            while row < len(capacities) and sec.modules > capacities[row]:
                row, col = row + 1, 0
        else:
            res.split_sections += 1
        for dev in sec.devices:
            place(dev)
    return res


@dataclass(frozen=True)
class EnclosureSpec:
    id: int
    rows: int
    per_row: int
    price: float
    ip: int = 40
    mounting: str = "flush"

    @property
    def capacity(self) -> int:
        return self.rows * self.per_row


def required_with_reserve(total: int, reserve_pct: int = 20) -> int:
    """Modules needed including the free reserve (20% by default), rounded up."""
    return math.ceil(total * (1 + reserve_pct / 100) - 1e-9)


def fits(sections: Sequence[Section], enclosure: EnclosureSpec, reserve_pct: int) -> bool:
    if enclosure.capacity < required_with_reserve(total_modules(sections), reserve_pct):
        return False
    return pack(sections, [enclosure.per_row] * enclosure.rows).ok


def suggest_enclosure(
    sections: Sequence[Section],
    candidates: Sequence[EnclosureSpec],
    reserve_pct: int = 20,
    mounting: str | None = None,
    min_ip: int = 0,
) -> EnclosureSpec | None:
    """Smallest (then cheapest) enclosure that holds everything with the reserve."""
    ok = [
        c
        for c in candidates
        if (mounting is None or c.mounting == mounting)
        and c.ip >= min_ip
        and fits(sections, c, reserve_pct)
    ]
    return min(ok, key=lambda c: (c.capacity, c.price, c.id), default=None)
