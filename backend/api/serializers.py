from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers

from calculations.models import ProjectCalculation
from catalog.models import Brand, Category, Product
from panels.layout_db import enclosure_geometry, sync_rails
from panels.models import DinRail, LayoutVersion, Placement
from panels.services.layout import required_width
from power.models import PowerSystem, PvArray, PvSystem
from projects.models import ConsumerGroup, Panel, PanelLink, Project

PLACEABLE_GROUP_CATEGORIES = {"mcb", "rcbo", "rcd", "contactor"}


def django_errors(exc: DjangoValidationError) -> serializers.ValidationError:
    return serializers.ValidationError(exc.messages)


# ---------------------------------------------------------------- catalog
class BrandSerializer(serializers.ModelSerializer[Brand]):
    class Meta:
        model = Brand
        fields = ["id", "name", "slug", "tier"]


class CategorySerializer(serializers.ModelSerializer[Category]):
    class Meta:
        model = Category
        fields = ["id", "code", "name_ru", "name_uk"]


class ProductSerializer(serializers.ModelSerializer[Product]):
    brand = BrandSerializer(read_only=True)
    category = CategorySerializer(read_only=True)

    class Meta:
        model = Product
        fields = [
            "id",
            "brand",
            "category",
            "sku",
            "name",
            "series",
            "tier",
            "rated_a",
            "poles",
            "curve",
            "leakage_ma",
            "rcd_type",
            "modules",
            "width_mm",
            "height_mm",
            "depth_mm",
            "din_mountable",
            "electrical",
            "price",
            "price_date",
            "needs_verification",
        ]
        read_only_fields = fields


# --------------------------------------------------------------- projects
class ProjectSerializer(serializers.ModelSerializer[Project]):
    class Meta:
        model = Project
        fields = [
            "id",
            "name",
            "object_type",
            "grid",
            "main_breaker_a",
            "earthing",
            "price_tier",
            "tmin_c",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class DinRailSerializer(serializers.ModelSerializer[DinRail]):
    class Meta:
        model = DinRail
        fields = ["id", "row_index", "capacity_modules"]
        read_only_fields = fields


class PanelSerializer(serializers.ModelSerializer[Panel]):
    rails = DinRailSerializer(many=True, read_only=True)
    enclosure = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.filter(category__code="enclosure"),
        allow_null=True,
        required=False,
    )
    mounting_area_mm = serializers.SerializerMethodField()

    class Meta:
        model = Panel
        fields = [
            "id",
            "project",
            "name",
            "kind",
            "enclosure",
            "ip",
            "mounting",
            "diagram_positions",
            "rails",
            "mounting_area_mm",
        ]
        read_only_fields = ["id", "project", "rails", "mounting_area_mm"]

    def validate_diagram_positions(self, value: Any) -> dict[str, dict[str, float]]:
        if not isinstance(value, dict) or len(value) > 1000:
            raise serializers.ValidationError("Ожидается объект не более чем с 1000 узлами")
        for key, pos in value.items():
            if not isinstance(key, str) or not 0 < len(key) <= 40:
                raise serializers.ValidationError("Неверный идентификатор узла")
            if not isinstance(pos, dict) or set(pos) != {"x", "y"}:
                raise serializers.ValidationError(f"{key}: ожидается {{x, y}}")
            for axis in ("x", "y"):
                v = pos[axis]
                if isinstance(v, bool) or not isinstance(v, int | float) or abs(v) > 100_000:
                    raise serializers.ValidationError(f"{key}.{axis}: неверное число")
        return value  # type: ignore[no-any-return]

    def get_mounting_area_mm(self, obj: Panel) -> dict[str, int | None]:
        _, _, area = enclosure_geometry(obj)
        return {"width": area.width_mm, "height": area.height_mm}

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        project: Project | None = self.context.get("project")
        if project is None and self.instance is not None:
            project = self.instance.project
        name = attrs.get("name")
        if project is not None and name is not None:
            clash = Panel.objects.filter(project=project, name=name)
            if self.instance is not None:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                raise serializers.ValidationError({"name": "Щит с таким названием уже есть"})
        enclosure: Product | None = attrs.get("enclosure")
        if enclosure is not None:
            el = enclosure.electrical or {}
            if "ip" in el and "ip" not in attrs:
                attrs["ip"] = el["ip"]
            if "mounting" in el and "mounting" not in attrs:
                attrs["mounting"] = el["mounting"]
        return attrs

    def create(self, validated_data: dict[str, Any]) -> Panel:
        try:
            panel = super().create(validated_data)
            sync_rails(panel)
        except DjangoValidationError as exc:
            raise django_errors(exc) from exc
        return panel

    def update(self, instance: Panel, validated_data: dict[str, Any]) -> Panel:
        try:
            panel = super().update(instance, validated_data)
            if "enclosure" in validated_data:
                sync_rails(panel)
        except DjangoValidationError as exc:
            raise django_errors(exc) from exc
        return panel


