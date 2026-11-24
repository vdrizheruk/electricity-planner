"""Normative tables (ДБН В.2.5-23 / ПУЭ / IEC 60364-5-52), see docs/PLAN.md §5."""

VOLTAGE_1PH = 230.0
VOLTAGE_3PH = 400.0
SQRT3 = 3**0.5

# Cu resistivity at operating temperature (~70 °C), Ohm*mm²/m.
RHO_CU = 0.0225

BREAKER_SERIES: tuple[int, ...] = (6, 10, 16, 20, 25, 32, 40, 50, 63, 80, 100, 125)
RCD_SERIES: tuple[int, ...] = (25, 40, 63, 80, 100)

# Cross-sections, mm².
CABLE_SIZES: tuple[float, ...] = (1.5, 2.5, 4.0, 6.0, 10.0, 16.0, 25.0, 35.0)

# Cu, PVC insulation, in wall/conduit, 30 °C: ampacity by number of loaded conductors.
IZ_2_LOADED: dict[float, float] = {
    1.5: 19,
    2.5: 27,
    4.0: 36,
    6.0: 46,
    10.0: 63,
    16.0: 85,
    25.0: 112,
    35.0: 138,
}
IZ_3_LOADED: dict[float, float] = {
    1.5: 17,
    2.5: 25,
    4.0: 33,
    6.0: 42,
    10.0: 57,
    16.0: 76,
    25.0: 99,
    35.0: 121,
}

# Demand factors Kc by group type.
KC: dict[str, float] = {
    "lighting": 0.8,
    "sockets": 0.5,
    "kitchen": 0.7,
    "cooker": 0.7,
    "boiler": 1.0,
    "ac": 0.8,
    "floor_heating": 0.8,
    "washer": 0.7,
    "dishwasher": 0.7,
    "other": 0.6,
}
KC_DEFAULT = 0.6

# Minimum Cu cross-section by group type, mm².
MIN_CABLE_MM2: dict[str, float] = {
    "lighting": 1.5,
    "sockets": 2.5,
    "kitchen": 2.5,
    "cooker": 4.0,
    "boiler": 2.5,
    "ac": 2.5,
    "floor_heating": 2.5,
    "washer": 2.5,
    "dishwasher": 2.5,
    "other": 2.5,
}

# Recommended breaker curve by group type (B: resistive/lighting, C: inrush/motors).
CURVE: dict[str, str] = {
    "lighting": "B",
    "sockets": "B",
    "kitchen": "C",
    "cooker": "B",
    "boiler": "B",
    "ac": "C",
    "floor_heating": "B",
    "washer": "C",
    "dishwasher": "C",
    "other": "C",
}

# Practical lower limit of breaker rating by type (default 10 A).
MIN_BREAKER_A: dict[str, int] = {"lighting": 10, "sockets": 16, "kitchen": 16}
MIN_BREAKER_DEFAULT_A = 10

# Practical upper limit of breaker rating for a single circuit of the given type.
MAX_BREAKER_A: dict[str, int] = {"lighting": 10, "sockets": 16, "kitchen": 25}

# Types that get an individual RCBO (dedicated line) rather than a shared RCD.
INDIVIDUAL_RCBO_TYPES = frozenset({"cooker", "ac", "boiler", "washer", "dishwasher"})

GROUP_TYPES = frozenset(KC)
PHASES_1PH = ("L1",)
PHASES_3PH = ("L1", "L2", "L3")

# Limits.
IMBALANCE_LIMIT_PCT = 15.0
BREAKER_SELECTIVITY_RATIO = 1.6
RCD_SELECTIVITY_RATIO = 3.0
KO_THRESHOLD_GROUPS = 5
KO_FACTOR = 0.9
EPS = 1e-9
