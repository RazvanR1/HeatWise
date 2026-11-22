"""Smart start helpers: preheat before the schedule, arrival home, messages.

Kept free of Home Assistant state handling where possible so they are easy to test.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

from .const import (
    ARRIVAL_LATCH_MINUTES,
    ARRIVAL_MIN_PROGRESS_KM,
    HEAT_RATE_MAX,
    HEAT_RATE_MIN,
    WINDOW_CLOSED_RISE,
    WINDOW_MIN_OPEN_MINUTES,
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


def absolute_humidity(temp: float, rh: float) -> float:
    """Grams of water per m³ of air at ``temp`` °C and ``rh`` % relative humidity."""
    saturation = 6.112 * math.exp(17.67 * temp / (temp + 243.5))  # hPa
    return saturation * rh * 2.1674 / (273.15 + temp)


def rooms_to_air(
    rooms: dict[str, tuple[float | None, float | None]],
    outdoor_temp: float | None,
    outdoor_rh: float | None,
    min_rh: float,
    min_diff: float,
) -> tuple[list[str], float | None, float | None]:
    """Humid rooms that airing would dry, with outdoor and worst indoor g/m³.

    ``rooms`` maps a name to (temperature, relative humidity).
    """
    if outdoor_temp is None or outdoor_rh is None:
        return [], None, None
    outside = absolute_humidity(outdoor_temp, outdoor_rh)
    names: list[str] = []
    worst: float | None = None
    for name, (temp, rh) in rooms.items():
        if temp is None or rh is None or rh < min_rh:
            continue
        inside = absolute_humidity(temp, rh)
        if inside - outside >= min_diff:
            names.append(name)
            worst = inside if worst is None else max(worst, inside)
    return names, round(outside, 1), (round(worst, 1) if worst is not None else None)


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


class WindowDetector:
    """Guesses an open window from a fast drop of a room's temperature.

    Heating, a switched-off AC or the night never cool a room by most of a
    degree in a few minutes; cold air from an open window does.
    """

    def __init__(self) -> None:
        self.history: dict[str, list[tuple[datetime, float]]] = {}
        self.open_since: dict[str, datetime] = {}
        self.lowest: dict[str, float] = {}

    def is_open(self, key: str) -> bool:
        return key in self.open_since

    def update(
        self,
        key: str,
        temp: float | None,
        now: datetime,
        drop: float,
        minutes: float,
        hold_minutes: float,
    ) -> bool:
        """Feed the current temperature of a room; True while a window seems open."""
        if temp is None:
            return self.is_open(key)
        since = self.open_since.get(key)
        if since is not None:
            open_minutes = (now - since).total_seconds() / 60
            lowest = min(self.lowest.get(key, temp), temp)
            self.lowest[key] = lowest
            recovering = temp >= lowest + WINDOW_CLOSED_RISE and open_minutes >= WINDOW_MIN_OPEN_MINUTES
            if recovering or open_minutes >= hold_minutes:
                self.open_since.pop(key, None)
                self.lowest.pop(key, None)
                # start over: closing must be followed by a new drop to count again
                self.history[key] = [(now, temp)]
                return False
            return True
        window = timedelta(minutes=minutes)
        points = [p for p in self.history.get(key, []) if now - p[0] <= window]
        points.append((now, temp))
        self.history[key] = points
        highest = max(v for _, v in points)
        if highest - temp >= drop - 1e-9:
            self.open_since[key] = now
            self.lowest[key] = temp
            return True
        return False

    def forget(self, key: str) -> None:
        self.history.pop(key, None)
        self.open_since.pop(key, None)
        self.lowest.pop(key, None)


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
        "window_drop": "The temperature in {zone} dropped fast: a window is probably open.",
        "window_drop_lowered": "The temperature in {zone} dropped fast: a window is probably open. Heating lowered until the room warms up again.",
        "offline_title": "HeatWise: device not responding",
        "offline": "{device} has not responded for {minutes} minutes.",
        "online": "{device} responds again.",
        "mould_title": "HeatWise: high humidity",
        "mould": "Humidity has been {rh}% in {zone} for {hours} h. Air the room for 5–10 minutes with the window wide open. It will not drop below {temp} °C until the humidity is down.",
        "mould_alert": "Humidity has been {rh}% in {zone} for {hours} h. Air the room for 5–10 minutes with the window wide open.",
        "vent_title": "HeatWise: good time to air",
        "vent": "The air outside is drier ({out} g/m³ of water against {inside} g/m³ in {zones}). Open the windows wide for 5–10 minutes, then close them.",
        "meter_title": "HeatWise: gas meter reading",
        "meter": "No gas meter reading for {days} days. Enter the index in HeatWise (Gas meter reading) so the gas use stays accurate.",
        "report_eff": "Efficiency: {eff} burner hours per degree-day (lower is better)",
        "report_eff_last": "Efficiency: {eff} burner hours per degree-day, last week {last} ({change})",
        "report_title": "HeatWise: this week",
        "report_gas": "Gas: {m3} m³ ({cost} {cur}), burner {hours} h",
        "report_gas_heating": "Gas for heating: {m3} m³ ({cost} {cur}), burner {hours} h",
        "report_hot_water": "Hot water: {m3} m³ of gas ({cost} {cur})",
        "report_ac": "AC electricity: {kwh} kWh ({cost} {cur})",
        "report_total": "Total heating: {cost} {cur}",
        "report_last": "Last week: {cost} {cur}",
        "report_empty": "No heating counted this week.",
    },
    "ro": {
        "window_title": "HeatWise: fereastră deschisă",
        "window": "Fereastră deschisă în {zone}.",
        "window_lowered": "Fereastră deschisă în {zone}: încălzirea e redusă până o închizi.",
        "window_drop": "Temperatura în {zone} a scăzut brusc: probabil e o fereastră deschisă.",
        "window_drop_lowered": "Temperatura în {zone} a scăzut brusc: probabil e o fereastră deschisă. Încălzirea e redusă până se încălzește din nou camera.",
        "offline_title": "HeatWise: dispozitiv care nu răspunde",
        "offline": "{device} nu mai răspunde de {minutes} minute.",
        "online": "{device} răspunde din nou.",
        "mould_title": "HeatWise: umiditate mare",
        "mould": "Umiditatea e {rh}% în {zone} de {hours} h. Aerisește 5–10 minute cu geamul larg deschis. Camera nu coboară sub {temp} °C până scade umiditatea.",
        "mould_alert": "Umiditatea e {rh}% în {zone} de {hours} h. Aerisește 5–10 minute cu geamul larg deschis.",
        "vent_title": "HeatWise: e momentul să aerisești",
        "vent": "Aerul de afară e mai uscat ({out} g/m³ apă față de {inside} g/m³ în {zones}). Deschide geamurile larg 5–10 minute, apoi închide-le.",
        "meter_title": "HeatWise: indexul de gaz",
        "meter": "Nicio citire a contorului de gaz de {days} zile. Trece indexul în HeatWise (Index contor gaz), ca să rămână corect consumul.",
        "report_eff": "Eficiență: {eff} ore de arzător pe grad-zi (mai puțin e mai bine)",
        "report_eff_last": "Eficiență: {eff} ore de arzător pe grad-zi, săptămâna trecută {last} ({change})",
        "report_title": "HeatWise: săptămâna aceasta",
        "report_gas": "Gaz: {m3} m³ ({cost} {cur}), arzătorul a mers {hours} h",
        "report_gas_heating": "Gaz pentru încălzire: {m3} m³ ({cost} {cur}), arzătorul a mers {hours} h",
        "report_hot_water": "Apă caldă: {m3} m³ gaz ({cost} {cur})",
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
    has_hot_water: bool = False,
    efficiency: float | None = None,
    last_efficiency: float | None = None,
) -> str:
    """Text of the Sunday report. With the hot water split, gas lines are heating only."""
    lang = lang[:2].lower()
    lines: list[str] = []

    def heating_total(values: dict[str, float]) -> float:
        total = 0.0
        if has_gas:
            total += values.get("gas_cost", 0.0)
            if has_hot_water:
                total -= values.get("dhw_cost", 0.0)
        if has_ac:
            total += values.get("ac_cost", 0.0)
        return total

    if has_gas:
        m3 = week.get("gas_m3", 0.0)
        cost = week.get("gas_cost", 0.0)
        hours = week.get("burner_h", 0.0)
        if has_hot_water:
            m3 -= week.get("dhw_m3", 0.0)
            cost -= week.get("dhw_cost", 0.0)
            hours -= week.get("dhw_h", 0.0)
        lines.append(
            notify_text(
                "report_gas_heating" if has_hot_water else "report_gas",
                lang,
                m3=_num(max(m3, 0.0), lang),
                cost=_num(max(cost, 0.0), lang, 2),
                hours=_num(max(hours, 0.0), lang),
                cur=currency,
            )
        )
    if efficiency is not None:
        if last_efficiency:
            change = (efficiency - last_efficiency) / last_efficiency * 100
            lines.append(notify_text("report_eff_last", lang, eff=_num(efficiency, lang, 2),
                                     last=_num(last_efficiency, lang, 2),
                                     change=("+" if change > 0 else "") + _num(change, lang, 0) + " %"))
        else:
            lines.append(notify_text("report_eff", lang, eff=_num(efficiency, lang, 2)))
    if has_ac:
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
    lines.append(notify_text("report_total", lang, cost=_num(heating_total(week), lang, 2), cur=currency))
    if has_gas and has_hot_water:
        lines.append(
            notify_text(
                "report_hot_water",
                lang,
                m3=_num(week.get("dhw_m3", 0.0), lang),
                cost=_num(week.get("dhw_cost", 0.0), lang, 2),
                cur=currency,
            )
        )
    if last_week:
        lines.append(notify_text("report_last", lang, cost=_num(heating_total(last_week), lang, 2), cur=currency))
    return "\n".join(lines)
