"""Photovoltaic part: string sizing against the inverter MPPT, DC protection, cables, yield.

Pure functions, no Django. Rules follow IEC 60364-7-712 / IEC 62548 in a simplified form:

* open-circuit voltage is taken at the lowest ambient temperature (default −20 °C);
* maximum-power voltage must stay inside the MPPT window;
* gPV fuses are required when more than two strings share an input;
* DC isolator and DC SPD voltage ratings must cover the cold open-circuit voltage;
* string cable is sized by current (with derating) and by DC voltage drop (target 1 %, limit 2 %).
"""

import math
from dataclasses import dataclass, replace
from typing import Literal

from .models import Finding, Grid

Region = Literal["north", "center", "south"]

# Annual yield of an optimally oriented 1 kWp system at PR 0.8, kWh/kWp (indicative).
REGION_YIELD: dict[str, float] = {"north": 950.0, "center": 1050.0, "south": 1200.0}
BASE_PR = 0.8
OPTIMAL_TILT_DEG = 35.0

DC_AC_WARN = 1.3
DC_AC_LOW = 0.8
DROP_TARGET_PCT = 1.0
DROP_LIMIT_PCT = 2.0
RHO_CU = 0.0225  # Ohm*mm2/m, copper at ~70 degC
FUSE_FACTOR = 1.5  # fuse rating >= 1.5 x Isc (IEC 62548)
ISOLATOR_FACTOR = 1.25  # isolator rating >= 1.25 x Isc
CABLE_FACTOR = 1.25  # continuous current factor for the cable
GREEN_TARIFF_MAX_KW = 50.0

FUSE_SERIES = (10.0, 12.0, 15.0, 16.0, 20.0, 25.0, 30.0)
BREAKER_SERIES = (6.0, 10.0, 16.0, 20.0, 25.0, 32.0, 40.0, 50.0, 63.0, 80.0, 100.0)
# Current-carrying capacity of PV1-F, mm2 -> A, already derated for roof ambient and grouping.
CABLE_AMPACITY: dict[int, float] = {4: 36.0, 6: 46.0, 10: 63.0}
CABLE_SECTIONS = tuple(sorted(CABLE_AMPACITY))


@dataclass(frozen=True)
class PvModuleSpec:
    pmax_w: float
    voc_v: float
    isc_a: float
    vmp_v: float
    imp_a: float
    beta_voc_pct_per_c: float = -0.25
    beta_vmp_pct_per_c: float = -0.30
    max_series_fuse_a: float = 25.0


@dataclass(frozen=True)
class PvInverterSpec:
    kind: str = "hybrid"
    phases: int = 1
    p_ac_w: float = 5000.0
    count: int = 1
    mppt_count: int = 0
    mppt_min_v: float = 0.0
    mppt_max_v: float = 0.0
    vmax_v: float = 0.0  # absolute maximum input voltage; 0: use the MPPT maximum
    imax_per_mppt_a: float = 0.0
    isc_max_per_mppt_a: float = 0.0  # 0: use imax_per_mppt_a
    pv_max_w: float = 0.0  # 0: unknown
    transformerless: bool = True


@dataclass(frozen=True)
class PvArray:
    """Strings connected to one MPPT input: ``strings`` identical strings of ``series`` modules."""

    mppt: int  # 1-based over all inverters
    series: int
    strings: int = 1
    azimuth_deg: float = 0.0  # 0 south, +90 west, -90 east
    tilt_deg: float = 35.0
    cable_m: float = 20.0  # one-way length from the string to the DC box


@dataclass(frozen=True)
class PvInput:
    grid: Grid
    earthing: str
    module: PvModuleSpec
    inverter: PvInverterSpec
    arrays: tuple[PvArray, ...] = ()
    t_min_c: float = -20.0
    t_cell_max_c: float = 70.0
    region: str = "center"
    performance_ratio: float = BASE_PR
    export_limit_w: float = 0.0  # 0: no limit configured
    green_tariff: bool = False


