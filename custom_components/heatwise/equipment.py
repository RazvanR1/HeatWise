"""Turn datasheet numbers (or their absence) into the values the engine needs.

Everything is optional. What the person knows from the datasheet or the
energy label wins; otherwise a sensible average for the kind of device is used.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .const import (
    CONF_AC_ENERGY_CLASS,
    CONF_AC_HEAT_W,
    CONF_AC_INPUT_W,
    CONF_BOILER_EFFICIENCY,
    CONF_BOILER_EFFICIENCY_PCT,
    CONF_BOILER_POWER_KW,
    CONF_BOILER_TYPE,
    CONF_COP_AT_7,
    CONF_GAS_KWH_PER_M3,
    CONF_GAS_RATE,
    DEFAULT_BOILER_EFFICIENCY,
    DEFAULT_COP_AT_7,
    DEFAULT_GAS_KWH_PER_M3,
    DEFAULT_GAS_RATE,
)

BOILER_CONDENSING = "condensing"
BOILER_CONVENTIONAL = "conventional"
BOILER_UNKNOWN = "unknown"

# Seasonal efficiency against the gross calorific value (the kWh on the gas
# bill), typical for radiator systems.
EFFICIENCY_BY_TYPE = {
    BOILER_CONDENSING: 0.93,
    BOILER_CONVENTIONAL: 0.84,
    BOILER_UNKNOWN: DEFAULT_BOILER_EFFICIENCY,
}

# Datasheets give efficiency against the net calorific value (Hi), which is why
# condensing boilers show more than 100 %. The bill counts the gross value (Hs).
HI_TO_HS = 0.902

# Heating energy class (EU label) -> lower bound of SCOP for that class.
SCOP_BY_CLASS = {
    "a3p": 5.1,  # A+++
    "a2p": 4.6,  # A++
    "a1p": 4.0,  # A+
    "a": 3.4,
    "b": 3.1,
}
# COP at 7 °C is usually a little below the seasonal SCOP on the datasheet.
COP7_PER_SCOP = 0.93

# A boiler rarely runs at full power; this is the average share of the maximum
# used while it burns, for the first guess of gas per burner hour.
AVERAGE_MODULATION = 0.8


@dataclass
class Equipment:
    """Values the engine uses, and where each came from."""

    boiler_efficiency: float
    boiler_efficiency_source: str
    cop_at_7: float
    cop_source: str
    gas_rate_default: float
    gas_rate_source: str


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def resolve(config: dict[str, Any]) -> Equipment:
    """Pick the best known value for every number, falling back to averages."""
    # Boiler efficiency
    pct = _num(config.get(CONF_BOILER_EFFICIENCY_PCT))
    if pct is not None:
        efficiency = min(max(pct / 100 * HI_TO_HS, 0.5), 1.05)
        eff_source = "datasheet"
    elif _num(config.get(CONF_BOILER_EFFICIENCY)) is not None and not config.get(CONF_BOILER_TYPE):
        efficiency = float(config[CONF_BOILER_EFFICIENCY])
        eff_source = "manual"
    else:
        boiler_type = config.get(CONF_BOILER_TYPE, BOILER_UNKNOWN)
        efficiency = EFFICIENCY_BY_TYPE.get(boiler_type, DEFAULT_BOILER_EFFICIENCY)
        eff_source = "average" if boiler_type == BOILER_UNKNOWN else "boiler_type"

    # AC efficiency at 7 °C
    heat_w = _num(config.get(CONF_AC_HEAT_W))
    input_w = _num(config.get(CONF_AC_INPUT_W))
    energy_class = config.get(CONF_AC_ENERGY_CLASS)
    if heat_w is not None and input_w is not None:
        cop = min(max(heat_w / input_w, 1.5), 7.0)
        cop_source = "datasheet"
    elif energy_class in SCOP_BY_CLASS:
        cop = round(SCOP_BY_CLASS[energy_class] * COP7_PER_SCOP, 2)
        cop_source = "energy_class"
    elif _num(config.get(CONF_COP_AT_7)) is not None:
        cop = float(config[CONF_COP_AT_7])
        cop_source = "manual"
    else:
        cop = DEFAULT_COP_AT_7
        cop_source = "average"

    # First guess of gas per burner hour (the meter calibration replaces it)
    power = _num(config.get(CONF_BOILER_POWER_KW))
    kwh_per_m3 = _num(config.get(CONF_GAS_KWH_PER_M3)) or DEFAULT_GAS_KWH_PER_M3
    if _num(config.get(CONF_GAS_RATE)) is not None:
        rate = float(config[CONF_GAS_RATE])
        rate_source = "manual"
    elif power is not None:
        rate = round(power * AVERAGE_MODULATION / (kwh_per_m3 * efficiency), 2)
        rate_source = "boiler_power"
    else:
        rate = DEFAULT_GAS_RATE
        rate_source = "average"

    return Equipment(
        boiler_efficiency=round(efficiency, 3),
        boiler_efficiency_source=eff_source,
        cop_at_7=round(cop, 2),
        cop_source=cop_source,
        gas_rate_default=rate,
        gas_rate_source=rate_source,
    )