class PanelLinkSerializer(serializers.ModelSerializer[PanelLink]):
    class Meta:
        model = PanelLink
        fields = ["id", "source", "target", "feeder_breaker_a"]
        read_only_fields = ["id"]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        project: Project = self.context["project"]
        for side in ("source", "target"):
            panel = attrs.get(side)
            if panel is not None and panel.project_id != project.pk:
                raise serializers.ValidationError({side: "Щит не принадлежит проекту"})
        return attrs

    def create(self, validated_data: dict[str, Any]) -> PanelLink:
        try:
            return super().create(validated_data)
        except DjangoValidationError as exc:
            raise django_errors(exc) from exc


class ConsumerGroupSerializer(serializers.ModelSerializer[ConsumerGroup]):
    class Meta:
        model = ConsumerGroup
        fields = [
            "id",
            "panel",
            "name",
            "room",
            "type",
            "power_w",
            "cos_phi",
            "phase",
            "length_m",
            "backed_up",
            "wet_zone",
            "assigned_phase",
            "breaker_a",
            "curve",
            "cable_mm2",
            "rcd_ma",
            "voltage_drop_pct",
        ]
        read_only_fields = [
            "id",
            "assigned_phase",
            "breaker_a",
            "curve",
            "cable_mm2",
            "rcd_ma",
            "voltage_drop_pct",
        ]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        project: Project = self.context["project"]
        panel = attrs.get("panel")
        if panel is not None and panel.project_id != project.pk:
            raise serializers.ValidationError({"panel": "Щит не принадлежит проекту"})
        phase = attrs.get("phase")
        grid = project.grid
        if phase == "3ph" and grid != "3ph":
            raise serializers.ValidationError({"phase": "3ф нагрузка при однофазном вводе"})
        if phase in ("L2", "L3") and grid != "3ph":
            raise serializers.ValidationError({"phase": "Фаза недоступна при однофазном вводе"})
        return attrs


# ------------------------------------------------------------- placements
class PlacementSerializer(serializers.ModelSerializer[Placement]):
    class Meta:
        model = Placement
        fields = [
            "id",
            "panel",
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
        ]
        read_only_fields = ["id", "panel"]
        extra_kwargs = {"width_modules": {"required": False}}

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        panel: Panel = self.context["panel"]
        inst: Placement | None = self.instance  # type: ignore[assignment]

        def val(name: str) -> Any:
            return attrs[name] if name in attrs else getattr(inst, name, None)

        rail: DinRail | None = val("rail")
        product: Product = val("product")
        group: ConsumerGroup | None = val("group")
        if rail is not None and rail.panel_id != panel.pk:
            raise serializers.ValidationError({"rail": "Рейка не принадлежит щиту"})
        if group is not None:
            if group.project_id != panel.project_id:
                raise serializers.ValidationError({"group": "Группа не принадлежит проекту"})
            if product.category.code not in PLACEABLE_GROUP_CATEGORIES:
                raise serializers.ValidationError(
                    {"group": "К группе можно привязать только автомат/УЗО/дифавтомат/контактор"}
                )
        if rail is not None and "width_modules" not in attrs:
            attrs["width_modules"] = required_width(float(product.modules))
        return attrs


# --------------------------------------------------------------- versions
class LayoutVersionSerializer(serializers.ModelSerializer[LayoutVersion]):
    class Meta:
        model = LayoutVersion
        fields = ["id", "number", "note", "created_at"]
        read_only_fields = ["id", "number", "created_at"]


class IssueSerializer(serializers.Serializer[None]):
    code = serializers.CharField()
    message = serializers.CharField()
    key = serializers.CharField()
    other_key = serializers.CharField(allow_null=True)


class BulkPlacementItemSerializer(serializers.Serializer[None]):
    id = serializers.IntegerField(required=False)
    rail = serializers.IntegerField(required=False, allow_null=True)
    product = serializers.IntegerField()
    group = serializers.IntegerField(required=False, allow_null=True)
    start_module = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    width_modules = serializers.IntegerField(required=False, min_value=0)
    x_mm = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    y_mm = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    w_mm = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    h_mm = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    label = serializers.CharField(required=False, allow_blank=True, max_length=64)


class BulkPlacementsSerializer(serializers.Serializer[None]):
    """Autosave payload: full desired state of the panel's placements."""

    placements = BulkPlacementItemSerializer(many=True)


