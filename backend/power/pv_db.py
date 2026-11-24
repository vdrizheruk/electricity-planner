"""Glue between the Django models and the pure PV service."""

from dataclasses import dataclass
from typing import Any

from catalog.models import Product
from panels.catalog_pick import pick
from projects.models import PanelKind, Project

from .models import PvArray, PvSystem
from .panel_builder import ApplyError, ApplyResult, PlaceItem, build_panel
from .services import (
    PvArray as PvArraySpec,
)
from .services import (
    PvComponent,
    PvInput,
    PvInverterSpec,
    PvModuleSpec,
    PvResult,
    analyze_pv,
)

PANEL_NAME = "DC-бокс"

LABELS = {
    "dc_fuse": "gPV",
    "dc_isolator": "DC QS",
    "dc_spd": "DC УЗИП",
    "ac_breaker": "AC выход",
    "ac_spd": "AC УЗИП",
    "meter": "Счётчик",
}


def _el(p: Product) -> dict[str, Any]:
    return p.electrical or {}


def module_spec(p: Product) -> PvModuleSpec:
    e = _el(p)
    return PvModuleSpec(
        pmax_w=float(e.get("pmax_w", 0)),
        voc_v=float(e.get("voc_v", 0)),
        isc_a=float(e.get("isc_a", 0)),
        vmp_v=float(e.get("vmp_v", 0)),
        imp_a=float(e.get("imp_a", 0)),
        beta_voc_pct_per_c=float(e.get("beta_voc_pct_per_c", -0.25)),
        beta_vmp_pct_per_c=float(e.get("beta_vmp_pct_per_c", -0.30)),
        max_series_fuse_a=float(e.get("max_series_fuse_a", 25)),
    )


def pv_inverter_spec(p: Product, count: int) -> PvInverterSpec:
    e = _el(p)
    return PvInverterSpec(
        kind=str(e.get("kind", "hybrid")),
        phases=int(e.get("phases", 1)),
        p_ac_w=float(e.get("p_ac_w", 0)),
        count=count,
        mppt_count=int(e.get("mppt_count", 0)),
        mppt_min_v=float(e.get("mppt_min_v", 0)),
        mppt_max_v=float(e.get("mppt_max_v", 0)),
        vmax_v=float(e.get("vmax_v", 0)),
        imax_per_mppt_a=float(e.get("imax_per_mppt_a", 0)),
        isc_max_per_mppt_a=float(e.get("isc_max_per_mppt_a", 0)),
        pv_max_w=float(e.get("pv_max_w", 0)),
        transformerless=bool(e.get("transformerless", True)),
    )


def get_or_create_pv(project: Project) -> PvSystem:
    pv, _ = PvSystem.objects.get_or_create(project=project)
    return pv


def array_spec(a: PvArray) -> PvArraySpec:
    return PvArraySpec(
        mppt=a.mppt,
        series=a.series,
        strings=a.strings,
        azimuth_deg=a.azimuth_deg,
        tilt_deg=a.tilt_deg,
        cable_m=a.cable_m,
    )


def pv_input(project: Project, pv: PvSystem) -> PvInput | None:
    """None while the module or the inverter is not chosen yet."""
    if pv.module is None or pv.inverter is None:
        return None
    return PvInput(
        grid=project.grid,  # type: ignore[arg-type]
        earthing=project.earthing,
        module=module_spec(pv.module),
        inverter=pv_inverter_spec(pv.inverter, pv.inverter_count),
        arrays=tuple(array_spec(a) for a in pv.arrays.all()),
        t_min_c=pv.t_min_c,
        t_cell_max_c=pv.t_cell_max_c,
        region=pv.region,
        performance_ratio=pv.performance_ratio,
        export_limit_w=float(pv.export_limit_w),
        green_tariff=pv.green_tariff,
    )


@dataclass
class PvSuggestion:
    component: PvComponent
    product: Product | None


def suggest_pv_product(c: PvComponent, tier: str, pv: PvSystem) -> Product | None:
    """The catalog product for a component (cheapest of the closest price tier)."""
    if c.kind == "pv_module":
        return pv.module
    if c.kind == "inverter":
        return pv.inverter
    if c.kind == "dc_fuse":
        return pick("dc_fuse", tier, rated_a__gte=c.rated_a, electrical__vdc_max__gte=c.vdc_v)
    if c.kind == "dc_isolator":
        return pick("dc_isolator", tier, rated_a__gte=c.rated_a, electrical__vdc_max__gte=c.vdc_v)
    if c.kind == "dc_spd":
        return pick("dc_spd", tier, electrical__ucpv_v__gte=c.vdc_v)
    if c.kind == "pv_connector":
        return pick("pv_connector", tier)
    if c.kind == "cable":
        return pick("cable", tier, electrical__pv=True, electrical__mm2=c.mm2)
    if c.kind == "mcb":
        return pick("mcb", tier, poles=c.poles, curve="C", rated_a=c.rated_a) or pick(
            "mcb", tier, poles=c.poles, curve="C", rated_a__gte=c.rated_a
        )
    if c.kind == "spd":
        return pick("spd", tier, poles=c.poles, electrical__spd_type="2") or pick(
            "spd", tier, poles__gte=c.poles, electrical__spd_type="2"
        )
    if c.kind == "meter":
        return pick(
            "meter",
            tier,
            electrical__bidirectional=True,
            electrical__phases=3 if c.poles == 4 else 1,
        )
    return None


def run_pv_check(project: Project, pv: PvSystem) -> tuple[PvResult, list[PvSuggestion]] | None:
    inp = pv_input(project, pv)
    if inp is None:
        return None
    result = analyze_pv(inp)
    return result, [
        PvSuggestion(c, suggest_pv_product(c, project.price_tier, pv)) for c in result.components
    ]


def apply_pv_to_panel(project: Project, pv: PvSystem) -> ApplyResult:
    checked = run_pv_check(project, pv)
    if checked is None:
        raise ApplyError("Выберите панель и инвертор", "empty")
    result, suggestions = checked
    errors = [f for f in result.findings if f.level == "error"]
    if errors:
        raise ApplyError("Конфигурация PV содержит ошибки", "has_errors", errors)
    missing = [s.component for s in suggestions if s.product is None]
    if missing:
        names = ", ".join(c.role for c in missing)
        raise ApplyError(f"В каталоге нет подходящих изделий: {names}", "no_product")
    places = [
        PlaceItem(s.product, s.component.qty, LABELS.get(s.component.role, s.component.role))
        for s in suggestions
        if s.component.placed and s.product is not None
    ]
    if not places:
        raise ApplyError("Нечего размещать в DC-боксе", "empty")
    return build_panel(project, PanelKind.DC, PANEL_NAME, places)
