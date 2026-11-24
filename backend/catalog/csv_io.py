"""CSV import/export for the product catalog."""

import csv
import io
import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import QuerySet

from .models import Brand, Category, CategoryCode, Product, Tier

COLUMNS = [
    "brand",
    "category",
    "sku",
    "name",
    "series",
    "tier",
    "rated_a",
    "poles",
    "curve",
    "leakage_ma",
    "rcd_type",
    "modules",
    "width_mm",
    "height_mm",
    "depth_mm",
    "din_mountable",
    "electrical",
    "price",
    "price_date",
    "needs_verification",
]
_REQUIRED = ("brand", "category", "sku", "name", "price")
_BOOL_TRUE = {"1", "true", "yes", "y", "да"}


@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def export_csv(queryset: QuerySet[Product] | None = None) -> str:
    qs = queryset if queryset is not None else Product.objects.all()
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    for p in qs.select_related("brand", "category"):
        writer.writerow(
            {
                "brand": p.brand.name,
                "category": p.category.code,
                "sku": p.sku,
                "name": p.name,
                "series": p.series,
                "tier": p.tier,
                "rated_a": _dec(p.rated_a),
                "poles": "" if p.poles is None else p.poles,
                "curve": p.curve,
                "leakage_ma": "" if p.leakage_ma is None else p.leakage_ma,
                "rcd_type": p.rcd_type,
                "modules": _dec(p.modules),
                "width_mm": "" if p.width_mm is None else p.width_mm,
                "height_mm": "" if p.height_mm is None else p.height_mm,
                "depth_mm": "" if p.depth_mm is None else p.depth_mm,
                "din_mountable": "1" if p.din_mountable else "0",
                "electrical": json.dumps(p.electrical, ensure_ascii=False, sort_keys=True),
                "price": _dec(p.price),
                "price_date": p.price_date.isoformat(),
                "needs_verification": "1" if p.needs_verification else "0",
            }
        )
    return buf.getvalue()


def _dec(value: Decimal | None) -> str:
    return "" if value is None else format(value, "f")


def _opt_int(raw: str) -> int | None:
    return int(raw) if raw.strip() else None


def _opt_dec(raw: str) -> Decimal | None:
    return Decimal(raw.strip().replace(",", ".")) if raw.strip() else None


def import_csv(text: str, *, today: date | None = None) -> ImportResult:
    """Upsert products by (brand, sku). All-or-nothing: any error rolls everything back."""
    result = ImportResult()
    reader = csv.DictReader(io.StringIO(text))
    missing = [c for c in _REQUIRED if c not in (reader.fieldnames or [])]
    if missing:
        result.errors.append(f"Отсутствуют колонки: {', '.join(missing)}")
        return result

    categories = {c.code: c for c in Category.objects.all()}
    default_date = today or date.today()

    with transaction.atomic():
        for line_no, row in enumerate(reader, start=2):
            try:
                created = _import_row(row, categories, default_date)
            except (ValidationError, ValueError, InvalidOperation, KeyError) as exc:
                msg = "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
                result.errors.append(f"строка {line_no}: {msg}")
                continue
            if created:
                result.created += 1
            else:
                result.updated += 1
        if result.errors:
            transaction.set_rollback(True)
            result.created = result.updated = 0
    return result


def _import_row(row: dict[str, Any], categories: dict[str, Category], default_date: date) -> bool:
    get = lambda k: (row.get(k) or "").strip()  # noqa: E731
    for col in _REQUIRED:
        if not get(col):
            raise ValueError(f"пустое поле {col}")
    code = get("category")
    if code not in CategoryCode.values:
        raise ValueError(f"неизвестная категория {code!r}")
    category = categories.get(code)
    if category is None:
        raise ValueError(f"категория {code!r} не создана (выполните seed_catalog)")
    tier = get("tier") or Tier.MIDDLE
    brand_name = get("brand")
    brand, _ = Brand.objects.get_or_create(
        name=brand_name, defaults={"slug": _slug(brand_name), "tier": tier}
    )
    electrical_raw = get("electrical")
    electrical = json.loads(electrical_raw) if electrical_raw else {}
    if not isinstance(electrical, dict):
        raise ValueError("electrical должен быть JSON-объектом")

    values: dict[str, Any] = {
        "category": category,
        "name": get("name"),
        "series": get("series"),
        "tier": tier,
        "rated_a": _opt_dec(get("rated_a")),
        "poles": _opt_int(get("poles")),
        "curve": get("curve"),
        "leakage_ma": _opt_int(get("leakage_ma")),
        "rcd_type": get("rcd_type"),
        "modules": _opt_dec(get("modules")) or Decimal("0"),
        "width_mm": _opt_int(get("width_mm")),
        "height_mm": _opt_int(get("height_mm")),
        "depth_mm": _opt_int(get("depth_mm")),
        "din_mountable": (get("din_mountable") or "1").lower() in _BOOL_TRUE,
        "electrical": electrical,
        "price": _opt_dec(get("price")),
        "price_date": date.fromisoformat(get("price_date")) if get("price_date") else default_date,
        "needs_verification": (get("needs_verification") or "1").lower() in _BOOL_TRUE,
    }
    product = Product.objects.filter(brand=brand, sku=get("sku")).first()
    created = product is None
    if product is None:
        product = Product(brand=brand, sku=get("sku"))
    for k, v in values.items():
        setattr(product, k, v)
    product.full_clean()
    product.save()
    return created


def _slug(name: str) -> str:
    from django.utils.text import slugify

    return slugify(name) or name.lower()