# ------------------------------------------------------------ calculation
class GroupResultSerializer(serializers.Serializer[None]):
    group_id = serializers.IntegerField()
    phase = serializers.CharField()
    ib_a = serializers.FloatField()
    breaker_a = serializers.IntegerField()
    curve = serializers.CharField()
    cable_mm2 = serializers.FloatField()
    voltage_drop_pct = serializers.FloatField()
    protection = serializers.CharField()
    rcd_ma = serializers.IntegerField(allow_null=True)
    rcd_type = serializers.CharField(allow_blank=True)
    demand_factor = serializers.FloatField()
    demand_va = serializers.FloatField()


class RcdSerializer(serializers.Serializer[None]):
    id = serializers.IntegerField()
    phase = serializers.CharField()
    poles = serializers.IntegerField()
    rating_a = serializers.IntegerField()
    leakage_ma = serializers.IntegerField()
    rcd_type = serializers.CharField()
    group_ids = serializers.ListField(child=serializers.IntegerField())
    backed_up = serializers.BooleanField()
    demand_a = serializers.FloatField()


class DemandSerializer(serializers.Serializer[None]):
    installed_w = serializers.FloatField()
    demand_w = serializers.FloatField()
    demand_va = serializers.FloatField()
    diversity = serializers.FloatField()
    design_current_a = serializers.FloatField()
    main_breaker_a = serializers.IntegerField()
    main_ok = serializers.BooleanField()


class PhasesSerializer(serializers.Serializer[None]):
    loads_va = serializers.DictField(child=serializers.FloatField())
    imbalance_pct = serializers.FloatField()
    exceeds_limit = serializers.BooleanField()
    assignment = serializers.DictField(child=serializers.CharField())


class FindingSerializer(serializers.Serializer[None]):
    level = serializers.ChoiceField(choices=["error", "warning", "info"])
    code = serializers.CharField()
    message = serializers.CharField()
    group_id = serializers.IntegerField(allow_null=True)


class CalculationSerializer(serializers.Serializer[None]):
    ok = serializers.BooleanField()
    groups = GroupResultSerializer(many=True)
    rcds = RcdSerializer(many=True)
    demand = DemandSerializer()
    phases = PhasesSerializer()
    findings = FindingSerializer(many=True)


def calculation_to_dict(calc: ProjectCalculation) -> dict[str, Any]:
    from dataclasses import asdict

    data = asdict(calc)
    data["ok"] = calc.ok
    data["phases"]["assignment"] = {str(k): v for k, v in calc.phases.assignment.items()}
    return data


class AutolayoutOptionsSerializer(serializers.Serializer[None]):
    voltage_relay = serializers.BooleanField(default=True)
    spd = serializers.ChoiceField(choices=["none", "2", "1+2"], default="2")
    fire_rcd = serializers.BooleanField(default=False)
    reserve_pct = serializers.IntegerField(default=20, min_value=0, max_value=100)
    pick_enclosure = serializers.BooleanField(default=True)


class AutolayoutResultSerializer(serializers.Serializer[None]):
    placements = PlacementSerializer(many=True)
    required_modules = serializers.IntegerField()
    capacity_modules = serializers.IntegerField()
    enclosure = serializers.IntegerField(allow_null=True)
    enclosure_changed = serializers.BooleanField()
    findings = FindingSerializer(many=True)


# ------------------------------------------------------------------ power
class PowerSystemSerializer(serializers.ModelSerializer[PowerSystem]):
    generator = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.filter(category__code="generator"),
        allow_null=True,
        required=False,
    )
    inverter = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.filter(category__code="inverter"),
        allow_null=True,
        required=False,
    )
    battery = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.filter(category__code="battery"),
        allow_null=True,
        required=False,
    )

    class Meta:
        model = PowerSystem
        fields = [
            "id",
            "project",
            "scenario",
            "generator",
            "inverter",
            "inverter_count",
            "inverter_mode",
            "battery",
            "battery_count",
            "ats_kind",
            "ats_poles",
            "ats_rated_a",
            "mechanical_interlock",
            "electrical_interlock",
            "backup_phase",
            "autonomy_target_h",
        ]
        read_only_fields = ["id", "project"]


class PowerFindingSerializer(serializers.Serializer[None]):
    level = serializers.ChoiceField(choices=["error", "warning", "info"])
    code = serializers.CharField()
    message = serializers.CharField()


class PowerMetricsSerializer(serializers.Serializer[None]):
    p_backup_w = serializers.FloatField()
    s_backup_va = serializers.FloatField()
    p_start_w = serializers.FloatField()
    s_start_va = serializers.FloatField()
    phase_va = serializers.DictField(child=serializers.FloatField())
    i_backup_a = serializers.FloatField()
    imbalance_pct = serializers.FloatField()
    gen_required_kva = serializers.FloatField(allow_null=True)
    gen_required_kw = serializers.FloatField(allow_null=True)
    inverter_capacity_w = serializers.FloatField(allow_null=True)
    inverter_required_w = serializers.FloatField(allow_null=True)
    autonomy_h = serializers.FloatField(allow_null=True)
    battery_dc_a = serializers.FloatField(allow_null=True)
    battery_usable_kwh = serializers.FloatField(allow_null=True)


