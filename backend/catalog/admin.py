from django import forms
from django.contrib import admin, messages
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import path, reverse

from .csv_io import export_csv, import_csv
from .models import Brand, Category, Product


class CsvImportForm(forms.Form):
    file = forms.FileField(label="CSV (UTF-8)")


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ("name", "tier")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("code", "name_ru", "name_uk", "sort_order")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "sku",
        "brand",
        "category",
        "name",
        "tier",
        "rated_a",
        "poles",
        "curve",
        "leakage_ma",
        "rcd_type",
        "modules",
        "price",
        "price_date",
        "needs_verification",
    )
    list_filter = ("category", "brand", "tier", "poles", "needs_verification")
    search_fields = ("sku", "name", "series")
    list_select_related = ("brand", "category")
    actions = ["export_selected_csv"]
    change_list_template = "admin/catalog/product/change_list.html"

    @admin.action(description="Экспорт выбранных в CSV")
    def export_selected_csv(
        self, request: HttpRequest, queryset: QuerySet[Product]
    ) -> HttpResponse:
        resp = HttpResponse(export_csv(queryset), content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="catalog.csv"'
        return resp

    def get_urls(self):  # type: ignore[no-untyped-def]
        custom = [
            path(
                "export-csv/",
                self.admin_site.admin_view(self.export_all),
                name="catalog_product_export",
            ),
            path(
                "import-csv/",
                self.admin_site.admin_view(self.import_view),
                name="catalog_product_import",
            ),
        ]
        return custom + super().get_urls()

    def export_all(self, request: HttpRequest) -> HttpResponse:
        if not self.has_view_permission(request):
            return HttpResponse(status=403)
        resp = HttpResponse(export_csv(), content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="catalog.csv"'
        return resp

    def import_view(self, request: HttpRequest) -> HttpResponse:
        if not (self.has_add_permission(request) and self.has_change_permission(request)):
            return HttpResponse(status=403)
        form = CsvImportForm(request.POST or None, request.FILES or None)
        if request.method == "POST" and form.is_valid():
            text = form.cleaned_data["file"].read().decode("utf-8-sig")
            result = import_csv(text)
            if result.ok:
                messages.success(
                    request, f"Импорт: создано {result.created}, обновлено {result.updated}"
                )
                return HttpResponseRedirect(reverse("admin:catalog_product_changelist"))
            for err in result.errors[:50]:
                messages.error(request, err)
        ctx = {
            **self.admin_site.each_context(request),
            "form": form,
            "title": "Импорт каталога из CSV",
        }
        return render(request, "admin/catalog/product/import_csv.html", ctx)
