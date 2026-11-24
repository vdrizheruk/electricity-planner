from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Tier(models.TextChoices):
    ECONOMY = "eco", "Эконом"
    MIDDLE = "mid", "Средний"
    PREMIUM = "premium", "Премиум"


class CategoryCode(models.TextChoices):
    """Product type. Business logic (autoselect, BOM, validation) keys off these codes."""

    MCB = "mcb", "Автоматический выключатель"
    RCD = "rcd", "УЗО"
    RCBO = "rcbo", "Дифавтомат"
    SPD = "spd", "УЗИП (AC)"
    MAIN_SWITCH = "main_switch", "Вводной выключатель-разъединитель"
    VOLTAGE_RELAY = "voltage_relay", "Реле напряжения"
    PHASE_RELAY = "phase_relay", "Реле контроля фаз"
    METER = "meter", "Счётчик"
    CONTACTOR = "contactor", "Контактор"
    TIMER = "timer", "Таймер"
    ATS = "ats", "АВР / переключатель"
    BUSBAR = "busbar", "Шина N/PE / гребёнка"
    DIN_RAIL = "din_rail", "DIN-рейка"
    BLANK = "blank", "Заглушка"
    LABEL = "label", "Маркировка"
    TERMINAL = "terminal", "Клеммник"
    ENCLOSURE = "enclosure", "Корпус щита"
    MOUNT_PANEL = "mount_panel", "Монтажная панель"
    INVERTER = "inverter", "Инвертор / ИБП"
    BATTERY = "battery", "АКБ"
    PV_MODULE = "pv_module", "Солнечная панель"
    DC_FUSE = "dc_fuse", "DC-предохранитель (gPV)"
    DC_ISOLATOR = "dc_isolator", "DC-разъединитель"
    DC_SPD = "dc_spd", "DC-УЗИП"
    DC_BREAKER = "dc_breaker", "DC-автомат"
    PV_CONNECTOR = "pv_connector", "Разъём MC4"
    CABLE = "cable", "Кабель"
    GENERATOR = "generator", "Генератор"


class RcdType(models.TextChoices):
    AC = "AC", "AC"
    A = "A", "A"
    F = "F", "F"
    B = "B", "B"


class Curve(models.TextChoices):
    B = "B", "B"
    C = "C", "C"
    D = "D", "D"


class Brand(models.Model):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=80, unique=True)
    tier = models.CharField(max_length=8, choices=Tier.choices, default=Tier.MIDDLE)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Category(models.Model):
    code = models.CharField(max_length=24, choices=CategoryCode.choices, unique=True)
    name_ru = models.CharField(max_length=120)
    name_uk = models.CharField(max_length=120)
    sort_order = models.PositiveSmallIntegerField(default=100)

    class Meta:
        ordering = ["sort_order", "code"]
        verbose_name_plural = "categories"

    def __str__(self) -> str:
        return self.name_ru


class Product(models.Model):
    brand = models.ForeignKey(Brand, on_delete=models.PROTECT, related_name="products")
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    sku = models.CharField("артикул", max_length=64)
    name = models.CharField(max_length=255)
    series = models.CharField(max_length=64, blank=True)
    tier = models.CharField(max_length=8, choices=Tier.choices, default=Tier.MIDDLE)

    rated_a = models.DecimalField(
        "номинал, А",
        max_digits=7,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    poles = models.PositiveSmallIntegerField(
        "полюса",
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(4)],
    )
    curve = models.CharField("характеристика", max_length=1, choices=Curve.choices, blank=True)
    leakage_ma = models.PositiveIntegerField("ток утечки, мА", null=True, blank=True)
    rcd_type = models.CharField("тип УЗО", max_length=2, choices=RcdType.choices, blank=True)

    modules = models.DecimalField(
        "модулей (17.5 мм)",
        max_digits=5,
        decimal_places=1,
        default=0,
        validators=[MinValueValidator(0)],
    )
    width_mm = models.PositiveIntegerField(null=True, blank=True)
    height_mm = models.PositiveIntegerField(null=True, blank=True)
    depth_mm = models.PositiveIntegerField(null=True, blank=True)
    din_mountable = models.BooleanField(
        "на DIN-рейку",
        default=True,
        help_text="False — монтируется на монтажную панель (контакторные АВР, клеммники и т.п.).",
    )

    electrical = models.JSONField("электрические параметры", default=dict, blank=True)

    price = models.DecimalField(
        "цена, UAH с НДС", max_digits=12, decimal_places=2, validators=[MinValueValidator(0)]
    )
    price_date = models.DateField("дата цены")
    needs_verification = models.BooleanField(
        default=True, help_text="Артикул/цена ориентировочные, требуют проверки."
    )

    class Meta:
        ordering = ["category__sort_order", "brand__name", "sku"]
        constraints = [
            models.UniqueConstraint(fields=["brand", "sku"], name="uniq_product_brand_sku"),
            models.CheckConstraint(condition=models.Q(price__gte=0), name="product_price_gte_0"),
            models.CheckConstraint(
                condition=models.Q(poles__isnull=True) | models.Q(poles__gte=1, poles__lte=4),
                name="product_poles_1_4",
            ),
        ]
        indexes = [
            models.Index(fields=["category", "rated_a", "poles"], name="product_filter_idx"),
            models.Index(fields=["tier"], name="product_tier_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.brand.name} {self.sku}"
