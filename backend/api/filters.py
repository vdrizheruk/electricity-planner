import django_filters

from catalog.models import Product


class ProductFilter(django_filters.FilterSet):
    category = django_filters.CharFilter(field_name="category__code")
    brand = django_filters.CharFilter(field_name="brand__slug")
    q = django_filters.CharFilter(method="search")
    rated_a = django_filters.NumberFilter()
    rated_a_min = django_filters.NumberFilter(field_name="rated_a", lookup_expr="gte")
    rated_a_max = django_filters.NumberFilter(field_name="rated_a", lookup_expr="lte")
    price_max = django_filters.NumberFilter(field_name="price", lookup_expr="lte")

    class Meta:
        model = Product
        fields = ["tier", "poles", "curve", "leakage_ma", "rcd_type", "din_mountable"]

    def search(self, queryset, name, value):  # type: ignore[no-untyped-def]
        from django.db.models import Q

        return queryset.filter(Q(sku__icontains=value) | Q(name__icontains=value))
