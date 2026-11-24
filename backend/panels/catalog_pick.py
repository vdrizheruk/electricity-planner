"""Pick catalog products for auto-layout: closest tier first, then cheapest."""

from typing import Any

from catalog.models import Product

TIERS = ("eco", "mid", "premium")


def tier_distance_order(tier: str) -> list[str]:
    base = TIERS.index(tier) if tier in TIERS else 1
    return sorted(TIERS, key=lambda t: (abs(TIERS.index(t) - base), TIERS.index(t)))


def pick(category: str, tier: str, **filters: Any) -> Product | None:
    """First product of ``category`` matching ``filters`` (ORM lookups).

    Tiers are tried by closeness to ``tier``; inside a tier the cheapest wins,
    ties broken by brand name and SKU so the result is deterministic.
    """
    qs = Product.objects.filter(category__code=category, **filters).select_related("brand")
    for t in tier_distance_order(tier):
        found = qs.filter(tier=t).order_by("price", "brand__name", "sku").first()
        if found is not None:
            return found
    return None
