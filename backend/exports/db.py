"""Collect the project's bill of materials from panels, the PV scheme and the backup scheme."""

from catalog.models import Product
from power.db import run_check
from power.models import PowerSystem, PvSystem
from power.pv_db import run_pv_check
from power.services.plan import WITH_GENERATOR, WITH_INVERTER
from projects.models import PanelKind, Project

from .services.bom import BlockInput, Bom, Item, SectionInput, build_bom

BOARDS = "boards"
SOLAR = "solar"
BACKUP = "backup"
TITLES = {BOARDS: "Щиты", SOLAR: "Солнечная система", BACKUP: "Резервное питание"}


def item(p: Product, qty: int = 1) -> Item:
    return Item(
        product_id=p.pk,
        brand=p.brand.name,
        sku=p.sku,
        name=p.name,
        unit_price=p.price,
        qty=qty,
        unit="м" if p.category.code == "cable" else "шт",
        needs_verification=p.needs_verification,
    )


def _boards(project: Project) -> tuple[SectionInput, bool, bool]:
    blocks: list[BlockInput] = []
    has_dc = has_backup = False
    panels = project.panels.select_related("enclosure__brand", "enclosure__category").order_by("id")
    for panel in panels:
        items: list[Item] = []
        if panel.enclosure is not None:
            items.append(item(panel.enclosure))
        for pl in panel.placements.select_related("product__brand", "product__category"):
            items.append(item(pl.product))
        blocks.append(BlockInput(f"panel:{panel.pk}", panel.name, tuple(items)))
        has_dc |= panel.kind == PanelKind.DC
        has_backup |= panel.kind == PanelKind.BACKUP
    return SectionInput(BOARDS, TITLES[BOARDS], tuple(blocks)), has_dc, has_backup


def _solar(project: Project, has_dc_panel: bool, missing: list[str]) -> SectionInput | None:
    pv = PvSystem.objects.filter(project=project).first()
    checked = run_pv_check(project, pv) if pv else None
    if checked is None:
        return None
    _, suggestions = checked
    items: list[Item] = []
    for s in suggestions:
        if s.component.placed and has_dc_panel:
            continue  # already counted with the DC box
        if s.product is None:
            missing.append(f"PV: {s.component.note or s.component.role}")
            continue
        items.append(item(s.product, s.component.qty))
    if not items:
        return None
    return SectionInput(
        SOLAR,
        TITLES[SOLAR],
        (BlockInput("pv", "Панели, инвертор, кабель, DC-защита", tuple(items), not has_dc_panel),),
    )


def _backup(
    project: Project, has_backup_panel: bool, pv: PvSystem | None, missing: list[str]
) -> SectionInput | None:
    ps = PowerSystem.objects.filter(project=project).first()
    if ps is None:
        return None
    items: list[Item] = []
    if ps.scenario in WITH_GENERATOR and ps.generator is not None:
        items.append(item(ps.generator))
    if ps.scenario in WITH_INVERTER:
        shared = pv is not None and pv.inverter_id is not None and pv.inverter_id == ps.inverter_id
        if ps.inverter is not None and not shared:  # a hybrid unit shared with PV is counted once
            items.append(item(ps.inverter, ps.inverter_count))
        if ps.battery is not None:
            items.append(item(ps.battery, ps.battery_count))
    estimated = False
    if not has_backup_panel and items:
        _, suggestions = run_check(project, ps)
        for s in suggestions:
            if s.product is None:
                missing.append(f"Резерв: {s.component.note or s.component.role}")
            else:
                items.append(item(s.product, s.component.qty))
        estimated = True
    if not items:
        return None
    return SectionInput(
        BACKUP,
        TITLES[BACKUP],
        (BlockInput("backup", "Генератор, инвертор, АКБ, коммутация", tuple(items), estimated),),
    )


def collect_bom(project: Project) -> Bom:
    boards, has_dc, has_backup = _boards(project)
    missing: list[str] = []
    sections = [boards]
    pv = PvSystem.objects.filter(project=project).first()
    for s in (_solar(project, has_dc, missing), _backup(project, has_backup, pv, missing)):
        if s is not None:
            sections.append(s)
    return build_bom(sections, tuple(missing))
