"""HeatWise decision engine.

Pure Python, no Home Assistant imports, so every rule can be unit tested.
The controller collects a snapshot of the house, calls :func:`evaluate`
and applies the resulting :class:`Plan` to the real devices.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SOURCE_BOILER = "boiler"
SOURCE_AC = "ac"

HYBRID_AUTO = "auto"
HYBRID_BOILER = "boiler_only"
HYBRID_AC = "ac_only"

PRESET_SCHEDULE = "schedule"
PRESET_COMFORT = "comfort"
PRESET_ECO = "eco"
PRESET_AWAY = "away"
PRESET_BOOST = "boost"
PRESETS = [PRESET_SCHEDULE, PRESET_COMFORT, PRESET_ECO, PRESET_AWAY, PRESET_BOOST]

AC_HEAT = "heat"
AC_OFF = "off"
AC_NONE = "none"

BOOST_DELTA = 2.0
DEMAND_MARGIN = 0.3


@dataclass
class Temps:
    """Temperature levels of a zone, in the house unit."""

    comfort: float = 21.0
    eco: float = 18.0
    away: float = 16.0
    frost: float = 7.0


@dataclass
class ZoneConfig:
    """Static description of a zone (the house itself is zone ``house``)."""

    zone_id: str
    name: str
    temps: Temps = field(default_factory=Temps)
    has_ac: bool = False
    has_trv: bool = False
    is_house: bool = False
    trv_follow_boiler: bool = False


@dataclass
class ZoneState:
    """Live state of a zone."""

    room_temp: float | None = None
    schedule_on: bool | None = None
    window_open: bool = False
    preset: str = PRESET_SCHEDULE
    override_temp: float | None = None
    enabled: bool = True
    ac_ours_running: bool = False
    ac_user_controlled: bool = False


@dataclass
class HybridConfig:
    """How HeatWise chooses between the boiler and the air conditioners."""

    mode: str = HYBRID_AUTO
    ac_threshold: float = 8.0
    gas_price: float | None = None
    electricity_price: float | None = None
    boiler_efficiency: float = 0.92
    cop_at_7: float = 3.5
    cop_slope: float = 0.08
    min_cop: float = 1.5
    ac_min_outdoor: float = -15.0
    ac_offset: float = 2.0
    ac_hyst_on: float = 0.5
    ac_hyst_off: float = 0.3


@dataclass
class HouseState:
    """Live state shared by every zone."""

    anyone_home: bool | None = None
    outdoor_temp: float | None = None
    warm_off_threshold: float | None = None
    previous_source: str = SOURCE_BOILER
    previous_warm_off: bool = False


@dataclass
class ZonePlan:
    """What should happen in one zone."""

    zone_id: str
    target: float
    reason: str
    demand: bool = False
    trv_target: float | None = None
    ac_action: str = AC_NONE
    ac_setpoint: float | None = None


@dataclass
class Plan:
    """The full decision for the house."""

    source: str
    source_reason: str
    warm_off: bool
    boiler_target: float
    house_reason: str
    zones: dict[str, ZonePlan]
    cop: float | None = None
    cost_gas: float | None = None
    cost_ac: float | None = None


def cop_at(outdoor: float, hybrid: HybridConfig) -> float:
    """Rough heat pump COP at an outdoor temperature (linear model)."""
    return max(hybrid.min_cop, hybrid.cop_at_7 + hybrid.cop_slope * (outdoor - 7.0))


def decide_warm_off(house: HouseState) -> bool:
    """True when it is warm enough outside to stop heating (1 °C hysteresis)."""
    thr = house.warm_off_threshold
    if thr is None or house.outdoor_temp is None:
        return False
    if house.previous_warm_off:
        return house.outdoor_temp > thr - 1.0
    return house.outdoor_temp > thr


def decide_source(
    house: HouseState, hybrid: HybridConfig, any_ac: bool
) -> tuple[str, str, float | None, float | None, float | None]:
    """Pick the heat source. Returns (source, reason, cop, cost_gas, cost_ac)."""
    if not any_ac:
        return SOURCE_BOILER, "no_ac", None, None, None
    if hybrid.mode == HYBRID_BOILER:
        return SOURCE_BOILER, "forced_boiler", None, None, None
    if hybrid.mode == HYBRID_AC:
        return SOURCE_AC, "forced_ac", None, None, None
    out = house.outdoor_temp
    if out is None:
        return SOURCE_BOILER, "no_outdoor", None, None, None
    if out < hybrid.ac_min_outdoor:
        return SOURCE_BOILER, "too_cold_for_ac", None, None, None

    was_ac = house.previous_source == SOURCE_AC
    if hybrid.gas_price is not None and hybrid.electricity_price is not None:
        cop = cop_at(out, hybrid)
        cost_gas = hybrid.gas_price / max(hybrid.boiler_efficiency, 0.1)
        cost_ac = hybrid.electricity_price / cop
        limit = cost_gas * (1.05 if was_ac else 0.95)
        if cost_ac <= limit:
            return SOURCE_AC, "ac_cheaper", cop, cost_gas, cost_ac
        return SOURCE_BOILER, "gas_cheaper", cop, cost_gas, cost_ac

    thr = hybrid.ac_threshold + (-0.5 if was_ac else 0.5)
    if out > thr:
        return SOURCE_AC, "above_threshold", None, None, None
    return SOURCE_BOILER, "below_threshold", None, None, None


def zone_target(
    cfg: ZoneConfig,
    state: ZoneState,
    house: HouseState,
    warm_off: bool,
    house_schedule_on: bool | None,
) -> tuple[float, str]:
    """Target temperature of a zone and the rule that decided it."""
    t = cfg.temps
    if not state.enabled:
        return t.frost, "off"
    if warm_off:
        return t.frost, "warm_outside"
    if state.window_open:
        return t.frost, "window_open"
    if state.override_temp is not None:
        return max(state.override_temp, t.frost), "manual"
    preset = state.preset
    if preset == PRESET_COMFORT:
        return t.comfort, "preset_comfort"
    if preset == PRESET_ECO:
        return t.eco, "preset_eco"
    if preset == PRESET_AWAY:
        return t.away, "preset_away"
    if preset == PRESET_BOOST:
        return t.comfort + BOOST_DELTA, "preset_boost"
    if house.anyone_home is False:
        return t.away, "away"
    schedule_on = state.schedule_on if state.schedule_on is not None else house_schedule_on
    if schedule_on is None:
        return t.comfort, "home"
    if schedule_on:
        return t.comfort, "schedule_comfort"
    return t.eco, "schedule_eco"


def _ac_action(
    cfg: ZoneConfig,
    state: ZoneState,
    target: float,
    source: str,
    hybrid: HybridConfig,
) -> tuple[str, float | None]:
    if not cfg.has_ac or state.ac_user_controlled:
        return AC_NONE, None
    if source != SOURCE_AC or target <= cfg.temps.frost:
        return (AC_OFF if state.ac_ours_running else AC_NONE), None
    room = state.room_temp
    if room is None:
        # No room sensor: let the AC regulate on its own sensor.
        return AC_HEAT, target
    want = room < target - hybrid.ac_hyst_on or (
        state.ac_ours_running and room < target + hybrid.ac_hyst_off
    )
    if want:
        return AC_HEAT, target + hybrid.ac_offset
    return (AC_OFF if state.ac_ours_running else AC_NONE), None


def evaluate(
    house_cfg: ZoneConfig,
    zones: list[ZoneConfig],
    states: dict[str, ZoneState],
    house: HouseState,
    hybrid: HybridConfig,
) -> Plan:
    """Decide what every device should do right now."""
    house_state = states.get(house_cfg.zone_id, ZoneState())
    warm_off = decide_warm_off(house)
    any_ac = any(z.has_ac for z in zones)
    source, source_reason, cop, cost_gas, cost_ac = decide_source(house, hybrid, any_ac)
    if warm_off or not house_state.enabled:
        source = SOURCE_BOILER
        source_reason = "warm_outside" if warm_off else "off"

    house_target, house_reason = zone_target(
        house_cfg, house_state, house, warm_off, None
    )
    house_schedule = house_state.schedule_on

    # Base boiler target: the house target, or the away level while the ACs heat.
    if source == SOURCE_AC:
        boiler_target = min(house_target, house_cfg.temps.away)
    else:
        boiler_target = house_target

    plans: dict[str, ZonePlan] = {}
    demand_targets: list[float] = []
    for cfg in zones:
        st = states.get(cfg.zone_id, ZoneState())
        target, reason = zone_target(cfg, st, house, warm_off, house_schedule)
        demand = st.room_temp is not None and st.room_temp < target - DEMAND_MARGIN
        zone_on_ac = source == SOURCE_AC and cfg.has_ac
        ac_action, ac_setpoint = _ac_action(cfg, st, target, source, hybrid)
        plan = ZonePlan(
            zone_id=cfg.zone_id,
            target=target,
            reason=reason,
            demand=demand,
            ac_action=ac_action,
            ac_setpoint=ac_setpoint,
        )
        if cfg.has_trv and not cfg.trv_follow_boiler:
            if zone_on_ac:
                plan.trv_target = min(target, cfg.temps.away)
            else:
                plan.trv_target = target
                if demand:
                    demand_targets.append(target)
        plans[cfg.zone_id] = plan

    if demand_targets and not warm_off and house_state.enabled:
        boiler_target = max(boiler_target, max(demand_targets))

    for cfg in zones:
        if cfg.has_trv and cfg.trv_follow_boiler:
            plans[cfg.zone_id].trv_target = boiler_target

    return Plan(
        source=source,
        source_reason=source_reason,
        warm_off=warm_off,
        boiler_target=boiler_target,
        house_reason=house_reason,
        zones=plans,
        cop=cop,
        cost_gas=cost_gas,
        cost_ac=cost_ac,
    )


REASONS: dict[str, dict[str, str]] = {
    "en": {
        "off": "HeatWise is off: frost protection only",
        "warm_outside": "Warm outside: heating stopped",
        "window_open": "Window open: heating lowered",
        "manual": "Manual temperature",
        "preset_comfort": "Comfort preset",
        "preset_eco": "Eco preset",
        "preset_away": "Away preset",
        "preset_boost": "Boost",
        "away": "Nobody home",
        "home": "Someone is home",
        "schedule_comfort": "Schedule: comfort",
        "schedule_eco": "Schedule: eco",
        "no_ac": "No air conditioner configured",
        "forced_boiler": "Boiler only (set by you)",
        "forced_ac": "Air conditioner only (set by you)",
        "no_outdoor": "No outdoor temperature: boiler",
        "too_cold_for_ac": "Too cold for the air conditioner",
        "ac_cheaper": "Air conditioner is cheaper now",
        "gas_cheaper": "Gas is cheaper now",
        "above_threshold": "Mild outside: air conditioner",
        "below_threshold": "Cold outside: boiler",
    },
    "ro": {
        "off": "HeatWise e oprit: doar protecție la îngheț",
        "warm_outside": "Cald afară: încălzirea e oprită",
        "window_open": "Fereastră deschisă: încălzire redusă",
        "manual": "Temperatură setată manual",
        "preset_comfort": "Mod confort",
        "preset_eco": "Mod eco",
        "preset_away": "Mod plecat",
        "preset_boost": "Boost",
        "away": "Nu e nimeni acasă",
        "home": "E cineva acasă",
        "schedule_comfort": "Program: confort",
        "schedule_eco": "Program: eco",
        "no_ac": "Niciun aer condiționat configurat",
        "forced_boiler": "Doar centrala (setat de tine)",
        "forced_ac": "Doar aerul condiționat (setat de tine)",
        "no_outdoor": "Fără temperatură exterioară: centrala",
        "too_cold_for_ac": "Prea frig pentru aerul condiționat",
        "ac_cheaper": "Aerul condiționat e mai ieftin acum",
        "gas_cheaper": "Gazul e mai ieftin acum",
        "above_threshold": "Afară e blând: aer condiționat",
        "below_threshold": "Afară e frig: centrala",
    },
}


def explain(reason: str, language: str = "en") -> str:
    """Human readable text for a reason code."""
    table = REASONS.get(language[:2].lower(), REASONS["en"])
    return table.get(reason, REASONS["en"].get(reason, reason))
