from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import QuerySet
from django.http import HttpResponse
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from calculations import calculate_project
from catalog.analogs import find_analogs
from catalog.csv_io import export_csv, import_csv
from catalog.models import Brand, Category, Product
from panels.autolayout_db import AutolayoutError, AutolayoutOptions, autolayout
from panels.layout_db import (
    create_version,
    enclosure_geometry,
    placement_spec,
    restore_version,
    to_specs,
    validate_panel,
)
from panels.models import LayoutVersion, Placement
from panels.services.layout import Issue, RailSpec, required_width, validate_layout
from projects.models import ConsumerGroup, Panel, PanelLink, Project
from projects.services import autoselect_project, build_inputs

from . import filters
from .serializers import (
    AutolayoutOptionsSerializer,
    AutolayoutResultSerializer,
    BrandSerializer,
    BulkPlacementsSerializer,
    CalculationSerializer,
    CategorySerializer,
    ConsumerGroupSerializer,
    IssueSerializer,
    LayoutVersionSerializer,
    PanelLinkSerializer,
    PanelSerializer,
    PlacementSerializer,
    ProductSerializer,
    ProjectSerializer,
    calculation_to_dict,
    django_errors,
)


def _issues_error(issues: list[Issue]) -> serializers.ValidationError:
    return serializers.ValidationError(
        {
            "layout": [
                {"code": i.code, "message": i.message, "key": i.key, "other_key": i.other_key}
                for i in issues
            ]
        }
    )


# ----------------------------------------------------------------- mixins
class OwnedMixin:
    """Object-level access: users only ever see their own projects and children.

    Foreign objects answer 404, not 403, so ids of other users' data don't leak.
    """

    request: Request
    kwargs: dict[str, Any]
    permission_classes = [IsAuthenticated]

    def is_schema(self) -> bool:
        return bool(getattr(self, "swagger_fake_view", False))

    def owned_project(self, pk: int | str) -> Project:
        return get_object_or_404(Project.objects.for_user(self.request.user), pk=pk)

    def owned_panel(self, pk: int | str) -> Panel:
        return get_object_or_404(
            Panel.objects.select_related("project", "enclosure").filter(
                project__owner=self.request.user
            ),
            pk=pk,
        )


# --------------------------------------------------------------- projects
class ProjectViewSet(OwnedMixin, viewsets.ModelViewSet[Project]):
    serializer_class = ProjectSerializer

    def get_queryset(self) -> QuerySet[Project]:
        if self.is_schema():
            return Project.objects.none()
        return Project.objects.for_user(self.request.user)

    def perform_create(self, serializer: serializers.BaseSerializer[Project]) -> None:
        serializer.save(owner=self.request.user)

    @extend_schema(responses=CalculationSerializer)
    @action(detail=True, methods=["get"], url_path="calc")
    def calc(self, request: Request, pk: str | None = None) -> Response:
        """Calculate (without saving): demand, phases, RCDs, per-group selection, findings."""
        project = self.get_object()
        groups, system = build_inputs(project)
        try:
            result = calculate_project(groups, system)
        except ValueError as exc:
            raise serializers.ValidationError({"detail": str(exc)}) from exc
        return Response(calculation_to_dict(result))


