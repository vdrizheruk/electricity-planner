"""Source checks: generator, inverter, battery."""

from calculations.constants import EPS, IMBALANCE_LIMIT_PCT, SQRT3, VOLTAGE_1PH, VOLTAGE_3PH
from calculations.phases import imbalance_pct

from .loads import PHASES, backed_up
from .models import (
    BatterySpec,
    Finding,
    GeneratorSpec,
    InverterSpec,
    LoadInput,
    Metrics,
    PowerInput,
)

# A generator may be loaded up to this multiple of its rating for the few seconds of a start.
GEN_SURGE_FACTOR = 1.5
# Inverter efficiency and battery round-trip factor used for autonomy and DC current.
INVERTER_EFF = 0.9
DOD_DEFAULT = {"LiFePO4": 0.9, "AGM": 0.5}
DC_CURRENT_MARGIN = 1.0


def _on_phases(loads: list[LoadInput], grid: str) -> set[str]:
    out: set[str] = set()
    for x in loads:
        if grid == "1ph":
            out.add("L1")
        elif x.phase == "3ph":
            out.update(PHASES)
        else:
            out.add(x.phase if x.phase in PHASES else "L1")
    return out


def check_generator(
    inp: PowerInput, gen: GeneratorSpec, m: Metrics, fs: list[Finding]
) -> tuple[float, float]:
    """Returns (required kVA, required kW) and appends findings."""
    loads = backed_up(inp.loads)
    sc = inp.scenario
    one_phase_sc = sc in ("grid3_gen1_phase", "grid3_gen1_combine")
    if one_phase_sc:
        if gen.phases != 1:
            fs.append(
                Finding("error", "GEN_PHASE_MISMATCH", "Для этого сценария нужен 1ф генератор")
            )
        if inp.grid != "3ph":
            fs.append(Finding("error", "GRID_PHASE_MISMATCH", "Сценарий требует 3ф сеть"))
    elif gen.phases != (3 if inp.grid == "3ph" else 1):
        fs.append(
            Finding(
                "error",
                "GEN_PHASE_MISMATCH",
                f"Генератор {gen.phases}ф не соответствует сети {inp.grid}",
            )
        )

    req_kva = m.s_backup_va / 1000
    req_kw = m.p_backup_w / 1000
    if sc == "grid3_gen1_phase":
        on = _on_phases(loads, inp.grid)
        if on - {inp.backup_phase}:
            ids = ", ".join(str(x.id) for x in loads if x.phase != inp.backup_phase)
            fs.append(
                Finding(
                    "error",
                    "BACKUP_LOADS_NOT_ON_ONE_PHASE",
                    "Резервируемые группы должны быть на одной фазе "
                    f"{inp.backup_phase} (группы: {ids}); перенесите их или объедините фазы",
                )
            )
    if sc == "grid3_gen1_combine":
        if any(x.phase == "3ph" for x in loads):
            fs.append(
                Finding(
                    "error",
                    "THREE_PHASE_LOAD_ON_1PH_GEN",
                    "3ф нагрузку нельзя питать от 1ф генератора при объединении фаз",
                )
            )
        fs.append(
            Finding(
                "info",
                "COMBINED_PHASES",
                "Фазы объединяются на резервной шине только контактором с блокировкой; "
                "суммарная нагрузка ложится на одну фазу генератора",
            )
        )

    if gen.kw > gen.kva + 1e-9:
        fs.append(
            Finding("warning", "GEN_KW_GT_KVA", "kW генератора больше kVA — проверьте данные")
        )
    if req_kva > gen.kva + 1e-9:
        fs.append(
            Finding(
                "error",
                "GEN_UNDERSIZED",
                f"Мощность генератора {gen.kva:.1f} кВА меньше нагрузки {req_kva:.1f} кВА",
            )
        )
    if req_kw > gen.kw + 1e-9:
        fs.append(
            Finding(
                "error",
                "GEN_KW_UNDERSIZED",
                f"Активная мощность генератора {gen.kw:.1f} кВт меньше нагрузки {req_kw:.1f} кВт",
            )
        )
    if m.s_start_va / 1000 > gen.kva * GEN_SURGE_FACTOR + 1e-9:
        fs.append(
            Finding(
                "error",
                "GEN_SURGE",
                f"Пусковая мощность {m.s_start_va / 1000:.1f} кВА выше допустимой "
                f"перегрузки генератора ({gen.kva * GEN_SURGE_FACTOR:.1f} кВА)",
            )
        )
    if gen.phases == 3 and not one_phase_sc:
        per_phase_limit = gen.kva * 1000 / 3
        worst = max(m.phase_va.values(), default=0.0)
        if worst > per_phase_limit + 1e-9:
            fs.append(
                Finding(
                    "error",
                    "GEN_PHASE_OVERLOAD",
                    f"Нагрузка фазы {worst / 1000:.1f} кВА выше 1/3 мощности генератора "
                    f"({per_phase_limit / 1000:.1f} кВА)",
                )
            )
        if m.imbalance_pct > IMBALANCE_LIMIT_PCT + EPS:
            fs.append(
                Finding(
                    "warning",
                    "GEN_PHASE_IMBALANCE",
                    f"Перекос фаз резервной нагрузки {m.imbalance_pct:.0f}% "
                    f"(> {IMBALANCE_LIMIT_PCT:.0f}%)",
                )
            )
    return req_kva, req_kw