@dataclass(frozen=True)
class PvComponent:
    """A device or material of the PV system; the Django layer maps it to a catalog product."""

    role: str
    kind: str  # catalog family
    qty: int = 1
    poles: int = 0
    rated_a: float = 0.0
    vdc_v: float = 0.0  # minimum DC voltage rating
    mm2: int = 0
    placed: bool = False  # goes into the DC box panel
    note: str = ""


@dataclass(frozen=True)
class ArrayResult:
    mppt: int
    modules: int
    kwp: float
    voc_cold_v: float
    vmp_stc_v: float
    vmp_hot_v: float
    vmp_cold_v: float
    isc_a: float
    imp_a: float
    fuse_a: float | None
    cable_mm2: int
    drop_pct: float
    yield_kwh: float


@dataclass(frozen=True)
class PvMetrics:
    modules: int
    kwp: float
    p_ac_w: float
    dc_ac_ratio: float
    clip_loss_pct: float
    yield_kwh_year: float
    specific_yield: float  # kWh/kWp/year
    ac_breaker_a: float


@dataclass(frozen=True)
class PvResult:
    ok: bool
    metrics: PvMetrics
    arrays: tuple[ArrayResult, ...]
    findings: tuple[Finding, ...]
    components: tuple[PvComponent, ...]
    description: str = ""


# --------------------------------------------------------------------- formulas
def temp_factor(beta_pct_per_c: float, t_c: float) -> float:
    """Relative change of a voltage against its 25 °C value (STC)."""
    return 1.0 + beta_pct_per_c / 100.0 * (t_c - 25.0)


def string_voltages(m: PvModuleSpec, series: int, t_min: float, t_max: float) -> tuple[float, ...]:
    """(Voc cold, Vmp STC, Vmp hot, Vmp cold) of one string, V."""
    return (
        m.voc_v * series * temp_factor(m.beta_voc_pct_per_c, t_min),
        m.vmp_v * series,
        m.vmp_v * series * temp_factor(m.beta_vmp_pct_per_c, t_max),
        m.vmp_v * series * temp_factor(m.beta_vmp_pct_per_c, t_min),
    )


def pick_standard(value: float, series: tuple[float, ...]) -> float | None:
    for s in series:
        if s >= value - 1e-9:
            return s
    return None


def tilt_factor(tilt_deg: float) -> float:
    return max(1.0 - 0.00009 * (tilt_deg - OPTIMAL_TILT_DEG) ** 2, 0.3)


def azimuth_factor(azimuth_deg: float) -> float:
    az = min(abs(azimuth_deg), 180.0)
    if az <= 90.0:
        return 1.0 - 0.15 * (az / 90.0) ** 2
    return 0.85 - 0.30 * (az - 90.0) / 90.0


def orientation_factor(azimuth_deg: float, tilt_deg: float) -> float:
    return max(azimuth_factor(azimuth_deg) * tilt_factor(tilt_deg), 0.2)


def clipping_loss_pct(dc_ac: float) -> float:
    """Share of energy cut by the inverter limit (rough estimate: 0 up to DC/AC 1.0)."""
    return 0.0 if dc_ac <= 1.0 else min(0.25 * (dc_ac - 1.0) ** 2 * 100.0, 25.0)


def voltage_drop_pct(length_m: float, current_a: float, mm2: int, v_string: float) -> float:
    """DC drop of a two-wire line, % of the string voltage."""
    if v_string <= 0:
        return 0.0
    return 2.0 * length_m * RHO_CU * current_a / (mm2 * v_string) * 100.0


