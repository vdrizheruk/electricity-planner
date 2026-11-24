"""Auto-layout: «ввод → реле/УЗИП → УЗО с группами», then manual editing.

Chooses catalog products for the project's price tier, packs them on the DIN rails of
the panel (optionally replacing the enclosure with a suitable one, 20 % reserve) and
stores the result as placements linked to their consumer groups.
"""

from dataclasses import dataclass, field
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from calculations import Finding, ProjectCalculation
from catalog.models import Product
from projects.models import ConsumerGroup, Panel
from projects.services import autoselect_project

from .catalog_pick import pick
from .layout_db import sync_rails
from .models import DinRail, Placement
from .services.autolayout import (
    Device,
    EnclosureSpec,
    PackResult,
    Section,
    pack,
    required_with_reserve,
    suggest_enclosure,
    total_modules,
)
from .services.layout import required_width


@dataclass
class AutolayoutOptions:
    voltage_relay: bool = True
    spd: str = "2"  # "none" | "2" | "1+2"
    fire_rcd: bool = False
    reserve_pct: int = 20
    pick_enclosure: bool = True


@dataclass
class AutolayoutResult:
    placements: list[Placement]
    required_modules: int
    capacity_modules: int
    enclosure_changed: bool
    findings: list[Finding] = field(default_factory=list)


class AutolayoutError(Exception):
    def __init__(self, message: str, findings: list[Finding] | None = None, code: str = "error"):
        super().__init__(message)
        self.findings = findings or []
        self.code = code


def _width(p: Product) -> int:
    return max(required_width(float(p.modules)), 1)


