from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from catalog.models import Product, Tier


class ProjectQuerySet(models.QuerySet["Project"]):
    def for_user(self, user: "settings.AUTH_USER_MODEL") -> "ProjectQuerySet":  # type: ignore[valid-type]
        """Object-level access: only the owner sees a project."""
        return self.filter(owner=user)


class ObjectType(models.TextChoices):
    FLAT = "flat", "Квартира"
    HOUSE = "house", "Дом"


class Grid(models.TextChoices):
    ONE_PHASE = "1ph", "1ф 230 В"
    THREE_PHASE = "3ph", "3ф 400 В"


class Earthing(models.TextChoices):
    TN_C_S = "TN-C-S", "TN-C-S"
    TN_S = "TN-S", "TN-S"
    TT = "TT", "TT"


class Project(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="projects"
    )
    name = models.CharField(max_length=160)
    object_type = models.CharField(
        max_length=8, choices=ObjectType.choices, default=ObjectType.FLAT
    )
    grid = models.CharField(max_length=3, choices=Grid.choices, default=Grid.ONE_PHASE)
    main_breaker_a = models.PositiveSmallIntegerField(
        "вводной автомат, А", default=32, validators=[MinValueValidator(6), MaxValueValidator(250)]
    )
    earthing = models.CharField(max_length=8, choices=Earthing.choices, default=Earthing.TN_C_S)
    price_tier = models.CharField(max_length=8, choices=Tier.choices, default=Tier.MIDDLE)
    tmin_c = models.SmallIntegerField("Tmin для PV, °C", default=-20)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProjectQuerySet.as_manager()

    class Meta:
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["owner", "-updated_at"], name="project_owner_idx")]

    def __str__(self) -> str:
        return self.name


class PanelKind(models.TextChoices):
    MAIN = "main", "ГРЩ"
    FLOOR = "floor", "Этажный"
    BACKUP = "backup", "Щит резерва / АВР"
    DC = "dc", "DC-бокс"


class Mounting(models.TextChoices):
    FLUSH = "flush", "Встраиваемый"
    SURFACE = "surface", "Навесной"


class Panel(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="panels")
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=8, choices=PanelKind.choices, default=PanelKind.MAIN)
    enclosure = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        limit_choices_to={"category__code": "enclosure"},
    )
    ip = models.PositiveSmallIntegerField("IP", default=40)
    mounting = models.CharField(max_length=8, choices=Mounting.choices, default=Mounting.FLUSH)
    # Manual node positions of the single-line diagram: {"s12": {"x": 10, "y": 20}, "bus": {...}}.
    diagram_positions = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["project_id", "id"]
        constraints = [
            models.UniqueConstraint(fields=["project", "name"], name="uniq_panel_name_per_project")
        ]

    def __str__(self) -> str:
        return f"{self.project.name}: {self.name}"


class PanelLink(models.Model):
    """Feeder link «щит → щит» (source panel feeds the target panel)."""

    source = models.ForeignKey(Panel, on_delete=models.CASCADE, related_name="outgoing_links")
    target = models.ForeignKey(Panel, on_delete=models.CASCADE, related_name="incoming_links")
    feeder_breaker_a = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["source", "target"], name="uniq_panel_link"),
            models.CheckConstraint(
                condition=~models.Q(source=models.F("target")), name="panel_link_not_self"
            ),
            # A panel has at most one feeder.
            models.UniqueConstraint(fields=["target"], name="panel_single_feeder"),
        ]

    def __str__(self) -> str:
        return f"{self.source_id} -> {self.target_id}"

    def save(self, *args: object, **kwargs: object) -> None:
        self.full_clean()
        super().save(*args, **kwargs)  # type: ignore[arg-type]

    def clean(self) -> None:
        if self.source_id and self.target_id:
            if self.source_id == self.target_id:
                raise ValidationError("Щит не может питать сам себя")
            if self.source.project_id != self.target.project_id:
                raise ValidationError("Щиты должны принадлежать одному проекту")
            # Cycle check: walk up from source; target must not be an ancestor.
            seen: set[int] = set()
            cur: int | None = self.source_id
            while cur is not None and cur not in seen:
                if cur == self.target_id:
                    raise ValidationError("Связь образует цикл")
                seen.add(cur)
                parent = PanelLink.objects.filter(target_id=cur).exclude(pk=self.pk).first()
                cur = parent.source_id if parent else None


class GroupType(models.TextChoices):
    LIGHTING = "lighting", "Освещение"
    SOCKETS = "sockets", "Розетки"
    KITCHEN = "kitchen", "Кухня"
    COOKER = "cooker", "Плита"
    BOILER = "boiler", "Бойлер"
    AC = "ac", "Кондиционер"
    FLOOR_HEATING = "floor_heating", "Тёплый пол"
    WASHER = "washer", "Стиральная машина"
    DISHWASHER = "dishwasher", "Посудомоечная машина"
    OTHER = "other", "Прочее"


class PhaseAssignment(models.TextChoices):
    AUTO = "auto", "Авто"
    L1 = "L1", "L1"
    L2 = "L2", "L2"
    L3 = "L3", "L3"
    THREE = "3ph", "3ф"


class ConsumerGroup(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="groups")
    panel = models.ForeignKey(
        Panel, on_delete=models.SET_NULL, null=True, blank=True, related_name="groups"
    )
    name = models.CharField(max_length=120)
    room = models.CharField(max_length=80, blank=True)
    type = models.CharField(max_length=16, choices=GroupType.choices, default=GroupType.SOCKETS)
    power_w = models.PositiveIntegerField("мощность, Вт", validators=[MinValueValidator(1)])
    cos_phi = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=1,
        validators=[MinValueValidator(Decimal("0.1")), MaxValueValidator(Decimal("1"))],
    )
    phase = models.CharField(
        max_length=4, choices=PhaseAssignment.choices, default=PhaseAssignment.AUTO
    )
    length_m = models.DecimalField("длина линии, м", max_digits=6, decimal_places=1, default=20)
    backed_up = models.BooleanField("резервируемая", default=False)
    wet_zone = models.BooleanField("влажная зона", default=False)

    # Results of auto-selection (filled by the calculations service in stage 2).
    assigned_phase = models.CharField(max_length=3, blank=True)
    breaker_a = models.PositiveSmallIntegerField(null=True, blank=True)
    curve = models.CharField(max_length=1, blank=True)
    cable_mm2 = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    rcd_ma = models.PositiveSmallIntegerField(null=True, blank=True)
    voltage_drop_pct = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["project_id", "id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(power_w__gt=0), name="group_power_gt_0"),
            models.CheckConstraint(
                condition=models.Q(cos_phi__gte=0.1, cos_phi__lte=1), name="group_cosphi_range"
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        if self.panel_id and self.panel.project_id != self.project_id:
            raise ValidationError("Щит группы должен принадлежать тому же проекту")