class PanelViewSet(OwnedMixin, viewsets.ModelViewSet[Panel]):
    serializer_class = PanelSerializer

    def get_queryset(self) -> QuerySet[Panel]:
        if self.is_schema():
            return Panel.objects.none()
        qs = Panel.objects.select_related("project", "enclosure").prefetch_related("rails")
        qs = qs.filter(project__owner=self.request.user)
        if "project_pk" in self.kwargs:
            qs = qs.filter(project_id=self.kwargs["project_pk"])
        return qs

    def get_serializer_context(self) -> dict[str, Any]:
        ctx = super().get_serializer_context()
        if "project_pk" in self.kwargs and not self.is_schema():
            ctx["project"] = self.owned_project(self.kwargs["project_pk"])
        return ctx

    def perform_create(self, serializer: serializers.BaseSerializer[Panel]) -> None:
        serializer.save(project=self.owned_project(self.kwargs["project_pk"]))

    @extend_schema(responses=IssueSerializer(many=True))
    @action(detail=True, methods=["get"], url_path="validate")
    def validate_layout(self, request: Request, pk: str | None = None) -> Response:
        """Server-side layout check: bounds, collisions, compatibility."""
        panel = self.get_object()
        return Response(
            [
                {"code": i.code, "message": i.message, "key": i.key, "other_key": i.other_key}
                for i in validate_panel(panel)
            ]
        )

    @extend_schema(
        request=AutolayoutOptionsSerializer,
        responses=AutolayoutResultSerializer,
    )
    @action(detail=True, methods=["post"], url_path="autolayout")
    def autolayout(self, request: Request, pk: str | None = None) -> Response:
        """Auto-layout: input devices, relay/SPD, RCDs with their breakers; picks an enclosure.

        Replaces all DIN-rail placements of the panel (mounting-panel items are kept).
        Unassigned groups of a main panel are assigned to it.
        """
        panel = self.get_object()
        opts_ser = AutolayoutOptionsSerializer(data=request.data)
        opts_ser.is_valid(raise_exception=True)
        try:
            res = autolayout(panel, AutolayoutOptions(**opts_ser.validated_data))
        except AutolayoutError as exc:
            body = {
                "code": exc.code,
                "detail": str(exc),
                "findings": [
                    {"level": f.level, "code": f.code, "message": f.message, "group_id": f.group_id}
                    for f in exc.findings
                ],
            }
            return Response(body, status=status.HTTP_409_CONFLICT)
        panel.refresh_from_db()
        return Response(
            {
                "placements": PlacementSerializer(res.placements, many=True).data,
                "required_modules": res.required_modules,
                "capacity_modules": res.capacity_modules,
                "enclosure": panel.enclosure_id,
                "enclosure_changed": res.enclosure_changed,
                "findings": [
                    {"level": f.level, "code": f.code, "message": f.message, "group_id": f.group_id}
                    for f in res.findings
                ],
            }
        )

    @extend_schema(responses=ConsumerGroupSerializer(many=True))
    @action(detail=True, methods=["get"], url_path="unplaced")
    def unplaced(self, request: Request, pk: str | None = None) -> Response:
        """Breakers of this panel's groups that are not yet placed on a rail/panel."""
        panel = self.get_object()
        groups = panel.groups.exclude(placements__panel=panel)
        return Response(ConsumerGroupSerializer(groups, many=True).data)


class PanelLinkViewSet(
    OwnedMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet[PanelLink],
):
    serializer_class = PanelLinkSerializer

    def get_queryset(self) -> QuerySet[PanelLink]:
        if self.is_schema():
            return PanelLink.objects.none()
        qs = PanelLink.objects.filter(source__project__owner=self.request.user)
        if "project_pk" in self.kwargs:
            qs = qs.filter(source__project_id=self.kwargs["project_pk"])
        return qs

    def get_serializer_context(self) -> dict[str, Any]:
        ctx = super().get_serializer_context()
        if "project_pk" in self.kwargs and not self.is_schema():
            ctx["project"] = self.owned_project(self.kwargs["project_pk"])
        return ctx


class ConsumerGroupViewSet(OwnedMixin, viewsets.ModelViewSet[ConsumerGroup]):
    serializer_class = ConsumerGroupSerializer

    def get_queryset(self) -> QuerySet[ConsumerGroup]:
        if self.is_schema():
            return ConsumerGroup.objects.none()
        qs = ConsumerGroup.objects.filter(project__owner=self.request.user)
        if "project_pk" in self.kwargs:
            qs = qs.filter(project_id=self.kwargs["project_pk"])
        return qs

    def _project(self) -> Project:
        if "project_pk" in self.kwargs:
            return self.owned_project(self.kwargs["project_pk"])
        return self.get_object().project

    def get_serializer_context(self) -> dict[str, Any]:
        ctx = super().get_serializer_context()
        if self.action != "autoselect" and not self.is_schema():
            ctx["project"] = self._project()
        return ctx

    def perform_create(self, serializer: serializers.BaseSerializer[ConsumerGroup]) -> None:
        serializer.save(project=self.owned_project(self.kwargs["project_pk"]))

    @extend_schema(request=None, responses=CalculationSerializer)
    @action(detail=False, methods=["post"], url_path="autoselect")
    def autoselect(self, request: Request, project_pk: str | None = None) -> Response:
        """Auto-select breaker, cable, RCD and phase for all groups and store the results."""
        project = self.owned_project(self.kwargs["project_pk"])
        try:
            result = autoselect_project(project)
        except ValueError as exc:
            raise serializers.ValidationError({"detail": str(exc)}) from exc
        return Response(calculation_to_dict(result))