class _Builder:
    def __init__(self, panel: Panel, calc: ProjectCalculation, opts: AutolayoutOptions):
        self.panel = panel
        self.project = panel.project
        self.calc = calc
        self.opts = opts
        self.tier: str = self.project.price_tier
        self.three = self.project.grid == "3ph"
        self.findings: list[Finding] = []
        self.products: dict[int, Product] = {}
        self.n = 0
        self.group_by_id = {g.pk: g for g in panel.groups.all()}
        self.result_by_id = {r.group_id: r for r in calc.groups}

    # -- helpers
    def dev(self, product: Product, kind: str, group_id: int | None = None) -> Device:
        self.products[product.pk] = product
        self.n += 1
        return Device(f"d{self.n}", _width(product), product.pk, kind, group_id)

    def warn(self, code: str, message: str, group_id: int | None = None) -> None:
        self.findings.append(Finding("warning", code, message, group_id))

    def info(self, code: str, message: str, group_id: int | None = None) -> None:
        self.findings.append(Finding("info", code, message, group_id))

    def mcb(self, rating: int, curve: str, poles: int, group_id: int | None) -> Device | None:
        label = f"{poles}P {curve}{rating}"
        p = pick("mcb", self.tier, rated_a=rating, poles=poles, curve=curve)
        if p is None:
            other = "C" if curve == "B" else "B"
            p = pick("mcb", self.tier, rated_a=rating, poles=poles, curve=other)
            if p is not None:
                self.warn(
                    "curve_substituted", f"{label}: в каталоге нет, взят {other}{rating}", group_id
                )
        if p is None:
            self.warn("missing_product", f"Нет автомата {label} в каталоге", group_id)
            return None
        return self.dev(p, "mcb", group_id)

    def rcd(self, rating: int, poles: int, ma: int = 30, selective: bool = False) -> Device | None:
        filters: dict[str, Any] = {"rated_a": rating, "poles": poles, "leakage_ma": ma}
        if selective:
            filters["electrical__selective"] = True
        else:
            filters["rcd_type"] = "A"
            filters["electrical__selective"] = False
        p = pick("rcd", self.tier, **filters)
        if p is None:
            self.warn("missing_product", f"Нет УЗО {poles}P {rating}A {ma}мА в каталоге")
            return None
        return self.dev(p, "rcd")

    # -- sections
    def input_section(self) -> Section | None:
        devs: list[Device | None] = []
        poles = 4 if self.three else 2
        main = pick("mcb", self.tier, rated_a=self.project.main_breaker_a, poles=poles, curve="C")
        if main is None:
            bigger = [
                x
                for x in range(self.project.main_breaker_a + 1, 126)
                if pick("mcb", self.tier, rated_a=x, poles=poles, curve="C")
            ]
            if bigger:
                main = pick("mcb", self.tier, rated_a=bigger[0], poles=poles, curve="C")
                self.warn(
                    "main_breaker_substituted",
                    f"Вводного автомата {self.project.main_breaker_a} А нет в каталоге, "
                    f"взят {bigger[0]} А",
                )
        if main is None:
            self.warn("missing_product", f"Нет вводного автомата {poles}P в каталоге")
        else:
            devs.append(self.dev(main, "main"))
        if self.opts.fire_rcd:
            devs.append(self.rcd(63, poles, 300, selective=True))
        if self.opts.voltage_relay:
            p = pick("phase_relay" if self.three else "voltage_relay", self.tier)
            if p is None:
                self.warn("missing_product", "Нет реле напряжения / контроля фаз в каталоге")
            else:
                devs.append(self.dev(p, "relay"))
        if self.opts.spd != "none":
            p = pick("spd", self.tier, poles=poles, electrical__spd_type=self.opts.spd)
            if p is None:
                self.warn("missing_product", f"Нет УЗИП типа {self.opts.spd} {poles}P")
            else:
                devs.append(self.dev(p, "spd"))
        real = tuple(d for d in devs if d is not None)
        return Section(real) if real else None

    def group_breaker(self, gid: int) -> Device | None:
        r = self.result_by_id[gid]
        poles = 3 if r.phase == "3ph" else 1
        return self.mcb(r.breaker_a, r.curve, poles, gid)

    def rcd_sections(self) -> list[Section]:
        out: list[Section] = []
        for a in sorted(self.calc.rcds, key=lambda x: (x.backed_up, len(x.group_ids) == 1, x.id)):
            single_rcbo = (
                len(a.group_ids) == 1 and self.result_by_id[a.group_ids[0]].protection == "rcbo"
            )
            if single_rcbo:
                gid = a.group_ids[0]
                r = self.result_by_id[gid]
                p = None
                if r.phase != "3ph":
                    p = pick(
                        "rcbo",
                        self.tier,
                        rated_a=r.breaker_a,
                        poles=2,
                        leakage_ma=30,
                        rcd_type="A",
                        curve=r.curve,
                    )
                    if p is None:
                        p = pick(
                            "rcbo",
                            self.tier,
                            rated_a=r.breaker_a,
                            poles=2,
                            leakage_ma=30,
                            rcd_type="A",
                        )
                        if p is not None:
                            self.warn(
                                "curve_substituted",
                                f"Дифавтомат {r.curve}{r.breaker_a}: взят {p.curve}{r.breaker_a}",
                                gid,
                            )
                if p is not None:
                    out.append(Section((self.dev(p, "rcbo", gid),)))
                    continue
                self.info("rcd_plus_mcb", "Дифавтомат не найден: УЗО + автомат", gid)
            rating = a.rating_a
            rcd = self.rcd(rating, a.poles)
            devs: list[Device] = []
            if rcd is not None:
                devs.append(rcd)
            for gid in a.group_ids:
                m = self.group_breaker(gid)
                if m is not None:
                    devs.append(m)
            if devs:
                out.append(Section(tuple(devs)))
        return out

    def plain_sections(self) -> list[Section]:
        out: list[Section] = []
        for r in self.calc.groups:
            if r.protection == "mcb":
                m = self.group_breaker(r.group_id)
                if m is not None:
                    out.append(Section((m,)))
        return out

    def sections(self) -> list[Section]:
        secs: list[Section] = []
        inp = self.input_section()
        if inp is not None:
            secs.append(inp)
        secs += self.rcd_sections() + self.plain_sections()
        return secs


def _enclosure_specs(panel: Panel, tier: str) -> tuple[list[EnclosureSpec], dict[int, Product]]:
    prods = list(Product.objects.filter(category__code="enclosure"))
    specs = []
    for p in prods:
        el: dict[str, Any] = p.electrical or {}
        if not el.get("rows") or not el.get("modules_per_row"):
            continue
        specs.append(
            EnclosureSpec(
                p.pk,
                int(el["rows"]),
                int(el["modules_per_row"]),
                float(p.price),
                int(el.get("ip", 40)),
                str(el.get("mounting", "flush")),
            )
        )
    return specs, {p.pk: p for p in prods}


