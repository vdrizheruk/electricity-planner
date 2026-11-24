"""PDF export of the bill of materials with drawings (WeasyPrint).

Drawings are SVG pictures made by the editor. They are embedded as ``data:`` images and the
URL fetcher refuses everything else, so an uploaded SVG cannot make the server read local files
or call other hosts.
"""

import base64
from dataclasses import dataclass
from datetime import date
from typing import Any

from django.template.loader import render_to_string
from weasyprint import HTML, URLFetcher

from projects.models import Project

from .services.bom import Bom

MAX_SVG_BYTES = 2_000_000
KIND_CAPTION = {"board": "Вид щита", "diagram": "Однолинейная схема"}


@dataclass(frozen=True)
class Drawing:
    panel_id: int
    kind: str  # board | diagram
    svg: str


def _data_uri(svg: str) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def group_drawings(project: Project, drawings: list[Drawing]) -> list[dict[str, Any]]:
    """One page group per panel, board view first, in the panel order."""
    names = {p.pk: p.name for p in project.panels.order_by("id")}
    out: list[dict[str, Any]] = []
    for panel_id, name in names.items():
        mine = [d for d in drawings if d.panel_id == panel_id]
        mine.sort(key=lambda d: 0 if d.kind == "board" else 1)
        if mine:
            out.append(
                {
                    "title": name,
                    "images": [
                        {"caption": KIND_CAPTION.get(d.kind, d.kind), "src": _data_uri(d.svg)}
                        for d in mine
                    ],
                }
            )
    return out


def build_pdf(
    project: Project, bom: Bom, drawings: list[Drawing] | None = None, today: date | None = None
) -> bytes:
    html = render_to_string(
        "exports/spec.html",
        {
            "project": project,
            "bom": bom,
            "today": today or date.today(),
            "drawings": group_drawings(project, drawings or []),
        },
    )
    return HTML(string=html, url_fetcher=URLFetcher(allowed_protocols={"data"})).write_pdf()  # type: ignore[no-any-return]
