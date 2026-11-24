"""Create the backup panel (ATS, in/out breakers, SPD, RCD…) from a checked configuration."""

from projects.models import PanelKind, Project

from .db import run_check
from .models import PowerSystem
from .panel_builder import ApplyError, ApplyResult, PlaceItem, build_panel

PANEL_NAME = "Щит резерва"

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

__all__ = ["ApplyError", "ApplyResult", "apply_to_panel"]


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
    places = [
        PlaceItem(s.product, s.component.qty, LABELS.get(s.component.role, s.component.role))
        for s in suggestions
        if s.product is not None
    ]
    return build_panel(project, PanelKind.BACKUP, PANEL_NAME, places)