def inverter_capacity(inv: InverterSpec) -> float:
    """Total AC power the inverter group can deliver, W."""
    return inv.p_ac_w * max(inv.count, 1)


def check_inverter(
    inp: PowerInput, inv: InverterSpec, m: Metrics, fs: list[Finding]
) -> tuple[float, float]:
    """Returns (capacity W, required W)."""
    cap = inverter_capacity(inv)
    surge_one = inv.p_surge_w if inv.p_surge_w > 0 else inv.p_ac_w * 1.5
    surge = surge_one * max(inv.count, 1)

    if inv.kind == "on-grid":
        fs.append(
            Finding(
                "error",
                "INVERTER_NOT_BACKUP",
                "Сетевой (on-grid) инвертор отключается при пропадании сети "
                "и не может питать резерв — нужен гибридный или off-grid",
            )
        )
    if inv.mode == "phase_set" and not (inv.phases == 1 and inv.count == 3):
        fs.append(
            Finding(
                "error",
                "PHASE_SET_INVALID",
                "Трёхфазный комплект собирается из трёх однофазных инверторов",
            )
        )
    three_phase_out = inv.phases == 3 or inv.mode == "phase_set"
    loads = backed_up(inp.loads)
    required = m.p_backup_w

    if inp.grid == "3ph" and not three_phase_out:
        on = _on_phases(loads, inp.grid)
        if len(on) > 1 or any(x.phase == "3ph" for x in loads):
            fs.append(
                Finding(
                    "error",
                    "INVERTER_PHASE_MISMATCH",
                    "Однофазный инвертор в 3ф сети питает только одну фазу: "
                    "резервируемые группы должны быть на одной фазе (без 3ф нагрузок)",
                )
            )
    if inp.grid == "1ph" and three_phase_out:
        fs.append(
            Finding("warning", "INVERTER_3PH_ON_1PH", "3ф инвертор в однофазной сети — избыточно")
        )
    if three_phase_out:
        per_phase_cap = cap / 3 if inv.phases == 3 else inv.p_ac_w
        worst_w = max(m.phase_va.values(), default=0.0)
        if worst_w > per_phase_cap + 1e-9:
            fs.append(
                Finding(
                    "error",
                    "INVERTER_PHASE_OVERLOAD",
                    f"Нагрузка фазы {worst_w:.0f} ВА выше возможностей инвертора на фазу "
                    f"({per_phase_cap:.0f} Вт)",
                )
            )
        if m.imbalance_pct > IMBALANCE_LIMIT_PCT + EPS:
            fs.append(
                Finding(
                    "warning",
                    "INVERTER_PHASE_IMBALANCE",
                    f"Перекос фаз резервной нагрузки {m.imbalance_pct:.0f}%",
                )
            )
    if required > cap + 1e-9:
        fs.append(
            Finding(
                "error",
                "INVERTER_UNDERSIZED",
                f"Мощность инвертора {cap:.0f} Вт меньше нагрузки {required:.0f} Вт",
            )
        )
    if m.p_start_w > surge + 1e-9:
        fs.append(
            Finding(
                "error",
                "INVERTER_SURGE",
                f"Пусковая мощность {m.p_start_w:.0f} Вт выше пиковой мощности инвертора "
                f"({surge:.0f} Вт)",
            )
        )
    if inv.bypass_a > 0 and m.i_backup_a > inv.bypass_a + 1e-9:
        fs.append(
            Finding(
                "warning",
                "INVERTER_BYPASS",
                f"Ток нагрузки {m.i_backup_a:.0f} А выше тока байпаса {inv.bypass_a:.0f} А",
            )
        )
    if inv.kind != "on-grid":
        _check_neutral_bond(inp, inv, fs)
    return cap, required


