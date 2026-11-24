"""Scenario templates: which devices a backup scheme needs and the safety rules of switching."""

from calculations.constants import VOLTAGE_1PH

from .checks import gen_current_a
from .loads import next_rating
from .models import (
    Component,
    Finding,
    Metrics,
    PowerInput,
    Scenario,
)

AC_SERIES: tuple[int, ...] = (6, 10, 16, 20, 25, 32, 40, 50, 63, 80, 100, 125, 160, 200, 250)
DC_SERIES: tuple[int, ...] = (32, 63, 100, 125, 160, 250)
ATS_MIN_A = 25

WITH_GENERATOR: frozenset[Scenario] = frozenset(
    {
        "grid_gen_ats",
        "manual_i0ii",
        "grid3_gen1_phase",
        "grid3_gen1_combine",
        "grid1_gen1",
        "grid_inverter_gen",
    }
)
WITH_INVERTER: frozenset[Scenario] = frozenset({"grid_inverter", "grid_inverter_gen"})

DESCRIPTIONS: dict[Scenario, str] = {
    "grid_gen_ats": "Сеть + генератор через АВР: при пропадании сети АВР переключает "
    "резервную шину на генератор, параллельная работа исключена блокировкой.",
    "grid_inverter": "Сеть + инвертор с АКБ: резервная шина питается через инвертор "
    "(байпас/сеть при наличии), автономия ограничена ёмкостью АКБ.",
    "grid_inverter_gen": "Сеть + инвертор + генератор: приоритеты источников задаются; "
    "генератор подключается ко входу инвертора через АВР и подзаряжает АКБ.",
    "manual_i0ii": "Ручной переключатель I-0-II: оператор выбирает сеть или генератор; "
    "положение 0 исключает параллельную работу.",
    "grid3_gen1_phase": "3ф сеть + 1ф генератор: генератор питает одну фазу, на неё "
    "должны быть сгруппированы все резервируемые группы; коммутируются фаза и N.",
    "grid3_gen1_combine": "3ф сеть + 1ф генератор: на резервной шине три фазы объединяются "
    "контактором с блокировкой, питаются только однофазные нагрузки.",
    "grid1_gen1": "1ф сеть + 1ф генератор через АВР или переключатель; коммутируются фаза и N.",
}


def required_ats_poles(inp: PowerInput) -> int:
    """Poles the changeover device must have so that the neutral is switched too."""
    if inp.scenario == "grid3_gen1_phase":
        return 2  # one phase + N
    if inp.grid == "3ph":
        return 4  # three phases + N (TN-S, TN-C-S and TT alike)
    return 2


def check_switching(inp: PowerInput, m: Metrics, fs: list[Finding]) -> None:
    sc = inp.scenario
    if sc in WITH_GENERATOR and inp.generator is None:
        fs.append(Finding("error", "GENERATOR_MISSING", "Для сценария нужен генератор"))
    if sc in WITH_INVERTER and inp.inverter is None:
        fs.append(Finding("error", "INVERTER_MISSING", "Для сценария нужен инвертор"))
    if sc == "grid_inverter" and inp.generator is not None:
        fs.append(
            Finding(
                "warning",
                "GENERATOR_IGNORED",
                "Генератор не используется в сценарии «сеть + инвертор»",
            )
        )
    if sc not in WITH_GENERATOR:
        return

    ats = inp.ats
    if ats.kind == "none":
        fs.append(
            Finding(
                "error",
                "PARALLEL_GEN_GRID",
                "Генератор подключён без АВР/переключателя: возможна параллельная работа "
                "с сетью и обратная трансформация — недопустимо",
            )
        )
        return
    if sc == "manual_i0ii" and ats.kind != "manual":
        fs.append(
            Finding(
                "error",
                "ATS_KIND_MISMATCH",
                "Сценарий «I-0-II» требует ручной переключатель",
            )
        )
    if sc != "manual_i0ii" and ats.kind == "manual":
        fs.append(
            Finding(
                "warning",
                "MANUAL_SWITCH",
                "Ручной переключатель не обеспечивает автоматического ввода резерва",
            )
        )
    if ats.kind == "contactor":
        if not ats.mechanical_interlock:
            fs.append(
                Finding(
                    "error",
                    "NO_MECHANICAL_INTERLOCK",
                    "АВР на контакторах без механической блокировки: возможно включение "
                    "обоих контакторов одновременно",
                )
            )
        if not ats.electrical_interlock:
            fs.append(
                Finding(
                    "error",
                    "NO_ELECTRICAL_INTERLOCK",
                    "АВР на контакторах без электрической блокировки (взаимные "
                    "размыкающие контакты в цепях катушек)",
                )
            )
    need = required_ats_poles(inp)
    if ats.poles < need:
        fs.append(
            Finding(
                "error",
                "N_NOT_SWITCHED",
                f"АВР {ats.poles}P не коммутирует нейтраль: нужно {need}P "
                f"({'3 фазы + N' if need == 4 else 'фаза + N'})",
            )
        )
    i_load = load_current_a(inp, m)
    if ats.rated_a > 0 and ats.rated_a < i_load - 1e-9:
        fs.append(
            Finding(
                "error",
                "ATS_UNDERSIZED",
                f"Номинал АВР {ats.rated_a:.0f} А меньше тока нагрузки {i_load:.0f} А",
            )
        )


