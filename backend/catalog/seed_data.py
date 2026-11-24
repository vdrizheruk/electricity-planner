"""Seed data for the catalog.

Prices are indicative (UAH incl. VAT, late 2026) and every item is flagged
``needs_verification=True``: SKUs follow each vendor's naming scheme but must be
checked against current vendor price lists before use in real quotations.
"""

from dataclasses import dataclass, field
from typing import Any

from .models import CategoryCode as C
from .models import Tier

CATEGORIES: list[tuple[str, str, str]] = [
    (C.MCB, "Автоматические выключатели", "Автоматичні вимикачі"),
    (C.RCD, "УЗО", "ПЗВ"),
    (C.RCBO, "Дифавтоматы", "Диф. автомати"),
    (C.SPD, "УЗИП (AC)", "ОПН (AC)"),
    (C.MAIN_SWITCH, "Вводные выключатели-разъединители", "Вводні вимикачі-роз'єднувачі"),
    (C.VOLTAGE_RELAY, "Реле напряжения", "Реле напруги"),
    (C.PHASE_RELAY, "Реле контроля фаз", "Реле контролю фаз"),
    (C.METER, "Счётчики", "Лічильники"),
    (C.CONTACTOR, "Контакторы", "Контактори"),
    (C.TIMER, "Таймеры", "Таймери"),
    (C.ATS, "АВР и переключатели", "АВР та перемикачі"),
    (C.BUSBAR, "Шины N/PE и гребёнки", "Шини N/PE та гребінки"),
    (C.DIN_RAIL, "DIN-рейки", "DIN-рейки"),
    (C.BLANK, "Заглушки", "Заглушки"),
    (C.LABEL, "Маркировка", "Маркування"),
    (C.TERMINAL, "Клеммники", "Клемники"),
    (C.ENCLOSURE, "Корпуса щитов", "Корпуси щитів"),
    (C.MOUNT_PANEL, "Монтажные панели", "Монтажні панелі"),
    (C.INVERTER, "Инверторы / ИБП", "Інвертори / ДБЖ"),
    (C.BATTERY, "АКБ", "АКБ"),
    (C.PV_MODULE, "Солнечные панели", "Сонячні панелі"),
    (C.DC_FUSE, "DC-предохранители gPV", "DC-запобіжники gPV"),
    (C.DC_ISOLATOR, "DC-разъединители", "DC-роз'єднувачі"),
    (C.DC_SPD, "DC-УЗИП", "DC-ОПН"),
    (C.DC_BREAKER, "DC-автоматы", "DC-автомати"),
    (C.PV_CONNECTOR, "Разъёмы MC4", "Роз'єми MC4"),
    (C.CABLE, "Кабели и провода", "Кабелі та проводи"),
    (C.GENERATOR, "Генераторы", "Генератори"),
]

# name: (tier, price factor relative to the "middle" price level)
BRANDS: dict[str, tuple[str, float]] = {
    "ABB": (Tier.PREMIUM, 1.45),
    "Schneider Electric": (Tier.PREMIUM, 1.55),
    "Hager": (Tier.PREMIUM, 1.40),
    "Eaton": (Tier.MIDDLE, 1.00),
    "IEK": (Tier.ECONOMY, 0.45),
    "E.NEXT": (Tier.ECONOMY, 0.40),
}
OTHER_BRANDS: dict[str, str] = {
    "Deye": Tier.MIDDLE,
    "Growatt": Tier.MIDDLE,
    "Victron Energy": Tier.PREMIUM,
    "Huawei": Tier.PREMIUM,
    "Pylontech": Tier.MIDDLE,
    "Dyness": Tier.MIDDLE,
    "JA Solar": Tier.MIDDLE,
    "LONGi": Tier.PREMIUM,
    "Jinko": Tier.MIDDLE,
    "NIK": Tier.ECONOMY,
    "Stäubli": Tier.PREMIUM,
    "Hyundai": Tier.MIDDLE,
    "Ritar": Tier.ECONOMY,
}


@dataclass
class Item:
    brand: str
    category: str
    sku: str
    name: str
    price: float
    series: str = ""
    rated_a: float | None = None
    poles: int | None = None
    curve: str = ""
    leakage_ma: int | None = None
    rcd_type: str = ""
    modules: float = 0
    size: tuple[int, int, int] | None = None  # w, h, d mm
    din: bool = True
    electrical: dict[str, Any] = field(default_factory=dict)

    @property
    def tier(self) -> str:
        if self.brand in BRANDS:
            return BRANDS[self.brand][0]
        return OTHER_BRANDS[self.brand]


