from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from catalog.models import Brand, Category, Product
from catalog.seed_data import BRANDS, CATEGORIES, OTHER_BRANDS, build_items


class Command(BaseCommand):
    help = "Create categories, brands and indicative catalog products (idempotent)."

    @transaction.atomic
    def handle(self, *args: object, **options: object) -> None:
        for order, (code, ru, uk) in enumerate(CATEGORIES):
            Category.objects.update_or_create(
                code=code, defaults={"name_ru": ru, "name_uk": uk, "sort_order": order * 10}
            )
        brands: dict[str, Brand] = {}
        all_brands = {n: t for n, (t, _f) in BRANDS.items()} | OTHER_BRANDS
        for name, tier in all_brands.items():
            brands[name], _ = Brand.objects.update_or_create(
                name=name, defaults={"slug": slugify(name) or name.lower(), "tier": tier}
            )
        cats = {c.code: c for c in Category.objects.all()}
        today = date.today()
        created = 0
        for it in build_items():
            w = h = d = None
            if it.size:
                w, h, d = it.size
            _, was_created = Product.objects.update_or_create(
                brand=brands[it.brand],
                sku=it.sku,
                defaults={
                    "category": cats[it.category],
                    "name": it.name,
                    "series": it.series,
                    "tier": it.tier,
                    "rated_a": it.rated_a,
                    "poles": it.poles,
                    "curve": it.curve,
                    "leakage_ma": it.leakage_ma,
                    "rcd_type": it.rcd_type,
                    "modules": it.modules,
                    "width_mm": w,
                    "height_mm": h,
                    "depth_mm": d,
                    "din_mountable": it.din,
                    "electrical": it.electrical,
                    "price": it.price,
                    "price_date": today,
                    "needs_verification": True,
                },
            )
            created += was_created
        total = Product.objects.count()
        self.stdout.write(self.style.SUCCESS(f"Catalog seeded: {created} new, {total} total."))
