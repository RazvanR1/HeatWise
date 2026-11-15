"""Smart start helpers: preheat before the schedule, arrival home, messages.

Kept free of Home Assistant state handling where possible so they are easy to test.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .const import (
    ARRIVAL_LATCH_MINUTES,
    ARRIVAL_MIN_PROGRESS_KM,
    HEAT_RATE_MAX,
    HEAT_RATE_MIN,
)

_UNIT_TO_KM = {"m": 0.001, "km": 1.0, "mi": 1.609344, "ft": 0.0003048, "yd": 0.0009144}


def preheat_due(
    next_on: datetime | None,
    now: datetime,
    gap: float | None,
    rate: float,
    max_minutes: float,
) -> bool:
    """True when the comfort period starts soon enough that heating must begin now.

    ``gap`` is how many degrees the room is below comfort, ``rate`` how many
    degrees per hour the house gains while heating.
    """
    if next_on is None or gap is None or gap <= 0:
        return False
    minutes_left = (next_on - now).total_seconds() / 60
    if minutes_left <= 0:
        return False
    rate = min(max(rate, HEAT_RATE_MIN), HEAT_RATE_MAX)
    lead = min(gap / rate * 60, max_minutes)
    return minutes_left <= lead


def learn_rate(previous: float | None, gain: float, hours: float) -> float | None:
    """New heat-up rate (°C/h) from one warm-up, smoothed with the previous one."""
    if hours < 0.25 or gain < 0.5:
        return None
    rate = gain / hours
    if not HEAT_RATE_MIN <= rate <= HEAT_RATE_MAX:
        return None
    if previous:
        rate = 0.7 * previous + 0.3 * rate
    return round(rate, 2)


class ArrivalWatcher:
    """Notices someone heading home from proximity distance sensors."""

    def __init__(self) -> None:
        self.farthest: dict[str, float] = {}
        self.until: datetime | None = None
        self.who: str | None = None

    @staticmethod
    def direction_entity(distance_entity: str) -> str:
        if distance_entity.endswith("_distance"):
            return distance_entity[: -len("_distance")] + "_direction_of_travel"
        return distance_entity + "_direction_of_travel"

    @staticmethod
    def to_km(value: Any, unit: str | None) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number * _UNIT_TO_KM.get((unit or "km").lower(), 1.0)

    def reset(self) -> None:
        self.farthest.clear()
        self.until = None
        self.who = None

    def update(
        self,
        readings: dict[str, tuple[float | None, str | None]],
        limit_km: float,
        anyone_home: bool | None,
        now: datetime,
    ) -> bool:
        """Feed {sensor: (distance km, direction)}; True while someone is on the way home."""
        if anyone_home is not False:
            self.reset()
            return False
        if self.until is not None and now < self.until:
            return True
        self.until = None
        for entity_id, (km, direction) in readings.items():
            if km is None:
                continue
            farthest = max(self.farthest.get(entity_id, 0.0), km)
            self.farthest[entity_id] = farthest
            heading_home = direction == "towards" if direction else True
            if (
                heading_home
                and km <= limit_km
                and farthest - km >= ARRIVAL_MIN_PROGRESS_KM
            ):
                self.until = now + timedelta(minutes=ARRIVAL_LATCH_MINUTES)
                self.who = entity_id
                return True
        return False


def _num(value: float, lang: str, digits: int = 1) -> str:
    text = f"{value:,.{digits}f}"
    if lang == "ro":
        text = text.replace(",", " ").replace(".", ",")
    return text


MESSAGES = {
    "en": {
        "window_title": "HeatWise: window open",
        "window": "Window open in {zone}.",
        "window_lowered": "Window open in {zone}: heating lowered until it is closed.",
        "offline_title": "HeatWise: device not responding",
        "offline": "{device} has not responded for {minutes} minutes.",
        "online": "{device} responds again.",
        "report_title": "HeatWise: this week",
        "report_gas": "Gas: {m3} m³ ({cost} {cur}), burner {hours} h",
        "report_ac": "AC electricity: {kwh} kWh ({cost} {cur})",
        "report_total": "Total heating: {cost} {cur}",
        "report_last": "Last week: {cost} {cur}",
        "report_empty": "No heating counted this week.",
    },
    "ro": {
        "window_title": "HeatWise: fereastră deschisă",
        "window": "Fereastră deschisă în {zone}.",
        "window_lowered": "Fereastră deschisă în {zone}: încălzirea e redusă până o închizi.",
        "offline_title": "HeatWise: dispozitiv care nu răspunde",
        "offline": "{device} nu mai răspunde de {minutes} minute.",
        "online": "{device} răspunde din nou.",
        "report_title": "HeatWise: săptămâna aceasta",
        "report_gas": "Gaz: {m3} m³ ({cost} {cur}), arzătorul a mers {hours} h",
        "report_ac": "Curent AC: {kwh} kWh ({cost} {cur})",
        "report_total": "Total încălzire: {cost} {cur}",
        "report_last": "Săptămâna trecută: {cost} {cur}",
        "report_empty": "Nicio încălzire numărată săptămâna aceasta.",
    },
}


def notify_text(key: str, lang: str, **values: Any) -> str:
    table = MESSAGES.get(lang[:2].lower(), MESSAGES["en"])
    return table.get(key, MESSAGES["en"][key]).format(**values)


def weekly_report(
    week: dict[str, float],
    last_week: dict[str, float] | None,
    lang: str,
    currency: str,
    has_gas: bool,
    has_ac: bool,
) -> str:
    lang = lang[:2].lower()
    lines: list[str] = []
    total = 0.0
    if has_gas:
        total += week.get("gas_cost", 0.0)
        lines.append(
            notify_text(
                "report_gas",
                lang,
                m3=_num(week.get("gas_m3", 0.0), lang),
                cost=_num(week.get("gas_cost", 0.0), lang, 2),
                hours=_num(week.get("burner_h", 0.0), lang),
                cur=currency,
            )
        )
    if has_ac:
        total += week.get("ac_cost", 0.0)
        lines.append(
            notify_text(
                "report_ac",
                lang,
                kwh=_num(week.get("ac_kwh", 0.0), lang),
                cost=_num(week.get("ac_cost", 0.0), lang, 2),
                cur=currency,
            )
        )
    if not lines:
        return notify_text("report_empty", lang)
    lines.append(notify_text("report_total", lang, cost=_num(total, lang, 2), cur=currency))
    if last_week:
        last = last_week.get("gas_cost", 0.0) * has_gas + last_week.get("ac_cost", 0.0) * has_ac
        lines.append(notify_text("report_last", lang, cost=_num(last, lang, 2), cur=currency))
    return "\n".join(lines)
