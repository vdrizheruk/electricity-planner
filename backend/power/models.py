from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from catalog.models import Product
from projects.models import Project

from .services.models import SCENARIOS


class ScenarioChoice(models.TextChoices):
    GRID_GEN_ATS = "grid_gen_ats", "Сеть + генератор через АВР"
    GRID_INVERTER = "grid_inverter", "Сеть + инвертор"
    GRID_INVERTER_GEN = "grid_inverter_gen", "Сеть + инвертор + генератор"
    MANUAL = "manual_i0ii", "Ручной переключатель I-0-II"
    GRID3_GEN1_PHASE = "grid3_gen1_phase", "3ф сеть + 1ф генератор (одна фаза)"
    GRID3_GEN1_COMBINE = "grid3_gen1_combine", "3ф сеть + 1ф генератор (объединение фаз)"
    GRID1_GEN1 = "grid1_gen1", "1ф сеть + 1ф генератор"


assert {c.value for c in ScenarioChoice} == set(SCENARIOS)


class AtsKindChoice(models.TextChoices):
    NONE = "none", "Нет"
    CONTACTOR = "contactor", "На контакторах"
    MODULAR = "modular", "Модульный АВР"
    MANUAL = "manual", "Ручной I-0-II"


class InverterModeChoice(models.TextChoices):
    SINGLE = "single", "Один"
    PARALLEL = "parallel", "Параллельно"
    PHASE_SET = "phase_set", "Три фазы из трёх 1ф"


def _of(category: str) -> dict[str, str]:
    return {"category__code": category}


class PowerSystem(models.Model):
    """Backup-power configuration of a project (one per project)."""

    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name="power")
    scenario = models.CharField(
        max_length=24, choices=ScenarioChoice.choices, default=ScenarioChoice.GRID_GEN_ATS
    )
    generator = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        limit_choices_to=_of("generator"),
    )
    inverter = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        limit_choices_to=_of("inverter"),
    )
    inverter_count = models.PositiveSmallIntegerField(
        default=1, validators=[MinValueValidator(1), MaxValueValidator(9)]
    )
    inverter_mode = models.CharField(
        max_length=10, choices=InverterModeChoice.choices, default=InverterModeChoice.SINGLE
    )
    battery = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        limit_choices_to=_of("battery"),
    )
    battery_count = models.PositiveSmallIntegerField(
        default=1, validators=[MinValueValidator(1), MaxValueValidator(64)]
    )
    ats_kind = models.CharField(
        max_length=10, choices=AtsKindChoice.choices, default=AtsKindChoice.NONE
    )
    ats_poles = models.PositiveSmallIntegerField(
        default=2, validators=[MinValueValidator(1), MaxValueValidator(4)]
    )
    ats_rated_a = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(1000)])
    mechanical_interlock = models.BooleanField(default=False)
    electrical_interlock = models.BooleanField(default=False)
    backup_phase = models.CharField(
        max_length=2, choices=[("L1", "L1"), ("L2", "L2"), ("L3", "L3")], default="L1"
    )
    autonomy_target_h = models.FloatField(
        default=4.0, validators=[MinValueValidator(0.0), MaxValueValidator(240.0)]
    )

    def __str__(self) -> str:
        return f"{self.project.name}: {self.scenario}"


class RegionChoice(models.TextChoices):
    NORTH = "north", "Север"
    CENTER = "center", "Центр"
    SOUTH = "south", "Юг"


class PvSystem(models.Model):
    """Photovoltaic configuration of a project (one per project)."""

    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name="pv")
    module = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        limit_choices_to=_of("pv_module"),
    )
    inverter = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        limit_choices_to=_of("inverter"),
    )
    inverter_count = models.PositiveSmallIntegerField(
        default=1, validators=[MinValueValidator(1), MaxValueValidator(9)]
    )
    t_min_c = models.FloatField(
        default=-20.0, validators=[MinValueValidator(-50.0), MaxValueValidator(10.0)]
    )
    t_cell_max_c = models.FloatField(
        default=70.0, validators=[MinValueValidator(40.0), MaxValueValidator(95.0)]
    )
    region = models.CharField(
        max_length=8, choices=RegionChoice.choices, default=RegionChoice.CENTER
    )
    performance_ratio = models.FloatField(
        default=0.8, validators=[MinValueValidator(0.5), MaxValueValidator(0.95)]
    )
    export_limit_w = models.PositiveIntegerField(
        default=0, validators=[MaxValueValidator(1_000_000)]
    )
    green_tariff = models.BooleanField(default=False)

    def __str__(self) -> str:
        return f"{self.project.name}: PV"


class PvArray(models.Model):
    """Identical strings feeding one MPPT input of the inverter."""

    pv = models.ForeignKey(PvSystem, on_delete=models.CASCADE, related_name="arrays")
    mppt = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(36)]
    )
    series = models.PositiveSmallIntegerField(
        default=10, validators=[MinValueValidator(1), MaxValueValidator(40)]
    )
    strings = models.PositiveSmallIntegerField(
        default=1, validators=[MinValueValidator(1), MaxValueValidator(20)]
    )
    azimuth_deg = models.FloatField(
        default=0.0, validators=[MinValueValidator(-180.0), MaxValueValidator(180.0)]
    )
    tilt_deg = models.FloatField(
        default=35.0, validators=[MinValueValidator(0.0), MaxValueValidator(90.0)]
    )
    cable_m = models.FloatField(
        default=20.0, validators=[MinValueValidator(1.0), MaxValueValidator(500.0)]
    )

    class Meta:
        ordering = ["mppt", "id"]
        constraints = [models.UniqueConstraint(fields=["pv", "mppt"], name="uniq_pv_mppt")]

    def __str__(self) -> str:
        return f"MPPT {self.mppt}: {self.strings}x{self.series}"
