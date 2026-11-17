"""Burner bookkeeping: power weighting, hot water split and gas meter readings.

Pure Python, no Home Assistant imports, so every rule can be unit tested.
"""

from __future__ import annotations

from datetime import datetime

from .const import (
    GAS_CALIBRATION_MIN_HOURS,
    GAS_RATE_MAX,
    GAS_RATE_MIN,
    METER_SOURCE_MANUAL,
    METER_SOURCE_SENSOR,
    POWER_REF_HOURS,
    POWER_WEIGHT_MAX,
    POWER_WEIGHT_MIN,
)


def power_weight(power: float | None, reference: float | None) -> float:
    """How much one second of burner time at ``power`` counts, 1 at the usual power.

    A modulating boiler draws more electricity (its fan spins faster) when it burns
    more gas, so a burn at a higher plug power counts proportionally more.
    """
    if not power or not reference or power <= 0 or reference <= 0:
        return 1.0
    return min(max(power / reference, POWER_WEIGHT_MIN), POWER_WEIGHT_MAX)


def update_power_ref(reference: float | None, power: float | None, seconds: float) -> float | None:
    """Follow the usual burner power, as a time weighted average of recent burns."""
    if not power or power <= 0 or seconds <= 0:
        return reference
    if not reference:
        return round(power, 2)
    alpha = min(1.0, seconds / (POWER_REF_HOURS * 3600))
    return round(reference + alpha * (power - reference), 3)


def split_hot_water(
    start: datetime,
    end: datetime,
    demand_now: bool,
    demand_off_at: datetime | None,
    grace_seconds: float,
) -> tuple[float, float]:
    """Split a slice of burner time into (heating seconds, hot water seconds).

    The burner runs for the heating only while the main thermostat calls for heat
    (and for a short grace time after the call ends). Any other burn of a combi
    boiler is hot water: a shower or a tap.
    """
    seconds = max(0.0, (end - start).total_seconds())
    if demand_now:
        return seconds, 0.0
    if demand_off_at is None:
        return 0.0, seconds
    cutoff = (demand_off_at - start).total_seconds() + grace_seconds
    heating = min(max(cutoff, 0.0), seconds)
    return heating, seconds - heating


def meter_reading_action(
    baseline: dict | None, value: float, source: str
) -> str:
    """What to do with a gas meter index: ``baseline``, ``ignore`` or ``calibrate``.

    A lower index from the supplier after a reading typed in by hand is an old
    reading, not a new meter. A much lower index means the meter was replaced.
    """
    if baseline is None:
        return "baseline"
    last = float(baseline["meter"])
    if value >= last - 0.001:
        return "calibrate"
    if source == METER_SOURCE_SENSOR and baseline.get("source") == METER_SOURCE_MANUAL:
        return "ignore"
    if source == METER_SOURCE_MANUAL and value > last * 0.5:
        return "too_low"
    return "baseline"


def learned_rate(
    previous: float | None, used_m3: float, load_hours: float
) -> tuple[float | None, str]:
    """New m³ per burner hour from a meter reading: (rate or None, outcome)."""
    if used_m3 < 0.5 or load_hours < GAS_CALIBRATION_MIN_HOURS:
        return None, "wait"
    rate = used_m3 / load_hours
    if not GAS_RATE_MIN <= rate <= GAS_RATE_MAX:
        return None, "implausible"
    if previous:
        rate = 0.5 * float(previous) + 0.5 * rate
    return round(rate, 3), "learned"