def pick_cable(
    length_m: float, i_string_a: float, i_design_a: float, v_string: float
) -> tuple[int, float, str]:
    """Smallest PV cable by ampacity and drop: (mm2, drop %, verdict ok|warning|error|ampacity)."""
    ok_amp = [s for s in CABLE_SECTIONS if CABLE_AMPACITY[s] >= i_design_a]
    if not ok_amp:
        s = CABLE_SECTIONS[-1]
        return s, voltage_drop_pct(length_m, i_string_a, s, v_string), "ampacity"
    for limit, verdict in ((DROP_TARGET_PCT, "ok"), (DROP_LIMIT_PCT, "warning")):
        for s in ok_amp:
            d = voltage_drop_pct(length_m, i_string_a, s, v_string)
            if d <= limit:
                return s, d, verdict
    s = ok_amp[-1]
    return s, voltage_drop_pct(length_m, i_string_a, s, v_string), "error"


def ac_current_a(inv: PvInverterSpec) -> float:
    """Rated output current of ONE inverter."""
    if inv.phases == 3:
        return inv.p_ac_w / (math.sqrt(3) * 400.0)
    return inv.p_ac_w / 230.0


# ---------------------------------------------------------------------- analysis
def analyze_pv(inp: PvInput) -> PvResult:
    m, inv = inp.module, inp.inverter
    fs: list[Finding] = []
    comps: list[PvComponent] = []
    results: list[ArrayResult] = []
    valid: list[PvArray] = []
    p_ac = inv.p_ac_w * inv.count
    inputs = inv.mppt_count * inv.count
    vmax = inv.vmax_v or inv.mppt_max_v
    isc_limit = inv.isc_max_per_mppt_a or inv.imax_per_mppt_a

    if inv.kind == "off-grid" or inv.mppt_count <= 0:
        fs.append(
            Finding(
                "error",
                "NO_MPPT",
                "У выбранного инвертора нет MPPT-входов для PV: нужен гибридный или сетевой",
            )
        )
    if not inp.arrays:
        fs.append(Finding("error", "NO_ARRAYS", "Не задано ни одной группы строк PV"))

    used: set[int] = set()
    for a in inp.arrays:
        tag = f"MPPT {a.mppt}"
        if a.series < 1 or a.strings < 1:
            fs.append(Finding("error", "ARRAY_INVALID", f"{tag}: число модулей и строк ≥ 1"))
            continue
        if not 1 <= a.mppt <= max(inputs, 0):
            fs.append(
                Finding("error", "MPPT_RANGE", f"{tag}: у инвертора только {inputs} вход(ов)")
            )
        if a.mppt in used:
            fs.append(Finding("error", "MPPT_DUP", f"{tag}: вход указан дважды"))
        used.add(a.mppt)

        voc_cold, vmp_stc, vmp_hot, vmp_cold = string_voltages(
            m, a.series, inp.t_min_c, inp.t_cell_max_c
        )
        isc = m.isc_a * a.strings
        imp = m.imp_a * a.strings
        if vmax > 0 and voc_cold > vmax:
            fs.append(
                Finding(
                    "error",
                    "VOC_COLD",
                    f"{tag}: Voc при {inp.t_min_c:g} °C = {voc_cold:.0f} В превышает "
                    f"максимум входа {vmax:g} В: уменьшите число модулей в строке",
                )
            )
        if inv.mppt_min_v and vmp_stc < inv.mppt_min_v:
            fs.append(
                Finding(
                    "error",
                    "VMP_LOW",
                    f"{tag}: Vmp = {vmp_stc:.0f} В ниже минимума MPPT {inv.mppt_min_v:g} В: "
                    "добавьте модули в строку",
                )
            )
        elif inv.mppt_max_v and vmp_stc > inv.mppt_max_v:
            fs.append(
                Finding(
                    "error",
                    "VMP_HIGH",
                    f"{tag}: Vmp = {vmp_stc:.0f} В выше максимума MPPT {inv.mppt_max_v:g} В",
                )
            )
        else:
            if inv.mppt_min_v and vmp_hot < inv.mppt_min_v:
                fs.append(
                    Finding(
                        "warning",
                        "VMP_HOT_LOW",
                        f"{tag}: при нагреве до {inp.t_cell_max_c:g} °C Vmp = {vmp_hot:.0f} В "
                        f"ниже окна MPPT ({inv.mppt_min_v:g} В): потери в жару",
                    )
                )
            if inv.mppt_max_v and vmp_cold > inv.mppt_max_v:
                fs.append(
                    Finding(
                        "warning",
                        "VMP_COLD_HIGH",
                        f"{tag}: на морозе Vmp = {vmp_cold:.0f} В выше окна MPPT "
                        f"({inv.mppt_max_v:g} В): ограничение мощности",
                    )
                )
        if isc_limit and isc > isc_limit:
            fs.append(
                Finding(
                    "error",
                    "ISC_HIGH",
                    f"{tag}: Isc = {isc:.1f} А превышает допустимый ток входа {isc_limit:g} А: "
                    "уменьшите число параллельных строк",
                )
            )
        if inv.imax_per_mppt_a and imp > inv.imax_per_mppt_a and isc <= (isc_limit or isc):
            fs.append(
                Finding(
                    "warning",
                    "IMP_HIGH",
                    f"{tag}: Imp = {imp:.1f} А выше рабочего тока входа {inv.imax_per_mppt_a:g} А: "
                    "мощность будет ограничена",
                )
            )

        fuse: float | None = None
        if a.strings > 2:
            fuse = pick_standard(FUSE_FACTOR * m.isc_a, FUSE_SERIES)
            if fuse is None or fuse > m.max_series_fuse_a:
                fs.append(
                    Finding(
                        "error",
                        "FUSE_RANGE",
                        f"{tag}: нет предохранителя между 1,5·Isc и допустимым током модуля "
                        f"{m.max_series_fuse_a:g} А",
                    )
                )
                fuse = fuse or FUSE_SERIES[-1]
            else:
                comps.append(
                    PvComponent(
                        "dc_fuse",
                        "dc_fuse",
                        qty=2 * a.strings,
                        rated_a=fuse,
                        vdc_v=math.ceil(voc_cold),
                        placed=True,
                        note=f"{tag}: gPV на каждую строку, оба полюса",
                    )
                )

        mm2, drop, verdict = pick_cable(
            a.cable_m, m.imp_a, CABLE_FACTOR * m.isc_a, vmp_stc if vmp_stc else 1.0
        )
        if verdict == "ampacity":
            fs.append(
                Finding(
                    "error",
                    "CABLE_AMPACITY",
                    f"{tag}: ток строки {CABLE_FACTOR * m.isc_a:.1f} А выше допустимого "
                    f"для PV-кабеля {CABLE_SECTIONS[-1]} мм²",
                )
            )
        elif verdict == "error":
            fs.append(
                Finding(
                    "error",
                    "CABLE_DROP",
                    f"{tag}: падение {drop:.1f}% на {a.cable_m:g} м даже на {mm2} мм² "
                    f"(предел {DROP_LIMIT_PCT:g}%): сократите длину или увеличьте число модулей",
                )
            )
        elif verdict == "warning":
            fs.append(
                Finding(
                    "warning",
                    "CABLE_DROP",
                    f"{tag}: падение {drop:.1f}% на {mm2} мм² (цель ≤ {DROP_TARGET_PCT:g}%)",
                )
            )
        comps.append(
            PvComponent(
                "pv_cable",
                "cable",
                qty=max(math.ceil(2 * a.cable_m * a.strings), 1),
                mm2=mm2,
                note=f"{tag}: PV1-F {mm2} мм², м ({a.strings} стр. × 2 жилы × {a.cable_m:g} м)",
            )
        )
        comps.append(
            PvComponent(
                "dc_isolator",
                "dc_isolator",
                rated_a=ISOLATOR_FACTOR * isc,
                vdc_v=math.ceil(voc_cold),
                placed=True,
                note=f"{tag}: разъединитель обоих полюсов",
            )
        )
        comps.append(
            PvComponent(
                "dc_spd",
                "dc_spd",
                vdc_v=math.ceil(voc_cold),
                placed=True,
                note=f"{tag}: УЗИП тип 2, Ucpv ≥ Voc max",
            )
        )
        comps.append(
            PvComponent(
                "mc4",
                "pv_connector",
                qty=2 * a.strings,
                note=f"{tag}: пары MC4 для стыковки строк",
            )
        )
        if a.cable_m > 10:
            fs.append(
                Finding(
                    "info",
                    "SPD_BOTH_ENDS",
                    f"{tag}: линия {a.cable_m:g} м > 10 м: УЗИП ставят и у панелей, и у инвертора",
                )
            )

        kwp = m.pmax_w * a.series * a.strings / 1000.0
        valid.append(a)
        results.append(
            ArrayResult(
                mppt=a.mppt,
                modules=a.series * a.strings,
                kwp=kwp,
                voc_cold_v=voc_cold,
                vmp_stc_v=vmp_stc,
                vmp_hot_v=vmp_hot,
                vmp_cold_v=vmp_cold,
                isc_a=isc,
                imp_a=imp,
                fuse_a=fuse,
                cable_mm2=mm2,
                drop_pct=drop,
                yield_kwh=0.0,
            )
        )

    free = sorted(set(range(1, inputs + 1)) - used)
    if free and inp.arrays:
        fs.append(
            Finding("info", "MPPT_UNUSED", "Свободные MPPT-входы: " + ", ".join(map(str, free)))
        )

    modules = sum(r.modules for r in results)
    kwp = sum(r.kwp for r in results)
    ratio = kwp * 1000.0 / p_ac if p_ac > 0 else 0.0
    if ratio > DC_AC_WARN:
        fs.append(
            Finding(
                "warning",
                "DC_AC_HIGH",
                f"DC/AC = {ratio:.2f} > {DC_AC_WARN:g}: избыточная мощность панелей будет срезана",
            )
        )
    elif 0 < ratio < DC_AC_LOW:
        fs.append(
            Finding(
                "info", "DC_AC_LOW", f"DC/AC = {ratio:.2f} < {DC_AC_LOW:g}: инвертор недогружен"
            )
        )
    if inv.pv_max_w and kwp * 1000.0 > inv.pv_max_w * inv.count:
        fs.append(
            Finding(
                "warning",
                "PV_MAX_W",
                f"Мощность панелей {kwp * 1000:.0f} Вт выше максимума входа инвертора "
                f"{inv.pv_max_w * inv.count:.0f} Вт",
            )
        )

    clip = clipping_loss_pct(ratio)
    base = REGION_YIELD.get(inp.region, REGION_YIELD["center"])
    pr_k = inp.performance_ratio / BASE_PR
    ay: list[ArrayResult] = []
    for r, a in zip(results, valid, strict=True):
        y = r.kwp * base * orientation_factor(a.azimuth_deg, a.tilt_deg) * pr_k * (1 - clip / 100)
        ay.append(replace(r, yield_kwh=y))
    total_yield = sum(r.yield_kwh for r in ay)

    # ---- AC side and the rest of the bill
    i_ac = ac_current_a(inv)
    ac_breaker = pick_standard(1.25 * i_ac, BREAKER_SERIES) or BREAKER_SERIES[-1]
    poles = 4 if inv.phases == 3 else 2
    if inv.mppt_count > 0:
        comps.append(
            PvComponent(
                "ac_breaker",
                "mcb",
                qty=inv.count,
                poles=poles,
                rated_a=ac_breaker,
                placed=True,
                note="Автомат на выходе инвертора (≥ 1,25·Iном)",
            )
        )
        comps.append(
            PvComponent(
                "ac_spd",
                "spd",
                poles=poles,
                placed=True,
                note="AC-УЗИП тип 2 на выходе инвертора",
            )
        )
    if inp.green_tariff or inp.export_limit_w > 0:
        comps.append(
            PvComponent(
                "meter",
                "meter",
                poles=4 if inv.phases == 3 else 2,
                placed=True,
                note="Двунаправленный счётчик (генерация/потребление)",
            )
        )
    if inp.green_tariff and kwp > GREEN_TARIFF_MAX_KW:
        fs.append(
            Finding(
                "warning",
                "GREEN_TARIFF_LIMIT",
                f"«Зелёный» тариф для домохозяйств — до {GREEN_TARIFF_MAX_KW:g} кВт, "
                f"заданo {kwp:.1f} кВт",
            )
        )
    if inp.export_limit_w > 0:
        if inp.export_limit_w >= p_ac:
            fs.append(
                Finding(
                    "info",
                    "EXPORT_LIMIT_MOOT",
                    "Лимит экспорта не меньше мощности инвертора: ограничение не сработает",
                )
            )
        else:
            fs.append(
                Finding(
                    "info",
                    "EXPORT_LIMIT",
                    f"Ограничение отдачи в сеть {inp.export_limit_w:g} Вт настраивается "
                    "в инверторе (датчик/счётчик на вводе)",
                )
            )
    if inv.transformerless:
        fs.append(
            Finding(
                "info",
                "RCD_TYPE_B",
                "Бестрансформаторный инвертор: УЗО выше по цепи — тип B, если инвертор "
                "не имеет контроля тока утечки с постоянной составляющей (712.411.3.2.1.2)",
            )
        )
    if inp.earthing == "TT":
        fs.append(
            Finding("warning", "TT_EARTH", "TT: проверьте сопротивление заземлителя и УЗО на вводе")
        )
    fs.append(
        Finding(
            "info",
            "PV_BONDING",
            "Каркас панелей и конструкцию соедините с PE медью не менее 6 мм² (IEC 62548)",
        )
    )
    fs.append(
        Finding(
            "info",
            "BATTERY_ELSEWHERE",
            "АКБ и её DC-защита рассчитываются на странице резервного питания",
        )
    )

    if modules:
        comps.append(PvComponent("pv_module", "pv_module", qty=modules, note="Солнечные панели"))
    if inv.mppt_count > 0:
        comps.append(PvComponent("inverter", "inverter", qty=inv.count, note="Инвертор"))

    ok = not any(f.level == "error" for f in fs)
    return PvResult(
        ok=ok,
        metrics=PvMetrics(
            modules=modules,
            kwp=kwp,
            p_ac_w=p_ac,
            dc_ac_ratio=ratio,
            clip_loss_pct=clip,
            yield_kwh_year=total_yield,
            specific_yield=total_yield / kwp if kwp > 0 else 0.0,
            ac_breaker_a=ac_breaker,
        ),
        arrays=tuple(ay),
        findings=tuple(fs),
        components=_merge(comps),
        description=(
            f"{modules} модулей, {kwp:.2f} кВт пик, DC/AC {ratio:.2f}, "
            f"≈ {total_yield:.0f} кВт·ч/год"
        ),
    )


def _merge(comps: list[PvComponent]) -> tuple[PvComponent, ...]:
    """Merge identical cable lines (same section) and keep the rest in order."""
    out: list[PvComponent] = []
    for c in comps:
        if c.kind == "cable":
            hit = next((i for i, o in enumerate(out) if o.kind == "cable" and o.mm2 == c.mm2), None)
            if hit is not None:
                o = out[hit]
                out[hit] = PvComponent(
                    o.role,
                    o.kind,
                    o.qty + c.qty,
                    o.poles,
                    o.rated_a,
                    o.vdc_v,
                    o.mm2,
                    o.placed,
                    f"PV1-F {c.mm2} мм², м",
                )
                continue
        out.append(c)
    return tuple(out)
