"""Analog lookup: same function in another brand / price tier."""

from django.db.models import QuerySet

from .models import Product, Tier

# Fields that define "same function" for a given product.
_MATCH_FIELDS = ("category_id", "rated_a", "poles", "curve", "leakage_ma", "rcd_type")


def find_analogs(product: Product, tier: str | None = None) -> QuerySet[Product]:
    """Products with identical functional parameters; optionally restricted to a tier.

    The product itself is excluded. Ordered cheapest first.
    """
    if tier is not None and tier not in Tier.values:
        raise ValueError(f"Unknown tier: {tier}")
    filters = {f: getattr(product, f) for f in _MATCH_FIELDS}
    # Optional numeric params: NULL must match NULL, not be skipped.
    qs = Product.objects.filter(**{k: v for k, v in filters.items() if v is not None})
    for field, value in filters.items():
        if value is None:
            qs = qs.filter(**{f"{field}__isnull": True})
    qs = qs.exclude(pk=product.pk).select_related("brand", "category")
    if tier is not None:
        qs = qs.filter(tier=tier)
    return qs.order_by("price", "brand__name")
