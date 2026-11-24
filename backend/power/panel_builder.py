"""Place catalog products into a project panel: enclosure choice, DIN packing, mount panel."""

from dataclasses import dataclass, field

from django.db import transaction

from catalog.models import Product
from panels.autolayout_db import _enclosure_specs, _spec_of
from panels.layout_db import sync_rails
from panels.models import DinRail, Placement
from panels.services.autolayout import Device, EnclosureSpec, Section, fits, pack
from panels.services.layout import required_width
from projects.models import Panel, Project

from .services import Finding

RESERVE_PCT = 20
DEFAULT_MOUNT_MM = (55, 85)
MOUNT_GAP_MM = 10
MOUNT_MARGIN_MM = 10


class ApplyError(Exception):
    def __init__(self, message: str, code: str, findings: list[Finding] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.findings = findings or []


@dataclass(frozen=True)
class PlaceItem:
    product: Product
    qty: int
    label: str


@dataclass
class _Item:
    product: Product
    din: bool
    modules: int
    label: str


@dataclass
class ApplyResult:
    panel: Panel
    placements: list[Placement] = field(default_factory=list)


def _items(places: list[PlaceItem]) -> list[_Item]:
    items: list[_Item] = []
    for pl in places:
        p = pl.product
        din = p.din_mountable and required_width(float(p.modules)) >= 1
        for _ in range(pl.qty):
            items.append(_Item(p, din, required_width(float(p.modules)) if din else 0, pl.label))
    return items


def _mount_layout(
    items: list[_Item], width: int | None, height: int | None
) -> list[tuple[_Item, int, int, int, int]] | None:
    """Shelf packing of non-DIN items on the mounting panel, mm. None if they do not fit."""
    placed: list[tuple[_Item, int, int, int, int]] = []
    x = y = MOUNT_MARGIN_MM
    row_h = 0
    for it in items:
        p = it.product
        w = p.width_mm or DEFAULT_MOUNT_MM[0]
        h = p.height_mm or DEFAULT_MOUNT_MM[1]
        if width is None or height is None:
            return None
        if x + w > width - MOUNT_MARGIN_MM and x > MOUNT_MARGIN_MM:
            x = MOUNT_MARGIN_MM
            y += row_h + MOUNT_GAP_MM
            row_h = 0
        if x + w > width or y + h > height:
            return None
        placed.append((it, x, y, w, h))
        x += w + MOUNT_GAP_MM
        row_h = max(row_h, h)
    return placed


@transaction.atomic
def build_panel(project: Project, kind: str, name: str, places: list[PlaceItem]) -> ApplyResult:
    """Create (or rebuild) the project's panel of ``kind`` and place ``places`` into it."""
    items = _items(places)
    din = [i for i in items if i.din]
    mount = [i for i in items if not i.din]
    sections = [
        Section(
            (
                Device(
                    key=str(n),
                    modules=i.modules,
                    product_id=i.product.pk,
                    kind=i.label,
                ),
            )
        )
        for n, i in enumerate(din)
    ]

    panel = (
        Panel.objects.select_for_update().filter(project=project, kind=kind).order_by("id").first()
    )
    if panel is None:
        panel = Panel.objects.create(project=project, name=name, kind=kind)

    specs, by_pk = _enclosure_specs(panel, project.price_tier)
    current = _spec_of(panel.enclosure) if panel.enclosure else None
    ordered = ([current] if current else []) + sorted(
        specs, key=lambda c: (c.capacity, c.price, c.id)
    )
    chosen: tuple[EnclosureSpec, list[tuple[_Item, int, int, int, int]]] | None = None
    for spec in ordered:
        if spec is None or not fits(sections, spec, RESERVE_PCT):
            continue
        enc = by_pk.get(spec.id) or panel.enclosure
        w = max((enc.width_mm or 0) - 40, 0) if enc else 0
        h = max((enc.height_mm or 0) - 40, 0) if enc else 0
        layout = _mount_layout(mount, w, h) if mount else []
        if layout is not None:
            chosen = (spec, layout)
            break
    if chosen is None:
        raise ApplyError("Нет корпуса, вмещающего все изделия с резервом", "no_enclosure")
    spec, layout = chosen

    panel.placements.all().delete()
    if panel.enclosure_id != spec.id:
        panel.enclosure = by_pk[spec.id]
        el = panel.enclosure.electrical or {}
        panel.ip = int(el.get("ip", panel.ip))
        panel.mounting = str(el.get("mounting", panel.mounting))
        panel.save(update_fields=["enclosure", "ip", "mounting"])
    sync_rails(panel)

    packed = pack(sections, [spec.per_row] * spec.rows)
    if not packed.ok:
        raise ApplyError("Изделия не помещаются на рейки", "no_fit")
    rails = {r.row_index: r for r in DinRail.objects.filter(panel=panel)}
    created: list[Placement] = []
    for slot in packed.slots:
        it = din[int(slot.key)]
        created.append(
            Placement(
                panel=panel,
                rail=rails[slot.row],
                product=it.product,
                start_module=slot.start,
                width_modules=it.modules,
                label=it.label,
            )
        )
    for it, x, y, w, h in layout:
        created.append(
            Placement(
                panel=panel,
                product=it.product,
                x_mm=x,
                y_mm=y,
                w_mm=w,
                h_mm=h,
                label=it.label,
            )
        )
    Placement.objects.bulk_create(created)
    return ApplyResult(panel=panel, placements=list(panel.placements.all()))