def _brand_price(base: float, brand: str) -> float:
    return float(round(base * BRANDS[brand][1]))


def _mcb_sku(brand: str, poles: int, curve: str, a: int) -> str:
    return {
        "ABB": f"S20{poles}-{curve}{a}",
        "Schneider Electric": f"iC60N-{poles}P-{curve}{a}",
        "Hager": f"MC{poles}P-{curve}{a}",
        "Eaton": f"PL6-{curve}{a}/{poles}",
        "IEK": f"MVA20-{poles}-{a:03d}-{curve}",
        "E.NEXT": f"e.mcb.stand.45.{poles}.{curve}{a}",
    }[brand]


_MCB_SERIES = {
    "ABB": "S200",
    "Schneider Electric": "iC60N",
    "Hager": "MC",
    "Eaton": "PL6",
    "IEK": "ВА47-29",
    "E.NEXT": "e.mcb.stand",
}
_RCD_PREFIX = {
    "ABB": "F20",
    "Schneider Electric": "iID",
    "Hager": "CD",
    "Eaton": "PF6",
    "IEK": "VD1-63",
    "E.NEXT": "e.rccb.pro",
}
_RCBO_PREFIX = {
    "ABB": "DS201",
    "Schneider Electric": "iDPN-Vigi",
    "Hager": "ADA",
    "Eaton": "PFL6",
    "IEK": "AD12",
    "E.NEXT": "e.elcb.stand",
}
_SPD_PREFIX = {
    "ABB": "OVR-T2",
    "Schneider Electric": "iPRD",
    "Hager": "SPN",
    "Eaton": "SPBT12",
    "IEK": "OPS1",
    "E.NEXT": "e.ogz",
}
_SW_PREFIX = {
    "ABB": "SD200",
    "Schneider Electric": "iSW",
    "Hager": "SB",
    "Eaton": "P-SW",
    "IEK": "VN-32",
    "E.NEXT": "e.is",
}


def _breakers() -> list[Item]:
    items: list[Item] = []
    for brand in BRANDS:
        # MCB 1P / 3P
        mcb: list[tuple[int, str, int, float]] = [
            (1, "B", 16, 105),
            (1, "C", 16, 105),
            (1, "C", 25, 115),
            (1, "C", 32, 120),
            (3, "C", 16, 360),
            (3, "C", 32, 400),
        ]
        for poles, curve, a, base in mcb:
            items.append(
                Item(
                    brand,
                    C.MCB,
                    _mcb_sku(brand, poles, curve, a),
                    f"Автоматический выключатель {poles}P {curve}{a} 6 кА",
                    _brand_price(base, brand),
                    series=_MCB_SERIES[brand],
                    rated_a=a,
                    poles=poles,
                    curve=curve,
                    modules=poles,
                    size=(int(17.5 * poles), 90, 70),
                    electrical={"icn_ka": 6, "voltage_v": 230 if poles == 1 else 400},
                )
            )
        # RCD
        rcd: list[tuple[int, int, int, bool, float]] = [
            (2, 40, 30, False, 1350),
            (4, 40, 30, False, 2300),
            (4, 63, 300, True, 3100),
        ]
        for poles, a, ma, sel, base in rcd:
            typ = "A"
            items.append(
                Item(
                    brand,
                    C.RCD,
                    f"{_RCD_PREFIX[brand]}-{poles}P-{a}A-{ma}mA-{typ}",
                    f"УЗО {poles}P {a}A {ma}мА тип {typ}" + (" (S, пожарное)" if sel else ""),
                    _brand_price(base, brand),
                    rated_a=a,
                    poles=poles,
                    leakage_ma=ma,
                    rcd_type=typ,
                    modules=poles * 1.0 if poles == 4 else 2,
                    size=(int(17.5 * poles), 90, 70),
                    electrical={"selective": sel, "fire_protection": ma >= 100},
                )
            )
        # RCBO 1P+N
        for a, base in ((16, 1650), (32, 1750)):
            items.append(
                Item(
                    brand,
                    C.RCBO,
                    f"{_RCBO_PREFIX[brand]}-C{a}-30mA-A",
                    f"Дифавтомат 1P+N C{a} 30мА тип A",
                    _brand_price(base, brand),
                    rated_a=a,
                    poles=2,
                    curve="C",
                    leakage_ma=30,
                    rcd_type="A",
                    modules=2,
                    size=(35, 90, 70),
                    electrical={"icn_ka": 6},
                )
            )
        # SPD type 2 (all brands)
        for poles, label, base in ((2, "1P+N", 3500), (4, "3P+N", 6300)):
            items.append(
                Item(
                    brand,
                    C.SPD,
                    f"{_SPD_PREFIX[brand]}-{label}-275",
                    f"УЗИП тип 2 {label} 275В 20/40 кА",
                    _brand_price(base, brand),
                    poles=poles,
                    modules=poles,
                    size=(int(17.5 * poles), 90, 65),
                    electrical={"spd_type": "2", "uc_v": 275, "in_ka": 20, "imax_ka": 40},
                )
            )
        # Main switch / isolator
        for poles, a, base in ((2, 63, 620), (4, 63, 1050), (4, 100, 1650)):
            items.append(
                Item(
                    brand,
                    C.MAIN_SWITCH,
                    f"{_SW_PREFIX[brand]}-{poles}P-{a}",
                    f"Выключатель-разъединитель {poles}P {a}A",
                    _brand_price(base, brand),
                    rated_a=a,
                    poles=poles,
                    modules=poles,
                    size=(int(17.5 * poles), 90, 70),
                )
            )
    # SPD type 1+2 (premium brands only)
    for brand in ("ABB", "Schneider Electric"):
        for poles, label, base in ((2, "1P+N", 8000), (4, "3P+N", 14500)):
            items.append(
                Item(
                    brand,
                    C.SPD,
                    f"{_SPD_PREFIX[brand]}-T1T2-{label}-255",
                    f"УЗИП тип 1+2 {label} 255В 12.5 кА",
                    _brand_price(base, brand),
                    poles=poles,
                    modules=poles * 2,
                    size=(int(35 * poles), 90, 70),
                    electrical={
                        "spd_type": "1+2",
                        "uc_v": 255,
                        "iimp_ka": 12.5,
                        "in_ka": 25,
                        "imax_ka": 50,
                    },
                )
            )
    return items