class PowerComponentSerializer(serializers.Serializer[None]):
    role = serializers.CharField()
    kind = serializers.CharField()
    poles = serializers.IntegerField()
    rated_a = serializers.FloatField()
    note = serializers.CharField()
    qty = serializers.IntegerField()
    product = ProductSerializer(allow_null=True)
    price_total = serializers.CharField(allow_null=True)


class PowerCheckSerializer(serializers.Serializer[None]):
    ok = serializers.BooleanField()
    description = serializers.CharField()
    metrics = PowerMetricsSerializer()
    findings = PowerFindingSerializer(many=True)
    components = PowerComponentSerializer(many=True)
    total_price = serializers.CharField()


class PowerApplyResultSerializer(serializers.Serializer[None]):
    panel = PanelSerializer()
    placements = PlacementSerializer(many=True)


# --------------------------------------------------------------------- pv
class PvArraySerializer(serializers.ModelSerializer[PvArray]):
    class Meta:
        model = PvArray
        fields = ["id", "mppt", "series", "strings", "azimuth_deg", "tilt_deg", "cable_m"]
        read_only_fields = ["id"]
        validators: list[Any] = []  # uniqueness is checked for the whole list


class PvSystemSerializer(serializers.ModelSerializer[PvSystem]):
    module = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.filter(category__code="pv_module"),
        allow_null=True,
        required=False,
    )
    inverter = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.filter(category__code="inverter"),
        allow_null=True,
        required=False,
    )
    arrays = PvArraySerializer(many=True, required=False)

    class Meta:
        model = PvSystem
        fields = [
            "id",
            "project",
            "module",
            "inverter",
            "inverter_count",
            "t_min_c",
            "t_cell_max_c",
            "region",
            "performance_ratio",
            "export_limit_w",
            "green_tariff",
            "arrays",
        ]
        read_only_fields = ["id", "project"]

    def validate_arrays(self, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        mppts = [a["mppt"] for a in value]
        if len(mppts) != len(set(mppts)):
            raise serializers.ValidationError("Один MPPT-вход указан дважды")
        return value

    def update(self, instance: PvSystem, validated_data: dict[str, Any]) -> PvSystem:
        arrays = validated_data.pop("arrays", None)
        with transaction.atomic():
            instance = super().update(instance, validated_data)
            if arrays is not None:
                instance.arrays.all().delete()
                PvArray.objects.bulk_create(PvArray(pv=instance, **a) for a in arrays)
        return instance


class PvArrayResultSerializer(serializers.Serializer[None]):
    mppt = serializers.IntegerField()
    modules = serializers.IntegerField()
    kwp = serializers.FloatField()
    voc_cold_v = serializers.FloatField()
    vmp_stc_v = serializers.FloatField()
    vmp_hot_v = serializers.FloatField()
    vmp_cold_v = serializers.FloatField()
    isc_a = serializers.FloatField()
    imp_a = serializers.FloatField()
    fuse_a = serializers.FloatField(allow_null=True)
    cable_mm2 = serializers.IntegerField()
    drop_pct = serializers.FloatField()
    yield_kwh = serializers.FloatField()


class PvMetricsSerializer(serializers.Serializer[None]):
    modules = serializers.IntegerField()
    kwp = serializers.FloatField()
    p_ac_w = serializers.FloatField()
    dc_ac_ratio = serializers.FloatField()
    clip_loss_pct = serializers.FloatField()
    yield_kwh_year = serializers.FloatField()
    specific_yield = serializers.FloatField()
    ac_breaker_a = serializers.FloatField()


class PvComponentSerializer(serializers.Serializer[None]):
    role = serializers.CharField()
    kind = serializers.CharField()
    qty = serializers.IntegerField()
    poles = serializers.IntegerField()
    rated_a = serializers.FloatField()
    vdc_v = serializers.FloatField()
    mm2 = serializers.IntegerField()
    placed = serializers.BooleanField()
    note = serializers.CharField()
    product = ProductSerializer(allow_null=True)
    price_total = serializers.CharField(allow_null=True)


class PvCheckSerializer(serializers.Serializer[None]):
    configured = serializers.BooleanField()
    ok = serializers.BooleanField()
    description = serializers.CharField()
    metrics = PvMetricsSerializer(allow_null=True)
    arrays = PvArrayResultSerializer(many=True)
    findings = PowerFindingSerializer(many=True)
    components = PvComponentSerializer(many=True)
    total_price = serializers.CharField()