# ------------------------------------------------------------- placements
class PlacementViewSet(OwnedMixin, viewsets.ModelViewSet[Placement]):
    serializer_class = PlacementSerializer

    def get_queryset(self) -> QuerySet[Placement]:
        if self.is_schema():
            return Placement.objects.none()
        qs = Placement.objects.select_related("product", "product__category", "panel")
        qs = qs.filter(panel__project__owner=self.request.user)
        if "panel_pk" in self.kwargs:
            qs = qs.filter(panel_id=self.kwargs["panel_pk"])
        return qs

    def _panel(self) -> Panel:
        if "panel_pk" in self.kwargs:
            return self.owned_panel(self.kwargs["panel_pk"])
        return self.get_object().panel

    def get_serializer_context(self) -> dict[str, Any]:
        ctx = super().get_serializer_context()
        if not self.is_schema() and self.action != "bulk":
            ctx["panel"] = self._panel()
        return ctx

    def _check_layout(self, panel: Panel, new: Placement, replacing: Placement | None) -> None:
        others = [
            p
            for p in panel.placements.select_related("product")
            if replacing is None or p.pk != replacing.pk
        ]
        rails, specs, area = to_specs(panel, others)
        specs.append(placement_spec(new, key="__new__"))
        issues = [
            i
            for i in validate_layout(rails, specs, area)
            if i.key == "__new__" or i.other_key == "__new__"
        ]
        if issues:
            raise _issues_error(issues)

    @transaction.atomic
    def perform_create(self, serializer: serializers.BaseSerializer[Placement]) -> None:
        panel = self.owned_panel(self.kwargs["panel_pk"])
        Panel.objects.select_for_update().get(pk=panel.pk)  # serialize concurrent edits
        data = serializer.validated_data
        candidate = Placement(panel=panel, **data)
        self._check_layout(panel, candidate, None)
        serializer.save(panel=panel)

    @transaction.atomic
    def perform_update(self, serializer: serializers.BaseSerializer[Placement]) -> None:
        inst: Placement = serializer.instance  # type: ignore[assignment]
        Panel.objects.select_for_update().get(pk=inst.panel_id)
        data = serializer.validated_data
        candidate = Placement(
            panel=inst.panel,
            **{
                f: data.get(f, getattr(inst, f))
                for f in (
                    "rail",
                    "product",
                    "group",
                    "start_module",
                    "width_modules",
                    "x_mm",
                    "y_mm",
                    "w_mm",
                    "h_mm",
                    "label",
                )
            },
        )
        self._check_layout(inst.panel, candidate, inst)
        serializer.save()

    @extend_schema(
        request=BulkPlacementsSerializer,
        responses=PlacementSerializer(many=True),
        parameters=[OpenApiParameter("panel_pk", int, OpenApiParameter.PATH)],
    )
    @action(detail=False, methods=["put", "patch"], url_path="bulk")
    @transaction.atomic
    def bulk(self, request: Request, panel_pk: str | None = None) -> Response:
        """Autosave: replace the panel's placements with the given full state, atomically.

        Items with ``id`` are updated, items without are created, existing placements that
        are absent from the payload are deleted. The whole result is validated first;
        on any issue nothing is changed.
        """
        panel = self.owned_panel(self.kwargs["panel_pk"])
        Panel.objects.select_for_update().get(pk=panel.pk)
        ser = BulkPlacementsSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        items = ser.validated_data["placements"]

        existing = {p.pk: p for p in panel.placements.all()}
        rails = {r.pk: r for r in panel.rails.all()}
        products = {
            p.pk: p
            for p in Product.objects.select_related("category").filter(
                pk__in={i["product"] for i in items}
            )
        }
        groups = {
            g.pk: g
            for g in ConsumerGroup.objects.filter(
                project=panel.project, pk__in={i["group"] for i in items if i.get("group")}
            )
        }
        seen: set[int] = set()
        candidates: list[tuple[Placement | None, Placement]] = []
        errors: dict[str, Any] = {}
        for n, item in enumerate(items):
            pid = item.get("id")
            if pid is not None:
                if pid not in existing or pid in seen:
                    raise serializers.ValidationError({"placements": f"[{n}] неизвестный id {pid}"})
                seen.add(pid)
            product = products.get(item["product"])
            if product is None:
                errors[str(n)] = {"product": "Изделие не найдено"}
                continue
            rail = None
            if item.get("rail") is not None:
                rail = rails.get(item["rail"])
                if rail is None:
                    errors[str(n)] = {"rail": "Рейка не принадлежит щиту"}
                    continue
            group = None
            if item.get("group") is not None:
                group = groups.get(item["group"])
                if group is None:
                    errors[str(n)] = {"group": "Группа не принадлежит проекту"}
                    continue
                if product.category.code not in {"mcb", "rcbo", "rcd", "contactor"}:
                    errors[str(n)] = {"group": "Недопустимый тип изделия для группы"}
                    continue
            width = item.get("width_modules")
            if width is None:
                width = required_width(float(product.modules)) if rail else 0
            cand = Placement(
                panel=panel,
                rail=rail,
                product=product,
                group=group,
                start_module=item.get("start_module"),
                width_modules=width,
                x_mm=item.get("x_mm"),
                y_mm=item.get("y_mm"),
                w_mm=item.get("w_mm"),
                h_mm=item.get("h_mm"),
                label=item.get("label", ""),
            )
            candidates.append((existing.get(pid) if pid is not None else None, cand))
        if errors:
            raise serializers.ValidationError({"placements": errors})

        specs = [placement_spec(c, key=str(i)) for i, (_, c) in enumerate(candidates)]
        _, _, area = enclosure_geometry(panel)
        issues = validate_layout(
            [RailSpec(r.pk, r.capacity_modules) for r in rails.values()], specs, area
        )
        if issues:
            for i in issues:
                i_key = int(i.key)
                errors.setdefault(str(i_key), []).append({"code": i.code, "message": i.message})
            raise serializers.ValidationError({"placements": errors})

        # Apply: delete absent, update/create present.
        for pid, obj in existing.items():
            if pid not in seen:
                obj.delete()
        saved: list[Placement] = []
        for old, cand in candidates:
            if old is None:
                cand.save()
                saved.append(cand)
            else:
                for f in (
                    "rail",
                    "product",
                    "group",
                    "start_module",
                    "width_modules",
                    "x_mm",
                    "y_mm",
                    "w_mm",
                    "h_mm",
                    "label",
                ):
                    setattr(old, f, getattr(cand, f))
                old.save()
                saved.append(old)
        return Response(PlacementSerializer(saved, many=True).data)


