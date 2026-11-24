"""Django-side helpers: build pure specs from the DB, sync rails, snapshot/restore."""

from collections.abc import Iterable
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from projects.models import Panel

from .models import DinRail, LayoutVersion, Placement
from .services.layout import Issue, PanelArea, PlacementSpec, RailSpec, validate_layout


def enclosure_geometry(panel: Panel) -> tuple[int, int, PanelArea]:
    """(rows, modules_per_row, mounting area) from the panel's enclosure; zeros if none."""
    enc = panel.enclosure
    if enc is None:
        return 0, 0, PanelArea()
    el: dict[str, Any] = enc.electrical or {}
    area = PanelArea()
    if enc.width_mm and enc.height_mm:
        # Usable mounting plate: enclosure minus 20 mm frame on each side.
        area = PanelArea(max(enc.width_mm - 40, 0), max(enc.height_mm - 40, 0))
    return int(el.get("rows", 0)), int(el.get("modules_per_row", 0)), area


@transaction.atomic
def sync_rails(panel: Panel) -> None:
    """Make DinRail rows match the enclosure. Refuses to drop occupied rails/slots."""
    rows, per_row, _ = enclosure_geometry(panel)
    existing = {r.row_index: r for r in panel.rails.all()}
    for idx in range(rows):
        if idx in existing:
            rail = existing[idx]
            if rail.capacity_modules != per_row:
                too_far = rail.placements.filter(start_module__gte=per_row).exists() or any(
                    (p.start_module or 0) + p.width_modules > per_row for p in rail.placements.all()
                )
                if too_far:
                    raise ValidationError(
                        f"Рейка {idx + 1}: есть элементы, не помещающиеся в {per_row} модулей"
                    )
                rail.capacity_modules = per_row
                rail.save(update_fields=["capacity_modules"])
        else:
            DinRail.objects.create(panel=panel, row_index=idx, capacity_modules=per_row)
    for idx, rail in existing.items():
        if idx >= rows:
            if rail.placements.exists():
                raise ValidationError(f"Рейка {idx + 1} занята: удалите элементы перед заменой")
            rail.delete()


def to_specs(
    panel: Panel, placements: Iterable[Placement]
) -> tuple[list[RailSpec], list[PlacementSpec], PanelArea]:
    rails = [RailSpec(r.pk, r.capacity_modules) for r in panel.rails.all()]
    _, _, area = enclosure_geometry(panel)
    specs = [placement_spec(p) for p in placements]
    return rails, specs, area


def placement_spec(p: Placement, key: str | None = None) -> PlacementSpec:
    return PlacementSpec(
        key=key if key is not None else str(p.pk),
        din=p.product.din_mountable,
        product_modules=float(p.product.modules),
        rail_id=p.rail_id,
        start=p.start_module,
        width=p.width_modules,
        x_mm=p.x_mm,
        y_mm=p.y_mm,
        w_mm=p.w_mm,
        h_mm=p.h_mm,
    )


def validate_panel(panel: Panel) -> list[Issue]:
    placements = list(panel.placements.select_related("product"))
    rails, specs, area = to_specs(panel, placements)
    return validate_layout(rails, specs, area)


def snapshot(panel: Panel) -> list[dict[str, Any]]:
    rail_row = {r.pk: r.row_index for r in panel.rails.all()}
    out: list[dict[str, Any]] = []
    for p in panel.placements.all():
        out.append(
            {
                "row": rail_row.get(p.rail_id) if p.rail_id else None,
                "start": p.start_module,
                "width": p.width_modules,
                "x": p.x_mm,
                "y": p.y_mm,
                "w": p.w_mm,
                "h": p.h_mm,
                "product": p.product_id,
                "group": p.group_id,
                "label": p.label,
            }
        )
    return out


@transaction.atomic
def create_version(panel: Panel, note: str = "") -> LayoutVersion:
    Panel.objects.select_for_update().get(pk=panel.pk)  # serialize version numbering
    last = panel.versions.order_by("-number").first()
    return LayoutVersion.objects.create(
        panel=panel, number=(last.number + 1) if last else 1, note=note, snapshot=snapshot(panel)
    )


@transaction.atomic
def restore_version(version: LayoutVersion) -> None:
    panel = version.panel
    rails = {r.row_index: r for r in panel.rails.all()}
    from catalog.models import Product
    from projects.models import ConsumerGroup

    missing_products = {s["product"] for s in version.snapshot} - set(
        Product.objects.filter(pk__in=[s["product"] for s in version.snapshot]).values_list(
            "pk", flat=True
        )
    )
    if missing_products:
        raise ValidationError("В версии есть изделия, которых больше нет в каталоге")
    for s in version.snapshot:
        if s["row"] is not None and s["row"] not in rails:
            raise ValidationError("Конфигурация корпуса изменилась: версию нельзя восстановить")
    valid_groups = set(
        ConsumerGroup.objects.filter(project=panel.project).values_list("pk", flat=True)
    )
    panel.placements.all().delete()
    Placement.objects.bulk_create(
        [
            Placement(
                panel=panel,
                rail=rails[s["row"]] if s["row"] is not None else None,
                product_id=s["product"],
                group_id=s["group"] if s["group"] in valid_groups else None,
                start_module=s["start"],
                width_modules=s["width"],
                x_mm=s["x"],
                y_mm=s["y"],
                w_mm=s["w"],
                h_mm=s["h"],
                label=s["label"],
            )
            for s in version.snapshot
        ]
    )