def _enclosures() -> list[Item]:
    items: list[Item] = []
    prefix = {"Hager": "VF", "IEK": "ЩРВ-П", "E.NEXT": "e.mbox.pro.f"}
    for brand in ("Hager", "IEK", "E.NEXT"):
        for rows in (1, 2, 3, 4):
            mods = rows * 12
            items.append(
                Item(
                    brand,
                    C.ENCLOSURE,
                    f"{prefix[brand]}-{mods}",
                    f"Щит встраиваемый {mods} мод. IP40",
                    _brand_price(450 + rows * 450, brand),
                    modules=0,
                    size=(250, 90 + rows * 125, 95),
                    electrical={
                        "rows": rows,
                        "modules_per_row": 12,
                        "total_modules": mods,
                        "ip": 40,
                        "mounting": "flush",
                    },
                )
            )
    for brand in ("IEK", "E.NEXT"):
        for rows in (2,):
            mods = rows * 12
            items.append(
                Item(
                    brand,
                    C.ENCLOSURE,
                    f"{brand.replace('.', '')}-SURF65-{mods}",
                    f"Щит навесной {mods} мод. IP65",
                    _brand_price(1800, brand),
                    size=(300, 340, 130),
                    electrical={
                        "rows": rows,
                        "modules_per_row": 12,
                        "total_modules": mods,
                        "ip": 65,
                        "mounting": "surface",
                    },
                )
            )
    items.append(
        Item(
            "IEK",
            C.MOUNT_PANEL,
            "IEK-MP-300x400",
            "Монтажная панель 300×400 мм",
            _brand_price(520, "IEK"),
            din=False,
            size=(300, 400, 3),
            electrical={"material": "steel"},
        )
    )
    return items


