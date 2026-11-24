"""Bill of materials: aggregation and totals. Pure Python, no Django.

Money is ``Decimal`` in UAH including VAT; line totals are rounded to kopecks (half up) and
section totals are sums of the rounded line totals, so a printed column always adds up.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

KOPECK = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    return value.quantize(KOPECK, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Item:
    """A product occurrence before aggregation."""

    product_id: int
    brand: str
    sku: str
    name: str
    unit_price: Decimal
    qty: int = 1
    unit: str = "шт"
    needs_verification: bool = False
    note: str = ""


@dataclass(frozen=True)
class Line:
    product_id: int
    brand: str
    sku: str
    name: str
    unit: str
    qty: int
    unit_price: Decimal
    total: Decimal
    needs_verification: bool = False


@dataclass(frozen=True)
class Block:
    """Lines of one panel or one group of equipment."""

    key: str
    title: str
    lines: tuple[Line, ...]
    total: Decimal
    estimated: bool = False  # built from the scheme, the panel itself is not assembled yet


@dataclass(frozen=True)
class BlockInput:
    key: str
    title: str
    items: tuple[Item, ...]
    estimated: bool = False


@dataclass(frozen=True)
class SectionInput:
    key: str  # boards | solar | backup
    title: str
    blocks: tuple[BlockInput, ...]


@dataclass(frozen=True)
class Section:
    key: str
    title: str
    blocks: tuple[Block, ...]
    total: Decimal


@dataclass(frozen=True)
class Bom:
    sections: tuple[Section, ...]
    total: Decimal
    unverified: int = 0  # number of lines with a price that is not verified
    missing: tuple[str, ...] = field(default_factory=tuple)  # components without a catalog item
    currency: str = "UAH"

    def section(self, key: str) -> Section | None:
        return next((s for s in self.sections if s.key == key), None)

    def total_of(self, key: str) -> Decimal:
        s = self.section(key)
        return s.total if s else Decimal("0.00")


def aggregate(items: tuple[Item, ...]) -> tuple[Line, ...]:
    """Merge items of one product (the price of the first occurrence wins), sort by brand/SKU."""
    qty: dict[int, int] = defaultdict(int)
    first: dict[int, Item] = {}
    for it in items:
        if it.qty <= 0:
            continue
        qty[it.product_id] += it.qty
        first.setdefault(it.product_id, it)
    lines = [
        Line(
            product_id=pid,
            brand=it.brand,
            sku=it.sku,
            name=it.name,
            unit=it.unit,
            qty=qty[pid],
            unit_price=money(it.unit_price),
            total=money(money(it.unit_price) * qty[pid]),
            needs_verification=it.needs_verification,
        )
        for pid, it in first.items()
    ]
    return tuple(sorted(lines, key=lambda x: (x.brand.lower(), x.sku, x.product_id)))


def build_bom(sections: list[SectionInput], missing: tuple[str, ...] = ()) -> Bom:
    out: list[Section] = []
    unverified: set[int] = set()
    for s in sections:
        blocks: list[Block] = []
        for b in s.blocks:
            lines = aggregate(b.items)
            unverified.update(ln.product_id for ln in lines if ln.needs_verification)
            blocks.append(
                Block(
                    key=b.key,
                    title=b.title,
                    lines=lines,
                    total=sum((ln.total for ln in lines), Decimal("0.00")),
                    estimated=b.estimated,
                )
            )
        out.append(
            Section(
                key=s.key,
                title=s.title,
                blocks=tuple(blocks),
                total=sum((b.total for b in blocks), Decimal("0.00")),
            )
        )
    return Bom(
        sections=tuple(out),
        total=sum((s.total for s in out), Decimal("0.00")),
        unverified=len(unverified),
        missing=missing,
    )