def load_current_a(inp: PowerInput, m: Metrics) -> float:
    """Current the backup switchgear must carry."""
    if inp.scenario == "grid3_gen1_combine":
        return m.s_backup_va / VOLTAGE_1PH
    return m.i_backup_a


def build_components(inp: PowerInput, m: Metrics) -> tuple[Component, ...]:
    sc = inp.scenario
    out: list[Component] = []
    i_load = load_current_a(inp, m)
    ats_poles = required_ats_poles(inp)
    three = inp.grid == "3ph"

    if sc in WITH_GENERATOR and inp.generator is not None:
        gen = inp.generator
        i_gen = gen_current_a(gen)
        gen_poles = 4 if gen.phases == 3 else 2
        if sc != "grid_inverter_gen":
            ats_a = float(next_rating(max(i_load, ATS_MIN_A), AC_SERIES))
            if inp.ats.kind in ("contactor", "none"):
                out.append(
                    Component(
                        "ats",
                        "contactor",
                        ats_poles,
                        ats_a,
                        "АВР на двух контакторах + механическая блокировка + "
                        "электрическая блокировка (размыкающие контакты катушек)",
                        qty=2,
                    )
                )
                out.append(
                    Component(
                        "ats",
                        "interlock",
                        0,
                        0.0,
                        "Механическая блокировка пары контакторов",
                    )
                )
            elif inp.ats.kind == "modular":
                out.append(Component("ats", "ats_auto", ats_poles, ats_a, "Модульный АВР"))
            else:
                out.append(Component("ats", "ats_manual", ats_poles, ats_a, "Переключатель I-0-II"))
            out.append(
                Component(
                    "grid_in_breaker",
                    "mcb",
                    ats_poles,
                    float(next_rating(max(i_load, 6), AC_SERIES)),
                    "Автомат ввода от сети перед АВР",
                )
            )
        out.append(
            Component(
                "gen_in_breaker",
                "mcb",
                gen_poles if sc != "grid3_gen1_phase" else 2,
                float(next_rating(max(i_gen, 6), AC_SERIES)),
                "Автомат ввода от генератора",
            )
        )

    if sc in WITH_INVERTER and inp.inverter is not None:
        inv = inp.inverter
        phases3 = inv.phases == 3 or inv.mode == "phase_set"
        poles = 4 if phases3 else 2
        cap = inv.p_ac_w * max(inv.count, 1)
        i_out = cap / (3 * VOLTAGE_1PH) if phases3 else cap / VOLTAGE_1PH
        out.append(
            Component(
                "inv_in_breaker",
                "mcb",
                poles,
                float(next_rating(max(inv.bypass_a, i_load, 6), AC_SERIES)),
                "Автомат входа инвертора (сеть / байпас)",
            )
        )
        out.append(
            Component(
                "inv_out_breaker",
                "mcb",
                poles,
                float(next_rating(max(i_out, 6), AC_SERIES)),
                "Автомат выхода инвертора на резервную шину",
            )
        )
        out.append(
            Component(
                "rcd_inv_out",
                "rcd",
                poles,
                float(next_rating(max(i_out, 25), AC_SERIES)),
                "УЗО 30 мА после инвертора, тип " + ("B/F" if inv.transformerless else "A"),
            )
        )
        if m.battery_dc_a is not None:
            out.append(
                Component(
                    "battery_dc_breaker",
                    "dc_breaker",
                    2,
                    float(next_rating(m.battery_dc_a * 1.25, DC_SERIES)),
                    "DC-автомат АКБ по току инвертора",
                )
            )
        if sc == "grid_inverter_gen" and inp.generator is not None:
            ats_a = float(next_rating(max(i_load, ATS_MIN_A), AC_SERIES))
            out.append(
                Component(
                    "ats",
                    "ats_auto" if inp.ats.kind != "contactor" else "contactor",
                    4 if three else 2,
                    ats_a,
                    "АВР между сетью и генератором на входе инвертора",
                    qty=2 if inp.ats.kind == "contactor" else 1,
                )
            )

    if out:
        out.append(
            Component(
                "spd",
                "spd",
                4 if three and sc != "grid3_gen1_phase" else 2,
                0.0,
                "УЗИП тип 2 на резервной шине",
            )
        )
    return tuple(out)