def _accessories() -> list[Item]:
    i: list[Item] = []
    i += [
        Item(
            "E.NEXT",
            C.VOLTAGE_RELAY,
            "e.control.v-63",
            "Реле напряжения 63А",
            850,
            rated_a=63,
            poles=2,
            modules=3,
            electrical={"umin_v": 170, "umax_v": 270},
        ),
        Item(
            "IEK",
            C.VOLTAGE_RELAY,
            "RN-63",
            "Реле напряжения 63А",
            980,
            rated_a=63,
            poles=2,
            modules=3,
            electrical={"umin_v": 170, "umax_v": 270},
        ),
        Item(
            "E.NEXT",
            C.PHASE_RELAY,
            "e.control.f03",
            "Реле контроля фаз 3ф",
            720,
            poles=4,
            modules=1.0,
        ),
        Item("ABB", C.PHASE_RELAY, "CM-PVE", "Реле контроля фаз 3ф", 3900, poles=4, modules=1.0),
        Item(
            "ABB",
            C.METER,
            "B21-112-100",
            "Счётчик 1ф электронный DIN",
            3100,
            poles=2,
            modules=4,
            electrical={"phases": 1, "direct_a": 65},
        ),
        Item(
            "Schneider Electric",
            C.METER,
            "iEM3155",
            "Счётчик 3ф с трансформаторным подключением",
            9800,
            poles=4,
            modules=4,
            electrical={"phases": 3},
        ),
        Item(
            "NIK",
            C.METER,
            "NIK-2102-02",
            "Счётчик 1ф электронный DIN 5(60)А",
            1600,
            poles=2,
            modules=4,
            electrical={"phases": 1, "direct_a": 60, "bidirectional": True},
        ),
        Item(
            "NIK",
            C.METER,
            "NIK-2303-AP3",
            "Счётчик 3ф электронный DIN 5(60)А",
            3900,
            poles=4,
            modules=7,
            electrical={"phases": 3, "direct_a": 60, "bidirectional": True},
        ),
        Item(
            "Hager",
            C.CONTACTOR,
            "ESC225S",
            "Контактор модульный 2P 25A 230В",
            1650,
            rated_a=25,
            poles=2,
            modules=1.0,
            electrical={"coil_v": 230},
        ),
        Item(
            "ABB",
            C.CONTACTOR,
            "ESB-40-40",
            "Контактор модульный 4P 40A 230В",
            3900,
            rated_a=40,
            poles=4,
            modules=3,
            electrical={"coil_v": 230},
        ),
        Item(
            "IEK",
            C.CONTACTOR,
            "KMR-125",
            "Контактор модульный 2P 25A 230В",
            590,
            rated_a=25,
            poles=2,
            modules=1.0,
            electrical={"coil_v": 230},
        ),
        Item(
            "Eaton",
            C.CONTACTOR,
            "DILM40-10",
            "Контактор силовой 3P 40A 230В",
            3300,
            rated_a=40,
            poles=3,
            din=False,
            size=(55, 85, 100),
            electrical={"coil_v": 230},
        ),
        Item(
            "ABB",
            C.CONTACTOR,
            "AF40-30-00",
            "Контактор силовой 3P 40A 230В",
            4200,
            rated_a=40,
            poles=3,
            din=False,
            size=(55, 85, 100),
            electrical={"coil_v": 230},
        ),
        Item(
            "Eaton",
            C.ATS,
            "DILM40-XMV",
            "Механическая блокировка контакторов",
            1250,
            din=False,
            electrical={"mechanical_interlock": True},
        ),
        Item(
            "ABB",
            C.ATS,
            "OT63F4C",
            "Переключатель I-0-II 4P 63A",
            4800,
            rated_a=63,
            poles=4,
            modules=4,
            din=False,
            electrical={"manual": True, "positions": "I-0-II"},
        ),
        Item(
            "IEK",
            C.ATS,
            "VPR-4-63",
            "Переключатель I-0-II 4P 63A",
            1900,
            rated_a=63,
            poles=4,
            modules=4,
            electrical={"manual": True, "positions": "I-0-II"},
        ),
        Item(
            "E.NEXT",
            C.ATS,
            "e.ats.4p.63",
            "Модульный АВР 4P 63A",
            9500,
            rated_a=63,
            poles=4,
            modules=8,
            electrical={"automatic": True},
        ),
        Item("Hager", C.TIMER, "EH011", "Таймер суточный модульный", 1900, modules=1.0),
        Item("IEK", C.TIMER, "THC15A", "Таймер суточный модульный", 520, modules=1.0),
        Item(
            "IEK",
            C.BUSBAR,
            "YNS10-N12",
            "Шина N 12 отв. на DIN",
            90,
            modules=2.0,
            electrical={"kind": "N", "holes": 12},
        ),
        Item(
            "IEK",
            C.BUSBAR,
            "YNS10-PE12",
            "Шина PE 12 отв. на DIN",
            95,
            modules=2.0,
            electrical={"kind": "PE", "holes": 12},
        ),
        Item(
            "Hager",
            C.BUSBAR,
            "KN12N",
            "Шина N 12 отв. на DIN",
            260,
            modules=2.0,
            electrical={"kind": "N", "holes": 12},
        ),
        Item(
            "IEK",
            C.BUSBAR,
            "YZN10-1P-12",
            "Гребёнка 1P 63A 12 мод.",
            70,
            rated_a=63,
            poles=1,
            modules=0,
            electrical={"kind": "comb", "length_modules": 12},
        ),
        Item(
            "IEK",
            C.BUSBAR,
            "YZN10-3P-12",
            "Гребёнка 3P 63A 12 мод.",
            160,
            rated_a=63,
            poles=3,
            modules=0,
            electrical={"kind": "comb", "length_modules": 12},
        ),
        Item(
            "Hager",
            C.BUSBAR,
            "KB163A",
            "Гребёнка 3P 63A 12 мод.",
            420,
            rated_a=63,
            poles=3,
            modules=0,
            electrical={"kind": "comb", "length_modules": 12},
        ),
        Item(
            "IEK",
            C.DIN_RAIL,
            "YDN10-0200",
            "DIN-рейка 35 мм, 200 мм",
            45,
            modules=0,
            electrical={"length_mm": 200},
        ),
        Item("IEK", C.BLANK, "ZP-1", "Заглушка 1 модуль", 14, modules=1.0),
        Item("Hager", C.BLANK, "KA02", "Заглушка 1 модуль", 42, modules=1.0),
        Item("E.NEXT", C.LABEL, "e.label.sheet", "Набор маркировки для щита (лист)", 120),
        Item(
            "IEK",
            C.TERMINAL,
            "YZN10-16",
            "Клеммник винтовой 16 мм² на DIN",
            38,
            modules=0,
            electrical={"max_mm2": 16},
        ),
        Item(
            "IEK",
            C.TERMINAL,
            "YZN10-6",
            "Клеммник винтовой 6 мм² на DIN",
            22,
            modules=0,
            electrical={"max_mm2": 6},
        ),
        Item("E.NEXT", C.CABLE, "e.pugv.6", "Провод ПуГВ 6 мм² (м)", 42, electrical={"mm2": 6}),
        Item("E.NEXT", C.CABLE, "e.pugv.10", "Провод ПуГВ 10 мм² (м)", 68, electrical={"mm2": 10}),
        Item("E.NEXT", C.CABLE, "e.ferrule.set", "Наконечники НШВИ, набор", 160),
    ]
    return i


