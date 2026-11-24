from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from catalog.analogs import find_analogs
from catalog.csv_io import COLUMNS, export_csv, import_csv
from catalog.models import Brand, Category, Product, Tier
from catalog.seed_data import build_items


def test_seed_size_and_integrity(seeded):
    n = Product.objects.count()
    assert 150 <= n <= 200
    assert n == len(build_items())
    # all six required brands present with all tiers
    names = set(Brand.objects.values_list("name", flat=True))
    assert {"ABB", "Schneider Electric", "Eaton", "Hager", "IEK", "E.NEXT"} <= names
    assert set(Product.objects.values_list("tier", flat=True)) == {"eco", "mid", "premium"}
    # required domain coverage
    codes = set(Category.objects.filter(products__isnull=False).values_list("code", flat=True))
    assert {
        "inverter",
        "battery",
        "pv_module",
        "dc_fuse",
        "dc_isolator",
        "dc_spd",
        "enclosure",
        "spd",
        "rcd",
        "rcbo",
        "mcb",
        "meter",
        "ats",
    } <= codes


def test_seed_idempotent(seeded):
    from django.core.management import call_command

    before = Product.objects.count()
    call_command("seed_catalog")
    assert Product.objects.count() == before


def test_seed_products_are_valid(seeded):
    for p in Product.objects.all():
        p.full_clean()
        assert p.price > 0
        assert p.needs_verification


def test_seed_pv_module_params_sane(seeded):
    for p in Product.objects.filter(category__code="pv_module"):
        e = p.electrical
        assert e["voc_v"] > e["vmp_v"] > 0
        assert e["isc_a"] > e["imp_a"] > 0
        assert e["beta_voc_pct_per_c"] < 0
        # Pmax within 6% of Vmp*Imp
        assert abs(e["vmp_v"] * e["imp_a"] - e["pmax_w"]) / e["pmax_w"] < 0.06


def test_seed_rcd_30ma_and_fire(seeded):
    assert Product.objects.filter(category__code="rcd", leakage_ma=30, rcd_type="A").exists()
    assert Product.objects.filter(category__code="rcd", leakage_ma=300).exists()


def test_unique_brand_sku(seeded):
    p = Product.objects.first()
    with pytest.raises(IntegrityError):
        Product.objects.create(
            brand=p.brand,
            category=p.category,
            sku=p.sku,
            name="dup",
            price=1,
            price_date="2026-01-01",
        )


def test_poles_validation(seeded):
    p = Product.objects.filter(poles=1).first()
    p.poles = 5
    with pytest.raises(ValidationError):
        p.full_clean()


def test_negative_price_rejected(seeded):
    p = Product.objects.first()
    p.price = Decimal("-1")
    with pytest.raises(ValidationError):
        p.full_clean()


def test_analogs_same_function_other_brands(seeded):
    p = Product.objects.get(brand__name="ABB", sku="S201-C16")
    analogs = list(find_analogs(p))
    assert {a.brand.name for a in analogs} == {
        "Schneider Electric",
        "Hager",
        "Eaton",
        "IEK",
        "E.NEXT",
    }
    assert all(a.rated_a == 16 and a.poles == 1 and a.curve == "C" for a in analogs)
    assert p not in analogs
    # cheapest first
    prices = [a.price for a in analogs]
    assert prices == sorted(prices)


def test_analogs_tier_filter(seeded):
    p = Product.objects.get(brand__name="ABB", sku="S201-C16")
    eco = find_analogs(p, tier=Tier.ECONOMY)
    assert {a.brand.name for a in eco} == {"IEK", "E.NEXT"}
    with pytest.raises(ValueError):
        find_analogs(p, tier="gold")


def test_analogs_null_params_match_null(seeded):
    # RCD analog must not match an RCBO or a breaker (leakage must match)
    rcd = Product.objects.get(brand__name="Hager", sku="CD-2P-40A-30mA-A")
    for a in find_analogs(rcd):
        assert a.category.code == "rcd" and a.leakage_ma == 30


def test_csv_roundtrip(seeded):
    text = export_csv()
    assert text.splitlines()[0].split(",") == COLUMNS
    before = Product.objects.count()
    res = import_csv(text)
    assert res.ok and res.created == 0 and res.updated == before
    assert Product.objects.count() == before


def test_csv_import_creates_and_updates(seeded):
    row = (
        "brand,category,sku,name,price\n"
        "NewBrand,mcb,X-1,Test MCB,99.50\n"
        "ABB,mcb,S201-C16,Renamed,200\n"
    )
    res = import_csv(row)
    assert res.ok and res.created == 1 and res.updated == 1
    assert Product.objects.get(brand__name="ABB", sku="S201-C16").name == "Renamed"
    assert Product.objects.get(sku="X-1").price == Decimal("99.50")


def test_csv_import_all_or_nothing(seeded):
    before = Product.objects.count()
    bad = (
        "brand,category,sku,name,price\n"
        "ABB,mcb,GOOD-1,ok,10\n"
        "ABB,nonexistent,BAD,bad,10\n"
        "ABB,mcb,BAD2,bad,-5\n"
    )
    res = import_csv(bad)
    assert not res.ok and len(res.errors) == 2
    assert "строка 3" in res.errors[0] and "строка 4" in res.errors[1]
    assert Product.objects.count() == before
    assert not Product.objects.filter(sku="GOOD-1").exists()


def test_csv_import_missing_columns(db):
    res = import_csv("brand,sku\nA,1\n")
    assert not res.ok and "category" in res.errors[0]


def test_csv_import_bad_json(seeded):
    res = import_csv('brand,category,sku,name,price,electrical\nABB,mcb,J,j,1,"[1]"\n')
    assert not res.ok