def _spec_of(product: Product) -> EnclosureSpec | None:
    el: dict[str, Any] = product.electrical or {}
    if not el.get("rows") or not el.get("modules_per_row"):
        return None
    return EnclosureSpec(
        product.pk,
        int(el["rows"]),
        int(el["modules_per_row"]),
        float(product.price),
        int(el.get("ip", 40)),
        str(el.get("mounting", "flush")),
    )


@transaction.atomic
def autolayout(panel: Panel, opts: AutolayoutOptions) -> AutolayoutResult:
    Panel.objects.select_for_update().get(pk=panel.pk)
    project = panel.project

    # Unassigned groups belong to the main panel.
    if panel.kind == "main":
        project.groups.filter(panel__isnull=True).update(panel=panel)
    group_ids = set(panel.groups.values_list("pk", flat=True))

    calc = autoselect_project(project, group_ids=group_ids)
    blocking = [f for f in calc.findings if f.level == "error"]
    if blocking:
        raise AutolayoutError("Расчёт групп содержит ошибки", blocking, "calculation_failed")

    builder = _Builder(panel, calc, opts)
    sections = builder.sections()
    need = total_modules(sections)
    need_reserve = required_with_reserve(need, opts.reserve_pct)

    # Enclosure: keep the current one if everything fits with the reserve.
    current = _spec_of(panel.enclosure) if panel.enclosure else None
    enclosure_changed = False
    chosen = current
    if current is None or not _fits(sections, current, opts.reserve_pct):
        if not opts.pick_enclosure:
            have = current.capacity if current else 0
            raise AutolayoutError(
                f"Нужно {need_reserve} модулей (с резервом {opts.reserve_pct}%), в корпусе {have}",
                code="enclosure_too_small",
            )
        specs, by_pk = _enclosure_specs(panel, project.price_tier)
        chosen = suggest_enclosure(
            sections,
            specs,
            opts.reserve_pct,
            mounting=panel.mounting if panel.enclosure else None,
        )
        if chosen is None:
            raise AutolayoutError(
                f"Нет подходящего корпуса для {need_reserve} модулей", code="no_enclosure"
            )
        panel.enclosure = by_pk[chosen.id]
        enclosure_changed = True

    assert chosen is not None
    # Free the rails: layout replaces all DIN placements, mounting-panel items stay.
    panel.placements.filter(rail__isnull=False).delete()
    if enclosure_changed:
        el = panel.enclosure.electrical if panel.enclosure else {}
        panel.ip = int(el.get("ip", panel.ip))
        panel.mounting = str(el.get("mounting", panel.mounting))
        panel.save(update_fields=["enclosure", "ip", "mounting"])
        try:
            sync_rails(panel)
        except ValidationError as exc:
            raise AutolayoutError("; ".join(exc.messages), code="rails") from exc

    result: PackResult = pack(sections, [chosen.per_row] * chosen.rows)
    if not result.ok:
        raise AutolayoutError("Элементы не помещаются на рейки", code="no_fit")
    if result.split_sections:
        builder.warn("section_split", "Часть групп под УЗО не помещается в один ряд и разнесена")

    rails = {r.row_index: r for r in DinRail.objects.filter(panel=panel)}
    devices = {d.key: d for s in sections for d in s.devices}
    created: list[Placement] = []
    group_by_pk = builder.group_by_id
    for slot in result.slots:
        d = devices[slot.key]
        created.append(
            Placement(
                panel=panel,
                rail=rails[slot.row],
                product=builder.products[d.product_id],
                group=group_by_pk.get(d.group_id) if d.group_id else None,
                start_module=slot.start,
                width_modules=d.modules,
                label=group_by_pk[d.group_id].name[:64] if d.group_id else "",
            )
        )
    Placement.objects.bulk_create(created)

    findings = [*calc.findings, *builder.findings]
    return AutolayoutResult(
        placements=list(panel.placements.all()),
        required_modules=need,
        capacity_modules=chosen.capacity,
        enclosure_changed=enclosure_changed,
        findings=findings,
    )


def _fits(sections: list[Section], spec: EnclosureSpec, reserve_pct: int) -> bool:
    from .services.autolayout import fits

    return fits(sections, spec, reserve_pct)


__all__ = [
    "AutolayoutError",
    "AutolayoutOptions",
    "AutolayoutResult",
    "ConsumerGroup",
    "autolayout",
]
