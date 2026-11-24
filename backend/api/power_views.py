from dataclasses import asdict
from decimal import Decimal
from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from power.apply import ApplyError, apply_to_panel
from power.db import get_or_create_power, run_check
from power.models import PowerSystem
from power.pv_db import apply_pv_to_panel, get_or_create_pv, run_pv_check
from power.services import Switches
from power.sim_db import run_simulation
from projects.models import Project

from .serializers import (
    PanelSerializer,
    PlacementSerializer,
    PowerApplyResultSerializer,
    PowerCheckSerializer,
    PowerSystemSerializer,
    ProductSerializer,
    PvCheckSerializer,
    PvSystemSerializer,
    SimResultSerializer,
    SimSwitchesSerializer,
)


class _PowerBase(APIView):
    permission_classes = [IsAuthenticated]

    def project(self, request: Request, pk: int) -> Project:
        return get_object_or_404(Project.objects.for_user(request.user), pk=pk)


class PowerView(_PowerBase):
    @extend_schema(responses=PowerSystemSerializer)
    def get(self, request: Request, pk: int) -> Response:
        """Backup-power configuration of the project (created with defaults on first use)."""
        ps = get_or_create_power(self.project(request, pk))
        return Response(PowerSystemSerializer(ps).data)

    @extend_schema(request=PowerSystemSerializer, responses=PowerSystemSerializer)
    def put(self, request: Request, pk: int) -> Response:
        return self._save(request, pk, partial=False)

    @extend_schema(request=PowerSystemSerializer, responses=PowerSystemSerializer)
    def patch(self, request: Request, pk: int) -> Response:
        return self._save(request, pk, partial=True)

    def _save(self, request: Request, pk: int, *, partial: bool) -> Response:
        ps = get_or_create_power(self.project(request, pk))
        ser = PowerSystemSerializer(ps, data=request.data, partial=partial)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data)


def check_payload(project: Project, ps: PowerSystem) -> dict[str, Any]:
    result, suggestions = run_check(project, ps)
    total = Decimal("0")
    comps = []
    for s in suggestions:
        price_total: str | None = None
        if s.product is not None:
            line = s.product.price * s.component.qty
            total += line
            price_total = f"{line:.2f}"
        comps.append(
            {
                **asdict(s.component),
                "product": ProductSerializer(s.product).data if s.product else None,
                "price_total": price_total,
            }
        )
    return {
        "ok": result.ok,
        "description": result.description,
        "metrics": asdict(result.metrics),
        "findings": [asdict(f) for f in result.findings],
        "components": comps,
        "total_price": f"{total:.2f}",
    }


class PowerCheckView(_PowerBase):
    @extend_schema(responses=PowerCheckSerializer)
    def get(self, request: Request, pk: int) -> Response:
        """Power, autonomy and safety checks plus the switchgear selected for the scenario."""
        project = self.project(request, pk)
        ps = get_or_create_power(project)
        return Response(check_payload(project, ps))


class PowerApplyView(_PowerBase):
    @extend_schema(request=None, responses={201: PowerApplyResultSerializer})
    def post(self, request: Request, pk: int) -> Response:
        """Create (or rebuild) the backup panel from the checked configuration."""
        project = self.project(request, pk)
        ps = get_or_create_power(project)
        try:
            res = apply_to_panel(project, ps)
        except ApplyError as exc:
            return Response(
                {
                    "code": exc.code,
                    "detail": str(exc),
                    "findings": [asdict(f) for f in exc.findings],
                },
                status=status.HTTP_409_CONFLICT,
            )
        return Response(
            {
                "panel": PanelSerializer(res.panel).data,
                "placements": PlacementSerializer(res.placements, many=True).data,
            },
            status=status.HTTP_201_CREATED,
        )


class PvView(_PowerBase):
    @extend_schema(responses=PvSystemSerializer)
    def get(self, request: Request, pk: int) -> Response:
        """PV configuration of the project (created empty on first use)."""
        pv = get_or_create_pv(self.project(request, pk))
        return Response(PvSystemSerializer(pv).data)

    @extend_schema(request=PvSystemSerializer, responses=PvSystemSerializer)
    def put(self, request: Request, pk: int) -> Response:
        return self._save(request, pk, partial=False)

    @extend_schema(request=PvSystemSerializer, responses=PvSystemSerializer)
    def patch(self, request: Request, pk: int) -> Response:
        return self._save(request, pk, partial=True)

    def _save(self, request: Request, pk: int, *, partial: bool) -> Response:
        pv = get_or_create_pv(self.project(request, pk))
        ser = PvSystemSerializer(pv, data=request.data, partial=partial)
        ser.is_valid(raise_exception=True)
        ser.save()
        pv.refresh_from_db()
        return Response(PvSystemSerializer(pv).data)


def pv_check_payload(project: Project, pv: Any) -> dict[str, Any]:
    checked = run_pv_check(project, pv)
    if checked is None:
        return {
            "configured": False,
            "ok": False,
            "description": "Выберите солнечную панель и инвертор",
            "metrics": None,
            "arrays": [],
            "findings": [],
            "components": [],
            "total_price": "0.00",
        }
    result, suggestions = checked
    total = Decimal("0")
    comps = []
    for s in suggestions:
        price_total: str | None = None
        if s.product is not None:
            line = s.product.price * s.component.qty
            total += line
            price_total = f"{line:.2f}"
        comps.append(
            {
                **asdict(s.component),
                "product": ProductSerializer(s.product).data if s.product else None,
                "price_total": price_total,
            }
        )
    return {
        "configured": True,
        "ok": result.ok,
        "description": result.description,
        "metrics": asdict(result.metrics),
        "arrays": [asdict(a) for a in result.arrays],
        "findings": [asdict(f) for f in result.findings],
        "components": comps,
        "total_price": f"{total:.2f}",
    }


class PvCheckView(_PowerBase):
    @extend_schema(responses=PvCheckSerializer)
    def get(self, request: Request, pk: int) -> Response:
        """String, voltage, current, cable and yield checks plus the bill of the PV system."""
        project = self.project(request, pk)
        return Response(pv_check_payload(project, get_or_create_pv(project)))


class PvApplyView(_PowerBase):
    @extend_schema(request=None, responses={201: PowerApplyResultSerializer})
    def post(self, request: Request, pk: int) -> Response:
        """Create (or rebuild) the DC box panel from the checked PV configuration."""
        project = self.project(request, pk)
        try:
            res = apply_pv_to_panel(project, get_or_create_pv(project))
        except ApplyError as exc:
            return Response(
                {
                    "code": exc.code,
                    "detail": str(exc),
                    "findings": [asdict(f) for f in exc.findings],
                },
                status=status.HTTP_409_CONFLICT,
            )
        return Response(
            {
                "panel": PanelSerializer(res.panel).data,
                "placements": PlacementSerializer(res.placements, many=True).data,
            },
            status=status.HTTP_201_CREATED,
        )


class SimulateView(_PowerBase):
    @extend_schema(parameters=[SimSwitchesSerializer], responses=SimResultSerializer)
    def get(self, request: Request, pk: int) -> Response:
        """Static power simulation for the given switch positions (query parameters)."""
        project = self.project(request, pk)
        ser = SimSwitchesSerializer(data=request.query_params)
        ser.is_valid(raise_exception=True)
        res = run_simulation(project, Switches(**ser.validated_data))
        return Response(SimResultSerializer(asdict(res)).data)
