from django.db import models

from catalog.models import Product
from projects.models import ConsumerGroup, Panel


class DinRail(models.Model):
    panel = models.ForeignKey(Panel, on_delete=models.CASCADE, related_name="rails")
    row_index = models.PositiveSmallIntegerField()
    capacity_modules = models.PositiveSmallIntegerField("модулей на рейке")

    class Meta:
        ordering = ["panel_id", "row_index"]
        constraints = [
            models.UniqueConstraint(fields=["panel", "row_index"], name="uniq_rail_row_per_panel"),
            models.CheckConstraint(
                condition=models.Q(capacity_modules__gt=0), name="rail_capacity_gt_0"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.panel_id}/row{self.row_index}"


class Placement(models.Model):
    """A device on a DIN rail (rail + start_module) or on the mounting panel (x/y/w/h, mm)."""

    panel = models.ForeignKey(Panel, on_delete=models.CASCADE, related_name="placements")
    rail = models.ForeignKey(
        DinRail, on_delete=models.CASCADE, null=True, blank=True, related_name="placements"
    )
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="placements")
    group = models.ForeignKey(
        ConsumerGroup, on_delete=models.SET_NULL, null=True, blank=True, related_name="placements"
    )
    start_module = models.PositiveSmallIntegerField(null=True, blank=True)
    width_modules = models.PositiveSmallIntegerField(default=0)
    x_mm = models.PositiveIntegerField(null=True, blank=True)
    y_mm = models.PositiveIntegerField(null=True, blank=True)
    w_mm = models.PositiveIntegerField(null=True, blank=True)
    h_mm = models.PositiveIntegerField(null=True, blank=True)
    label = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["panel_id", "rail_id", "start_module", "id"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(rail__isnull=False, start_module__isnull=False)
                    | models.Q(
                        rail__isnull=True,
                        x_mm__isnull=False,
                        y_mm__isnull=False,
                        w_mm__isnull=False,
                        h_mm__isnull=False,
                    )
                ),
                name="placement_rail_or_panel_geometry",
            ),
        ]
        indexes = [models.Index(fields=["panel", "rail"], name="placement_panel_rail_idx")]

    def __str__(self) -> str:
        return f"{self.product} @ {self.panel_id}"


class LayoutVersion(models.Model):
    panel = models.ForeignKey(Panel, on_delete=models.CASCADE, related_name="versions")
    number = models.PositiveIntegerField()
    note = models.CharField(max_length=200, blank=True)
    snapshot = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["panel_id", "-number"]
        constraints = [
            models.UniqueConstraint(fields=["panel", "number"], name="uniq_layout_version_number")
        ]

    def __str__(self) -> str:
        return f"{self.panel_id} v{self.number}"
