"""Create the backup panel (ATS, in/out breakers, SPD, RCD…) from a checked configuration."""

from dataclasses import dataclass, field

from django.db import transaction

from panels.autolayout_db import _enclosure_specs, _spec_of
from panels.layout_db import sync_rails
from panels.models import DinRail, Placement
from panels.services.autolayout import Device, EnclosureSpec, Section, fits, pack
from panels.services.layout import required_width
from projects.models import Panel, PanelKind, Project

from .db import Suggestion, run_check
from .models import PowerSystem
from .services import Finding

PANEL_NAME = "Щит резерва"
RESERVE_PCT = 20
DEFAULT_MOUNT_MM = (55, 85)
MOUNT_GAP_MM = 10
MOUNT_MARGIN_MM = 10

LABELS = {
    "grid_in_breaker": "Ввод сеть",
    "gen_in_breaker": "Ввод генератор",
    "ats": "АВР",
    "spd": "УЗИП",
    "inv_in_breaker": "Вход инвертора",
    "inv_out_breaker": "Выход инвертора",
    "rcd_inv_out": "УЗО инвертора",
    "battery_dc_breaker": "DC АКБ",
}


class ApplyError(Exception):
    def __init__(self, message: str, code: str, findings: list[Finding] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.findings = findings or []


@dataclass
class _Item:
    suggestion: Suggestion
    din: bool
    modules: int
    label: str


@dataclass
class ApplyResult:
    panel: Panel
    placements: list[Placement] = field(default_factory=list)


def _items(suggestions: list[Suggestion]) -> list[_Item]:
    items: list[_Item] = []
    for s in suggestions:
        p = s.product
        if p is None:
            continue
        din = p.din_mountable and required_width(float(p.modules)) >= 1
        label = LABELS.get(s.component.role, s.component.role)
        for _ in range(s.component.qty):
            items.append(_Item(s, din, required_width(float(p.modules)) if din else 0, label))
    return items


def _mount_layout(
    items: list[_Item], width: int | None, height: int | None
) -> list[tuple[_Item, int, int, int, int]] | None:
    """Shelf packing of non-DIN items on the mounting panel, mm. None if they do not fit."""
    placed: list[tuple[_Item, int, int, int, int]] = []
    x = y = MOUNT_MARGIN_MM
    row_h = 0
    for it in items:
        p = it.suggestion.product
        assert p is not None
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
def apply_to_panel(project: Project, ps: PowerSystem) -> ApplyResult:
    result, suggestions = run_check(project, ps)
    errors = [f for f in result.findings if f.level == "error"]
    if errors:
        raise ApplyError("Схема содержит ошибки безопасности или мощности", "has_errors", errors)
    if not result.components:
        raise ApplyError("Нечего размещать: выберите источники", "empty")
    missing = [s.component for s in suggestions if s.product is None]
    if missing:
        names = ", ".join(f"{c.role} ({c.kind} {c.poles}P {c.rated_a:g}A)" for c in missing)
        raise ApplyError(f"В каталоге нет подходящих изделий: {names}", "no_product")

    items = _items(suggestions)
    din = [i for i in items if i.din]
    mount = [i for i in items if not i.din]
    sections = [
        Section(
            (
                Device(
                    key=str(n),
                    modules=i.modules,
                    product_id=i.suggestion.product.pk,  # type: ignore[union-attr]
                    kind=i.suggestion.component.role,
                ),
            )
        )
        for n, i in enumerate(din)
    ]

    panel = (
        Panel.objects.select_for_update()
        .filter(project=project, kind=PanelKind.BACKUP)
        .order_by("id")
        .first()
    )
    if panel is None:
        panel = Panel.objects.create(project=project, name=PANEL_NAME, kind=PanelKind.BACKUP)

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
                product=it.suggestion.product,
                start_module=slot.start,
                width_modules=it.modules,
                label=it.label,
            )
        )
    for it, x, y, w, h in layout:
        created.append(
            Placement(
                panel=panel,
                product=it.suggestion.product,
                x_mm=x,
                y_mm=y,
                w_mm=w,
                h_mm=h,
                label=it.label,
            )
        )
    Placement.objects.bulk_create(created)
    return ApplyResult(panel=panel, placements=list(panel.placements.all()))