class VersionViewSet(
    OwnedMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet[LayoutVersion],
):
    serializer_class = LayoutVersionSerializer

    def get_queryset(self) -> QuerySet[LayoutVersion]:
        if self.is_schema():
            return LayoutVersion.objects.none()
        qs = LayoutVersion.objects.filter(panel__project__owner=self.request.user)
        if "panel_pk" in self.kwargs:
            qs = qs.filter(panel_id=self.kwargs["panel_pk"])
        return qs

    def perform_create(self, serializer: serializers.BaseSerializer[LayoutVersion]) -> None:
        panel = self.owned_panel(self.kwargs["panel_pk"])
        serializer.instance = create_version(panel, serializer.validated_data.get("note", ""))

    @extend_schema(request=None, responses=PlacementSerializer(many=True))
    @action(detail=True, methods=["post"], url_path="restore")
    def restore(self, request: Request, pk: str | None = None) -> Response:
        version = self.get_object()
        try:
            restore_version(version)
        except DjangoValidationError as exc:
            raise django_errors(exc) from exc
        return Response(PlacementSerializer(version.panel.placements.all(), many=True).data)


# ---------------------------------------------------------------- catalog
class BrandViewSet(viewsets.ReadOnlyModelViewSet[Brand]):
    queryset = Brand.objects.all()
    serializer_class = BrandSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None


class CategoryViewSet(viewsets.ReadOnlyModelViewSet[Category]):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None


class ProductViewSet(viewsets.ReadOnlyModelViewSet[Product]):
    queryset = Product.objects.select_related("brand", "category")
    serializer_class = ProductSerializer
    permission_classes = [IsAuthenticated]
    filterset_class = filters.ProductFilter

    @extend_schema(
        parameters=[OpenApiParameter("tier", str, description="eco | mid | premium")],
        responses=ProductSerializer(many=True),
    )
    @action(detail=True, methods=["get"], url_path="analogs")
    def analogs(self, request: Request, pk: str | None = None) -> Response:
        """Functional analogs in other brands, cheapest first; optional ``tier`` filter."""
        # Not get_object(): list filters (e.g. ?tier=) must not apply to the base product.
        product = get_object_or_404(self.get_queryset(), pk=pk)
        tier = request.query_params.get("tier") or None
        try:
            qs = find_analogs(product, tier)
        except ValueError as exc:
            raise serializers.ValidationError({"tier": str(exc)}) from exc
        return Response(ProductSerializer(qs, many=True).data)


class CatalogExportView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(responses={(200, "text/csv"): bytes})
    def get(self, request: Request) -> HttpResponse:
        resp = HttpResponse(export_csv(), content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="catalog.csv"'
        return resp


class CatalogImportView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {"file": {"type": "string", "format": "binary"}},
            }
        },
        responses={200: {"type": "object"}},
    )
    def post(self, request: Request) -> Response:
        upload = request.FILES.get("file")
        if upload is None:
            raise serializers.ValidationError({"file": "Нужен CSV-файл"})
        try:
            text = upload.read().decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise serializers.ValidationError({"file": "Нужна кодировка UTF-8"}) from exc
        result = import_csv(text)
        body = {"created": result.created, "updated": result.updated, "errors": result.errors}
        return Response(
            body, status=status.HTTP_200_OK if result.ok else status.HTTP_400_BAD_REQUEST
        )