def _check_neutral_bond(inp: PowerInput, inv: InverterSpec, fs: list[Finding]) -> None:
    tn = inp.earthing in ("TN-S", "TN-C-S")
    if tn and not inv.bonds_n_pe_offgrid:
        fs.append(
            Finding(
                "warning",
                "NO_NPE_BOND_OFFGRID",
                "В автономе у инвертора нет связи N-PE: в TN-системе защита от косвенного "
                "прикосновения может не сработать — нужна связь N-PE при работе от инвертора",
            )
        )
    if inp.earthing == "TT" and inv.bonds_n_pe_offgrid:
        fs.append(
            Finding(
                "warning",
                "NPE_BOND_IN_TT",
                "В TT инвертор с связью N-PE в автономе создаёт локальную TN-систему: "
                "нужен собственный заземлитель и УЗО",
            )
        )
    fs.append(
        Finding(
            "info",
            "RCD_AFTER_INVERTER",
            "УЗО на выходе инвертора 30 мА"
            + (
                ", тип B/F (бестрансформаторный инвертор с DC-составляющей)"
                if inv.transformerless
                else ", тип A"
            )
            + "; учитывайте связь N-PE в автономном режиме",
        )
    )


def battery_usable_kwh(b: BatterySpec) -> float:
    dod = b.dod if b.dod > 0 else DOD_DEFAULT.get(b.chemistry, 0.5)
    return b.kwh * max(b.count, 1) * dod


def check_battery(
    inp: PowerInput,
    b: BatterySpec | None,
    inv: InverterSpec | None,
    m: Metrics,
    fs: list[Finding],
) -> tuple[float | None, float | None, float | None]:
    """Returns (autonomy h, DC current A, usable kWh)."""
    if inv is None or inv.kind == "on-grid":
        return None, None, None
    if b is None:
        fs.append(
            Finding("error", "BATTERY_MISSING", "Для гибридного/off-grid инвертора нужна АКБ")
        )
        return None, None, None
    usable = battery_usable_kwh(b)
    p_kw = m.p_backup_w / 1000
    autonomy = usable * INVERTER_EFF / p_kw if p_kw > 0 else None
    volts = b.voltage_v if b.voltage_v > 0 else inv.batt_v
    dc_a = (m.p_backup_w / (volts * INVERTER_EFF)) * DC_CURRENT_MARGIN if volts > 0 else None
    if abs(b.voltage_v - inv.batt_v) > inv.batt_v * 0.25 and b.voltage_v > 0:
        fs.append(
            Finding(
                "error",
                "BATTERY_VOLTAGE_MISMATCH",
                f"Напряжение АКБ {b.voltage_v:g} В не соответствует инвертору ({inv.batt_v:g} В)",
            )
        )
    limit = b.max_discharge_a * max(b.count, 1)
    if dc_a is not None and limit > 0 and dc_a > limit + 1e-9:
        fs.append(
            Finding(
                "error",
                "BATTERY_DISCHARGE_LIMIT",
                f"Ток разряда {dc_a:.0f} А выше допустимого для АКБ ({limit:.0f} А)",
            )
        )
    if autonomy is not None and autonomy < inp.autonomy_target_h - 1e-9:
        fs.append(
            Finding(
                "warning",
                "AUTONOMY_LOW",
                f"Автономия {autonomy:.1f} ч меньше целевой {inp.autonomy_target_h:.1f} ч",
            )
        )
    return autonomy, dc_a, usable


def phase_imbalance(per_phase_va: dict[str, float], grid: str) -> float:
    if grid == "1ph":
        return 0.0
    return imbalance_pct([per_phase_va[p] for p in PHASES])


def gen_current_a(gen: GeneratorSpec) -> float:
    if gen.phases == 3:
        return gen.kva * 1000 / (SQRT3 * VOLTAGE_3PH)
    return gen.kva * 1000 / VOLTAGE_1PH
