from dataclasses import asdict
from datetime import date
from typing import Any

from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from exports.db import collect_bom
from exports.pdf import Drawing, build_pdf
from exports.xlsx import build_xlsx
from projects.models import Project

from .serializers import BomSerializer, PdfExportRequestSerializer

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class _ExportBase(APIView):
    permission_classes = [IsAuthenticated]

    def project(self, request: Request, pk: int) -> Project:
        return get_object_or_404(Project.objects.for_user(request.user), pk=pk)


def bom_payload(bom: Any) -> dict[str, Any]:
    data = asdict(bom)
    for s in data["sections"]:
        s["total"] = f"{s['total']:.2f}"
        for b in s["blocks"]:
            b["total"] = f"{b['total']:.2f}"
            for ln in b["lines"]:
                ln["unit_price"] = f"{ln['unit_price']:.2f}"
                ln["total"] = f"{ln['total']:.2f}"
    data["total"] = f"{bom.total:.2f}"
    return data


class BomView(_ExportBase):
    @extend_schema(responses=BomSerializer)
    def get(self, request: Request, pk: int) -> Response:
        """Bill of materials: «Щиты», «Солнечная система», «Резервное питание» and the total."""
        return Response(bom_payload(collect_bom(self.project(request, pk))))


def _attachment(content: bytes, content_type: str, name: str) -> HttpResponse:
    res = HttpResponse(content, content_type=content_type)
    res["Content-Disposition"] = f'attachment; filename="{name}"'
    return res


class XlsxExportView(_ExportBase):
    @extend_schema(responses={(200, XLSX_TYPE): OpenApiTypes.BINARY})
    def get(self, request: Request, pk: int) -> HttpResponse:
        project = self.project(request, pk)
        data = build_xlsx(project.name, collect_bom(project))
        return _attachment(data, XLSX_TYPE, f"specification-{project.pk}.xlsx")


class PdfExportView(_ExportBase):
    @extend_schema(responses={(200, "application/pdf"): OpenApiTypes.BINARY})
    def get(self, request: Request, pk: int) -> HttpResponse:
        """PDF with the bill of materials only."""
        return self._pdf(self.project(request, pk), [])

    @extend_schema(
        request=PdfExportRequestSerializer,
        responses={(200, "application/pdf"): OpenApiTypes.BINARY},
    )
    def post(self, request: Request, pk: int) -> HttpResponse:
        """PDF with the bill of materials plus board views / single-line diagrams (SVG)."""
        project = self.project(request, pk)
        ser = PdfExportRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        mine = set(project.panels.values_list("pk", flat=True))
        drawings = [
            Drawing(d["panel_id"], d["kind"], d["svg"])
            for d in ser.validated_data["images"]
            if d["panel_id"] in mine
        ]
        return self._pdf(project, drawings)

    def _pdf(self, project: Project, drawings: list[Drawing]) -> HttpResponse:
        data = build_pdf(project, collect_bom(project), drawings, date.today())
        return _attachment(data, "application/pdf", f"specification-{project.pk}.pdf")
