from decimal import Decimal

import pytest

from exports.services.bom import BlockInput, Item, SectionInput, aggregate, build_bom, money
from exports.templatetags.exports_extras import uah


def it(pid, price, qty=1, **kw):
    return Item(
        product_id=pid,
        brand=kw.pop("brand", "ABB"),
        sku=kw.pop("sku", f"S{pid}"),
        name="n",
        unit_price=Decimal(price),
        qty=qty,
        **kw,
    )


def test_money_rounds_half_up():
    assert money(Decimal("1.005")) == Decimal("1.01")
    assert money(Decimal("1.004")) == Decimal("1.00")
    assert money(Decimal("2")) == Decimal("2.00")


def test_aggregate_merges_same_product_and_sorts():
    lines = aggregate(
        (
            it(2, "10", sku="B"),
            it(1, "5", brand="IEK", sku="A"),
            it(2, "10", 3),
            it(3, "1", brand="ABB", sku="A"),
        )
    )
    assert [(ln.brand, ln.sku) for ln in lines] == [("ABB", "A"), ("ABB", "B"), ("IEK", "A")]
    b = next(ln for ln in lines if ln.product_id == 2)
    assert b.qty == 4 and b.total == Decimal("40.00")


def test_zero_and_negative_quantities_are_ignored():
    assert aggregate((it(1, "5", 0), it(2, "5", -1))) == ()


def test_totals_add_up_from_printed_values():
    # the printed unit price (0.335 -> 0.34) times the quantity is the line total
    items = tuple(it(i, "0.335", 3) for i in range(1, 4))
    bom = build_bom([SectionInput("boards", "Щиты", (BlockInput("p", "P", items),))])
    lines = bom.sections[0].blocks[0].lines
    assert all(x.unit_price == Decimal("0.34") and x.total == Decimal("1.02") for x in lines)
    assert all(x.unit_price * x.qty == x.total for x in lines)
    assert bom.sections[0].total == bom.total == Decimal("3.06")


def test_sections_and_grand_total():
    bom = build_bom(
        [
            SectionInput(
                "boards",
                "Щиты",
                (BlockInput("a", "A", (it(1, "100", 2),)), BlockInput("b", "B", (it(2, "50.50"),))),
            ),
            SectionInput(
                "solar",
                "Солнечная система",
                (BlockInput("pv", "PV", (it(3, "1000", 10, unit="м"),)),),
            ),
        ],
        missing=("x",),
    )
    assert bom.total_of("boards") == Decimal("250.50")
    assert bom.total_of("solar") == Decimal("10000.00")
    assert bom.total_of("backup") == Decimal("0.00")
    assert bom.total == Decimal("10250.50")
    assert bom.missing == ("x",)
    assert bom.section("solar").blocks[0].lines[0].unit == "м"


def test_unverified_counts_distinct_products():
    a = it(1, "5", needs_verification=True)
    bom = build_bom(
        [
            SectionInput(
                "boards",
                "Щиты",
                (BlockInput("a", "A", (a, a)), BlockInput("b", "B", (a, it(2, "1")))),
            ),
        ]
    )
    assert bom.unverified == 1


def test_empty_bom():
    bom = build_bom([SectionInput("boards", "Щиты", ())])
    assert bom.total == Decimal("0.00") and bom.unverified == 0


@pytest.mark.parametrize(
    "value,text",
    [
        (Decimal("0"), "0,00"),
        (Decimal("999.5"), "999,50"),
        (Decimal("1234.5"), "1 234,50"),
        (Decimal("1234567.891"), "1 234 567,89"),
        (Decimal("-1500"), "-1 500,00"),
    ],
)
def test_uah_format(value, text):
    assert uah(value) == text