def _power() -> list[Item]:
    i: list[Item] = []
    inv = [
        (
            "Deye",
            "SUN-5K-SG03LP1-EU",
            "Гибридный инвертор 5 кВт 1ф",
            61000,
            dict(
                kind="hybrid",
                phases=1,
                p_ac_w=5000,
                p_surge_w=10000,
                mppt_count=2,
                mppt_min_v=125,
                mppt_max_v=425,
                vmax_v=500,
                imax_per_mppt_a=13,
                isc_max_per_mppt_a=17,
                bypass_a=50,
                batt_v=48,
                batt_charge_a=120,
            ),
        ),
        (
            "Deye",
            "SUN-8K-SG01LP1-EU",
            "Гибридный инвертор 8 кВт 1ф",
            87000,
            dict(
                kind="hybrid",
                phases=1,
                p_ac_w=8000,
                p_surge_w=16000,
                mppt_count=2,
                mppt_min_v=125,
                mppt_max_v=425,
                vmax_v=500,
                imax_per_mppt_a=18,
                isc_max_per_mppt_a=22,
                bypass_a=63,
                batt_v=48,
                batt_charge_a=190,
            ),
        ),
        (
            "Deye",
            "SUN-12K-SG04LP3-EU",
            "Гибридный инвертор 12 кВт 3ф",
            118000,
            dict(
                kind="hybrid",
                phases=3,
                p_ac_w=12000,
                p_surge_w=24000,
                mppt_count=2,
                mppt_min_v=200,
                mppt_max_v=850,
                vmax_v=1000,
                imax_per_mppt_a=26,
                isc_max_per_mppt_a=32,
                bypass_a=63,
                batt_v=48,
                batt_charge_a=240,
            ),
        ),
        (
            "Growatt",
            "SPH-10000TL3-BH",
            "Гибридный инвертор 10 кВт 3ф",
            112000,
            dict(
                kind="hybrid",
                phases=3,
                p_ac_w=10000,
                p_surge_w=15000,
                mppt_count=2,
                mppt_min_v=140,
                mppt_max_v=1000,
                vmax_v=1000,
                imax_per_mppt_a=16,
                isc_max_per_mppt_a=20,
                bypass_a=40,
                batt_v=400,
                batt_charge_a=25,
            ),
        ),
        (
            "Growatt",
            "MIN-5000TL-X",
            "Сетевой инвертор 5 кВт 1ф",
            36000,
            dict(
                kind="on-grid",
                phases=1,
                p_ac_w=5000,
                mppt_count=2,
                mppt_min_v=80,
                mppt_max_v=550,
                vmax_v=600,
                imax_per_mppt_a=13,
                isc_max_per_mppt_a=16,
            ),
        ),
        (
            "Huawei",
            "SUN2000-15KTL-M2",
            "Сетевой инвертор 15 кВт 3ф",
            105000,
            dict(
                kind="on-grid",
                phases=3,
                p_ac_w=15000,
                mppt_count=2,
                mppt_min_v=200,
                mppt_max_v=1000,
                vmax_v=1100,
                imax_per_mppt_a=22,
                isc_max_per_mppt_a=30,
            ),
        ),
        (
            "Victron Energy",
            "MultiPlus-II-48/5000/70-50",
            "Инвертор-зарядное 4 кВт off-grid 1ф",
            94000,
            dict(
                kind="off-grid",
                phases=1,
                p_ac_w=4000,
                p_surge_w=9000,
                bypass_a=50,
                batt_v=48,
                batt_charge_a=70,
            ),
        ),
        (
            "Victron Energy",
            "MultiPlus-II-48/3000/35-32",
            "Инвертор-зарядное 2.4 кВт off-grid 1ф",
            62000,
            dict(
                kind="off-grid",
                phases=1,
                p_ac_w=2400,
                p_surge_w=5500,
                bypass_a=32,
                batt_v=48,
                batt_charge_a=35,
            ),
        ),
    ]
    for brand, sku, name, price, el in inv:
        i.append(Item(brand, C.INVERTER, sku, name, float(price), electrical=el))
    bat = [
        ("Pylontech", "US5000", "АКБ LiFePO4 48В 4.8 кВт·ч", 52000, "LiFePO4", 48, 4.8, 100),
        ("Pylontech", "US3000C", "АКБ LiFePO4 48В 3.55 кВт·ч", 41000, "LiFePO4", 48, 3.55, 74),
        ("Dyness", "B4850", "АКБ LiFePO4 48В 2.4 кВт·ч", 28000, "LiFePO4", 48, 2.4, 50),
        ("Deye", "RW-M6.1", "АКБ LiFePO4 51.2В 6.14 кВт·ч", 69000, "LiFePO4", 51.2, 6.14, 120),
        ("Deye", "SE-G5.1-Pro", "АКБ LiFePO4 51.2В 5.12 кВт·ч", 62000, "LiFePO4", 51.2, 5.12, 100),
        ("Ritar", "RA12-100", "АКБ AGM 12В 100 А·ч", 6400, "AGM", 12, 1.2, 40),
    ]
    for brand, sku, name, price, chem, v, kwh, imax in bat:
        i.append(
            Item(
                brand,
                C.BATTERY,
                sku,
                name,
                float(price),
                electrical=dict(
                    chemistry=chem,
                    voltage_v=v,
                    kwh=kwh,
                    max_discharge_a=imax,
                    dod=0.9 if chem == "LiFePO4" else 0.5,
                ),
            )
        )
    pv = [
        ("JA Solar", "JAM54S30-410/MR", 410, 37.3, 13.9, 31.2, 13.15, 108),
        ("JA Solar", "JAM72S30-550/MR", 550, 49.7, 14.0, 41.9, 13.13, 144),
        ("LONGi", "LR5-54HTH-430M", 430, 38.1, 14.1, 31.8, 13.5, 108),
        ("LONGi", "LR5-72HPH-550M", 550, 49.8, 13.9, 41.7, 13.2, 144),
        ("Jinko", "JKM410N-54HL4-V", 410, 37.6, 13.8, 31.0, 13.2, 108),
        ("Jinko", "JKM580N-72HL4-V", 580, 51.6, 14.2, 43.0, 13.5, 144),
    ]
    for brand, sku, p, voc, isc, vmp, imp, cells in pv:
        i.append(
            Item(
                brand,
                C.PV_MODULE,
                sku,
                f"Солнечная панель {p} Вт",
                float(p * 11.5),
                size=(1134, 1722 if cells == 108 else 2278, 30),
                electrical=dict(
                    pmax_w=p,
                    voc_v=voc,
                    isc_a=isc,
                    vmp_v=vmp,
                    imp_a=imp,
                    beta_voc_pct_per_c=-0.25,
                    beta_vmp_pct_per_c=-0.30,
                    cells=cells,
                ),
            )
        )
    dc = [
        (
            "ABB",
            C.DC_FUSE,
            "E9F-PV-15",
            "Предохранитель gPV 10×38 15А 1000В DC",
            120.0,
            dict(rated_a=15, vdc_max=1000),
        ),
        (
            "ABB",
            C.DC_FUSE,
            "E9F-PV-20",
            "Предохранитель gPV 10×38 20А 1000В DC",
            125.0,
            dict(rated_a=20, vdc_max=1000),
        ),
        (
            "ABB",
            C.DC_ISOLATOR,
            "OTDC16-2S",
            "DC-разъединитель 2 строки 1000В 16А",
            2900.0,
            dict(rated_a=16, vdc_max=1000, strings=2),
        ),
        (
            "ABB",
            C.DC_ISOLATOR,
            "OTDC25-4S",
            "DC-разъединитель 4 строки 1000В 25А",
            4800.0,
            dict(rated_a=25, vdc_max=1000, strings=4),
        ),
        (
            "ABB",
            C.DC_SPD,
            "OVR-PV-T2-40-1000",
            "DC-УЗИП тип 2, Ucpv 1000В",
            4700.0,
            dict(ucpv_v=1000, spd_type="2", in_ka=20),
        ),
        (
            "IEK",
            C.DC_SPD,
            "OPS1-DC-T2-1000",
            "DC-УЗИП тип 2, Ucpv 1000В",
            2100.0,
            dict(ucpv_v=1000, spd_type="2", in_ka=20),
        ),
        (
            "ABB",
            C.DC_BREAKER,
            "S804PV-S32",
            "DC-автомат 4P 32А 1200В",
            3400.0,
            dict(rated_a=32, vdc_max=1200),
        ),
        (
            "Schneider Electric",
            C.DC_BREAKER,
            "iC60N-DC-2P-C125",
            "DC-автомат 2P 125А 250В",
            5200.0,
            dict(rated_a=125, vdc_max=250),
        ),
        (
            "Stäubli",
            C.PV_CONNECTOR,
            "MC4-PAIR",
            "Разъём MC4 пара (папа+мама)",
            85.0,
            dict(max_mm2=6),
        ),
        ("E.NEXT", C.CABLE, "e.pv1f.4", "Кабель PV1-F 4 мм² (м)", 48.0, dict(mm2=4, pv=True)),
        ("E.NEXT", C.CABLE, "e.pv1f.6", "Кабель PV1-F 6 мм² (м)", 68.0, dict(mm2=6, pv=True)),
    ]
    for brand, cat, sku, name, price, el in dc:
        rated = el.get("rated_a")
        i.append(
            Item(
                brand,
                cat,
                sku,
                name,
                price,
                rated_a=rated,
                poles={"S804PV-S32": 4, "iC60N-DC-2P-C125": 2}.get(sku),
                modules=1.0
                if cat == C.DC_FUSE
                else (4 if cat in (C.DC_ISOLATOR, C.DC_BREAKER) else 0),
                electrical=el,
            )
        )
    i += [
        Item(
            "Hyundai",
            C.GENERATOR,
            "HHY-7000FE",
            "Генератор бензин 1ф 5.5 кВт / 6.9 кВА, ЭС",
            38000,
            din=False,
            electrical=dict(phases=1, kva=6.9, kw=5.5, cos_phi=0.8, autostart_ready=True),
        ),
        Item(
            "Hyundai",
            C.GENERATOR,
            "DHY-12000SE-T",
            "Генератор дизель 3ф 10 кВт / 12.5 кВА, ЭС",
            135000,
            din=False,
            electrical=dict(phases=3, kva=12.5, kw=10, cos_phi=0.8, autostart_ready=True),
        ),
    ]
    return i


def build_items() -> list[Item]:
    return [*_breakers(), *_enclosures(), *_accessories(), *_power()]
