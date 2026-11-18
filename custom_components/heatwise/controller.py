"""HeatWise controller: reads Home Assistant, runs the engine, drives devices."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    EVENT_HOMEASSISTANT_STOP,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import engine
from .const import (
    AC_POWER_MAX_GAP_SECONDS,
    CONF_AC_MIN_OUTDOOR,
    CONF_AC_OFFSET,
    CONF_AC_THRESHOLD,
    CONF_ARRIVAL_KM,
    CONF_ARRIVAL_SENSORS,
    CONF_AWAY,
    CONF_AWAY_DELAY,
    CONF_BOILER,
    CONF_BOILER_POWER,
    CONF_BURNER_THRESHOLD,
    CONF_COMFORT,
    CONF_ECO,
    CONF_EL_PRICE,
    CONF_EL_PRICE_ENTITY,
    CONF_FROST,
    CONF_GAS_BY_POWER,
    CONF_GAS_KWH_PER_M3,
    CONF_GAS_METER,
    CONF_GAS_PRICE,
    CONF_GAS_PRICE_ENTITY,
    CONF_HOUSE_SENSOR,
    CONF_HYBRID_MODE,
    CONF_LANGUAGE,
    CONF_NAME,
    CONF_NOTIFY,
    CONF_NOTIFY_OFFLINE,
    CONF_NOTIFY_WINDOW,
    CONF_OUTDOOR,
    CONF_OVERRIDE_MINUTES,
    CONF_PERSONS,
    CONF_PREHEAT,
    CONF_PREHEAT_MAX,
    CONF_SCHEDULE,
    CONF_SPLIT_HOT_WATER,
    CONF_WARM_OFF,
    CONF_WEEKLY_REPORT,
    CONF_WINDOW_DETECT,
    CONF_WINDOW_DROP,
    CONF_WINDOW_DROP_MINUTES,
    CONF_WINDOW_HOLD,
    CONF_WINDOWS,
    CONF_ZONE_AC_POWER,
    CONF_ZONE_ACS,
    CONF_ZONE_FOLLOW_BOILER,
    CONF_ZONE_ID,
    CONF_ZONE_NAME,
    CONF_ZONE_SENSOR,
    CONF_ZONE_TRVS,
    CONF_ZONES,
    DEBOUNCE_SECONDS,
    DEFAULT_AC_MIN_OUTDOOR,
    DEFAULT_AC_OFFSET,
    DEFAULT_AC_THRESHOLD,
    DEFAULT_ARRIVAL_KM,
    DEFAULT_AWAY,
    DEFAULT_AWAY_DELAY,
    DEFAULT_BURNER_THRESHOLD,
    DEFAULT_COMFORT,
    DEFAULT_ECO,
    DEFAULT_FROST,
    DEFAULT_GAS_KWH_PER_M3,
    DEFAULT_HEAT_RATE,
    DEFAULT_OVERRIDE_MINUTES,
    DEFAULT_PREHEAT_MAX,
    DEFAULT_WINDOW_DROP,
    DEFAULT_WINDOW_DROP_MINUTES,
    DEFAULT_WINDOW_HOLD,
    DOMAIN,
    EVAL_INTERVAL_SECONDS,
    HEAT_SESSION_MAX_HOURS,
    HOT_WATER_GRACE_SECONDS,
    HOUSE_ZONE_ID,
    LANG_AUTO,
    METER_SOURCE_MANUAL,
    METER_SOURCE_SENSOR,
    OFFLINE_MINUTES,
    OWN_COMMAND_GRACE_SECONDS,
    REPORT_HOUR,
    REPORT_WEEKDAY,
    SIGNAL_UPDATE,
    STORAGE_VERSION,
    STORED_PERIODS,
    WINDOW_DELAY_SECONDS,
)
from .burner import (
    learned_rate,
    meter_reading_action,
    power_weight,
    split_hot_water,
    update_power_ref,
)
from .equipment import Equipment
from .equipment import resolve as resolve_equipment
from .smart import (
    ArrivalWatcher,
    WindowDetector,
    learn_rate,
    notify_text,
    preheat_due,
    weekly_report,
)

_LOGGER = logging.getLogger(__name__)

HEAT_ACTIONS = ("heating", "preheating")
BURNER_BOOK_SECONDS = 300


class MeterReadingError(ValueError):
    """A gas meter index typed in by hand that HeatWise cannot use."""

    def __init__(self, key: str, **placeholders: Any) -> None:
        super().__init__(key)
        self.key = key
        self.placeholders = placeholders

BOOST_MINUTES = 60
SCHEDULE_PRESETS = ("program", "schedule", "auto", "Program", "Schedule", "Auto")


def _float(state: State | None, attribute: str | None = None) -> float | None:
    if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        return None
    raw = state.attributes.get(attribute) if attribute else state.state
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def effective_config(entry: ConfigEntry) -> dict[str, Any]:
    """Options hold the full settings once saved; the name stays in data."""
    if entry.options:
        return {CONF_NAME: entry.data.get(CONF_NAME, entry.title), **entry.options}
    return dict(entry.data)


class HeatWiseController:
    """One controller per HeatWise house (config entry)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.store: Store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self.plan: engine.Plan | None = None
        self.zone_states: dict[str, engine.ZoneState] = {}
        self.control_enabled = True
        self.use_ac = True
        self.presets: dict[str, tuple[str, str | None]] = {}
        self.enabled: dict[str, bool] = {}
        self.overrides: dict[str, tuple[float, str]] = {}
        self.ac_owned: set[str] = set()
        self.ac_blocked: dict[str, str] = {}
        self.previous_source = engine.SOURCE_BOILER
        self.previous_warm_off = False
        self.burner_day = dt_util.now().date().isoformat()
        self.burner_seconds = 0.0
        self.burner_on_since: datetime | None = None
        self.burner_total_seconds = 0.0
        self.burner_load_seconds = 0.0
        self.burner_power: float | None = None
        self.power_ref: float | None = None
        self.heat_demand: bool | None = None
        self._demand_off_at: datetime | None = None
        self.gas_total_m3 = 0.0
        self.period_keys: dict[str, str] = self._current_period_keys()
        self.period_values: dict[str, dict[str, float]] = {
            p: self._empty_period() for p in STORED_PERIODS
        }
        self.last_week: dict[str, float] | None = None
        self.heat_rates: dict[str, float] = {}
        self._heat_sessions: dict[str, tuple[datetime, float, float]] = {}
        self.arrival = ArrivalWatcher()
        self.house_device_id: str | None = None
        self.preheating: dict[str, bool] = {}
        self._windows_seen: dict[str, bool] = {}
        self.window_detector = WindowDetector()
        self.windows_detected: dict[str, bool] = {}
        self._offline_notified: set[str] = set()
        self._ac_power_last: dict[str, tuple[float, datetime]] = {}
        self.gas_rate_learned: float | None = None
        self.gas_calibrations = 0
        self.gas_baseline: dict[str, Any] | None = None
        self.last_manual_reading: tuple[float, str] | None = None
        self.anyone_home: bool | None = None
        self._departed_at: datetime | None = None
        self._last_sent: dict[str, tuple[float, datetime]] = {}
        self._unsubs: list = []
        self._debounce_unsub = None

    # ------------------------------------------------------------------ config
    @property
    def config(self) -> dict[str, Any]:
        return effective_config(self.entry)

    @property
    def name(self) -> str:
        return self.config.get(CONF_NAME, "Home")

    @property
    def zones(self) -> list[dict[str, Any]]:
        return list(self.config.get(CONF_ZONES, []))

    @property
    def language_setting(self) -> str | None:
        """The language chosen in HeatWise, None to follow Home Assistant."""
        value = self.config.get(CONF_LANGUAGE, LANG_AUTO)
        return None if value in (None, "", LANG_AUTO) else value

    @property
    def language(self) -> str:
        return self.language_setting or self.hass.config.language or "en"

    @property
    def has_ac(self) -> bool:
        return any(z.get(CONF_ZONE_ACS) for z in self.zones)

    @property
    def has_power(self) -> bool:
        return bool(self.config.get(CONF_BOILER_POWER))

    def _house_temps(self) -> engine.Temps:
        c = self.config
        return engine.Temps(
            comfort=float(c.get(CONF_COMFORT, DEFAULT_COMFORT)),
            eco=float(c.get(CONF_ECO, DEFAULT_ECO)),
            away=float(c.get(CONF_AWAY, DEFAULT_AWAY)),
            frost=float(c.get(CONF_FROST, DEFAULT_FROST)),
        )

    def _zone_temps(self, zone: dict[str, Any]) -> engine.Temps:
        house = self._house_temps()
        return engine.Temps(
            comfort=float(zone.get(CONF_COMFORT, house.comfort)),
            eco=float(zone.get(CONF_ECO, house.eco)),
            away=float(zone.get(CONF_AWAY, house.away)),
            frost=house.frost,
        )

    def zone_name(self, zone_id: str) -> str:
        if zone_id == HOUSE_ZONE_ID:
            return self.name
        for zone in self.zones:
            if zone[CONF_ZONE_ID] == zone_id:
                return zone[CONF_ZONE_NAME]
        return zone_id

    # --------------------------------------------------------------- lifecycle
    async def async_setup(self) -> None:
        data = await self.store.async_load() or {}
        self.control_enabled = data.get("control", True)
        self.use_ac = data.get("use_ac", True)
        self.presets = {k: tuple(v) for k, v in data.get("presets", {}).items()}
        self.enabled = data.get("enabled", {})
        self.overrides = {k: tuple(v) for k, v in data.get("overrides", {}).items()}
        self.ac_owned = set(data.get("ac_owned", []))
        self.ac_blocked = data.get("ac_blocked", {})
        self.previous_source = data.get("source", engine.SOURCE_BOILER)
        self.previous_warm_off = data.get("warm_off", False)
        burner = data.get("burner", {})
        same_day = burner.get("day") == self.burner_day
        if same_day:
            self.burner_seconds = float(burner.get("seconds", 0))
        self.burner_total_seconds = float(burner.get("total_seconds", 0))
        # before 0.7 every burner second counted the same
        self.burner_load_seconds = float(burner.get("load_seconds", self.burner_total_seconds))
        self.power_ref = burner.get("power_ref")
        gas = data.get("gas", {})
        self.gas_total_m3 = float(gas.get("total_m3", 0))
        stored = data.get("periods", {})
        keys = stored.get("keys", {})
        for period in STORED_PERIODS:
            if keys.get(period) == self.period_keys[period]:
                self.period_values[period].update(stored.get("values", {}).get(period, {}))
        if data.get("periods_version", 0) < 2:
            self._migrate_periods(gas, same_day)
        self.gas_rate_learned = gas.get("rate_learned")
        self.gas_calibrations = int(gas.get("calibrations", 0))
        self.gas_baseline = gas.get("baseline")
        if self.gas_baseline is not None:
            self.gas_baseline.setdefault("load_s", self.gas_baseline.get("burner_s", 0.0))
            self.gas_baseline.setdefault("source", METER_SOURCE_SENSOR)
        manual = gas.get("last_manual")
        self.last_manual_reading = tuple(manual) if manual else None
        self.last_week = stored.get("last_week")
        self.heat_rates = {k: float(v) for k, v in data.get("heat_rates", {}).items()}

        self._unsubs.append(
            async_track_state_change_event(
                self.hass, self._tracked_entities(), self._on_state_change
            )
        )
        self._unsubs.append(
            async_track_time_interval(
                self.hass, self._on_interval, timedelta(seconds=EVAL_INTERVAL_SECONDS)
            )
        )
        self._unsubs.append(
            async_track_time_change(
                self.hass, self._on_report_time, hour=REPORT_HOUR, minute=0, second=0
            )
        )
        # book the burner run in progress when Home Assistant stops (update, restart)
        self._unsubs.append(self.hass.bus.async_listen(EVENT_HOMEASSISTANT_STOP, self._on_stop))
        self.heat_demand = self._boiler_demand(self._state(self.config.get(CONF_BOILER)))
        if self.has_power:
            power = _float(self.hass.states.get(self.config[CONF_BOILER_POWER]))
            if power is not None and power > self._burner_threshold:
                self.burner_on_since = dt_util.utcnow()
                self.burner_power = power
        if self.config.get(CONF_GAS_METER):
            self._gas_meter_update(self.hass.states.get(self.config[CONF_GAS_METER]))
        self.async_schedule_evaluate(delay=5)

    async def async_unload(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._debounce_unsub:
            self._debounce_unsub()
            self._debounce_unsub = None
        self._flush_burner(dt_util.utcnow())
        await self.store.async_save(self._store_data())

    async def _on_stop(self, _event: Event) -> None:
        """Home Assistant is stopping: keep the gas of a burner run still in progress."""
        self._flush_burner(dt_util.utcnow())
        await self.store.async_save(self._store_data())

    def _store_data(self) -> dict[str, Any]:
        return {
            "control": self.control_enabled,
            "use_ac": self.use_ac,
            "presets": self.presets,
            "enabled": self.enabled,
            "overrides": self.overrides,
            "ac_owned": sorted(self.ac_owned),
            "ac_blocked": self.ac_blocked,
            "source": self.previous_source,
            "warm_off": self.previous_warm_off,
            "burner": {
                "day": self.burner_day,
                "seconds": self.burner_runtime_seconds,
                "total_seconds": self.burner_total_live_seconds,
                "load_seconds": self.burner_load_live_seconds,
                "power_ref": self.power_ref,
            },
            "periods": {
                "keys": self.period_keys,
                "values": self.period_values,
                "last_week": self.last_week,
            },
            "heat_rates": self.heat_rates,
            "periods_version": 2,
            "gas": {
                "total_m3": self.gas_total_live,
                "rate_learned": self.gas_rate_learned,
                "calibrations": self.gas_calibrations,
                "baseline": self.gas_baseline,
                "last_manual": self.last_manual_reading,
            },
        }

    @callback
    def _save(self) -> None:
        self.store.async_delay_save(self._store_data, 10)

    def _tracked_entities(self) -> list[str]:
        c = self.config
        ids: list[str] = []
        for key in (
            CONF_BOILER,
            CONF_HOUSE_SENSOR,
            CONF_OUTDOOR,
            CONF_SCHEDULE,
            CONF_GAS_PRICE_ENTITY,
            CONF_EL_PRICE_ENTITY,
            CONF_BOILER_POWER,
            CONF_GAS_METER,
        ):
            if c.get(key):
                ids.append(c[key])
        ids.extend(c.get(CONF_PERSONS, []))
        for eid in c.get(CONF_ARRIVAL_SENSORS, []):
            ids.append(eid)
            ids.append(ArrivalWatcher.direction_entity(eid))
        ids.extend(c.get(CONF_WINDOWS, []))
        for zone in self.zones:
            for key in (CONF_ZONE_SENSOR, CONF_SCHEDULE):
                if zone.get(key):
                    ids.append(zone[key])
            for key in (CONF_ZONE_TRVS, CONF_ZONE_ACS, CONF_WINDOWS, CONF_ZONE_AC_POWER):
                ids.extend(zone.get(key, []))
        return sorted(set(ids))

    # ------------------------------------------------------------------ events
    @callback
    def _on_interval(self, _now: datetime) -> None:
        now = dt_util.utcnow()
        if self.burner_on_since is not None and (now - self.burner_on_since).total_seconds() >= BURNER_BOOK_SECONDS:
            # a long run is booked as it goes, so even a crash loses only a few minutes
            self._flush_burner(now)
            self._save()
        for zone in self.zones:
            for eid in zone.get(CONF_ZONE_AC_POWER, []):
                self._integrate_ac_power(zone, eid, self.hass.states.get(eid))
        self.hass.async_create_task(self._check_offline())
        self.async_schedule_evaluate(delay=0)

    @callback
    def _on_state_change(self, event: Event) -> None:
        entity_id: str = event.data["entity_id"]
        old: State | None = event.data.get("old_state")
        new: State | None = event.data.get("new_state")
        c = self.config
        if entity_id in c.get(CONF_PERSONS, []):
            if old is not None and new is not None and old.state == "home" and new.state != "home":
                self._departed_at = dt_util.utcnow()
        if entity_id == c.get(CONF_GAS_METER):
            self._gas_meter_update(new)
        if entity_id == c.get(CONF_BOILER_POWER):
            self._track_burner(new)
        elif entity_id == c.get(CONF_BOILER):
            self._boiler_changed(new)
            self._detect_manual(HOUSE_ZONE_ID, entity_id, old, new)
        elif entity_id == c.get(CONF_SCHEDULE):
            if old is not None and new is not None and old.state != new.state:
                self._schedule_changed(None)
        for zone in self.zones:
            zid = zone[CONF_ZONE_ID]
            if entity_id in zone.get(CONF_ZONE_TRVS, []):
                self._detect_manual(zid, entity_id, old, new)
            elif entity_id in zone.get(CONF_ZONE_AC_POWER, []):
                self._integrate_ac_power(zone, entity_id, old)
                self._ac_power_last[entity_id] = (_float(new) or 0.0, dt_util.utcnow())
            elif entity_id in zone.get(CONF_ZONE_ACS, []):
                self._detect_ac_change(entity_id, old, new)
            elif entity_id == zone.get(CONF_SCHEDULE):
                if old is not None and new is not None and old.state != new.state:
                    self._schedule_changed(zid)
        self.async_schedule_evaluate()

    @callback
    def async_schedule_evaluate(self, delay: float = DEBOUNCE_SECONDS) -> None:
        if self._debounce_unsub:
            self._debounce_unsub()
        self._debounce_unsub = async_call_later(self.hass, delay, self._debounced)

    async def _debounced(self, _now: datetime) -> None:
        self._debounce_unsub = None
        await self.async_evaluate()

    def _recently_sent(self, entity_id: str, value: float | None) -> bool:
        sent = self._last_sent.get(entity_id)
        if sent is None:
            return False
        sent_value, when = sent
        fresh = dt_util.utcnow() - when < timedelta(seconds=OWN_COMMAND_GRACE_SECONDS)
        return fresh or (value is not None and abs(sent_value - value) < 0.01)

    @callback
    def _detect_manual(
        self, zone_id: str, entity_id: str, old: State | None, new: State | None
    ) -> None:
        """A target change we did not send is a manual change by a person."""
        if not self.control_enabled or old is None or new is None:
            return
        before = _float(old, ATTR_TEMPERATURE)
        after = _float(new, ATTR_TEMPERATURE)
        if before is None or after is None or abs(before - after) < 0.01:
            return
        if self._recently_sent(entity_id, after):
            return
        self.set_override(zone_id, after, evaluate=False)
        _LOGGER.info("Manual change on %s to %s, kept for a while", entity_id, after)

    @callback
    def _detect_ac_change(self, entity_id: str, old: State | None, new: State | None) -> None:
        if old is None or new is None or old.state == new.state:
            return
        if self._recently_sent(entity_id, None):
            return
        if entity_id in self.ac_owned and new.state == "off":
            # Someone switched off an AC we were running: respect it for a while.
            self.ac_owned.discard(entity_id)
            self.ac_blocked[entity_id] = (
                dt_util.utcnow() + timedelta(minutes=self._override_minutes)
            ).isoformat()
            self._save()

    @callback
    def _schedule_changed(self, zone_id: str | None) -> None:
        """A schedule step ends manual changes of the zones that follow it."""
        affected = [HOUSE_ZONE_ID] if zone_id is None else [zone_id]
        if zone_id is None:
            affected += [
                z[CONF_ZONE_ID] for z in self.zones if not z.get(CONF_SCHEDULE)
            ]
        changed = False
        for zid in affected:
            if self.overrides.pop(zid, None) is not None:
                changed = True
        if changed:
            self._save()

    @property
    def _burner_threshold(self) -> float:
        return float(self.config.get(CONF_BURNER_THRESHOLD, DEFAULT_BURNER_THRESHOLD))

    @property
    def _override_minutes(self) -> int:
        return int(self.config.get(CONF_OVERRIDE_MINUTES, DEFAULT_OVERRIDE_MINUTES))

    # ------------------------------------------------------------- burner
    @property
    def split_hot_water(self) -> bool:
        """Count hot water apart: needs the plug and the main thermostat's heat call."""
        c = self.config
        return bool(c.get(CONF_SPLIT_HOT_WATER, True) and c.get(CONF_BOILER) and self.has_power)

    @property
    def gas_by_power(self) -> bool:
        return bool(self.config.get(CONF_GAS_BY_POWER, True))

    @staticmethod
    def _boiler_demand(state: State | None) -> bool | None:
        """Does the main thermostat call for heat? None when it cannot be told."""
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        if state.state == "off":
            return False
        action = state.attributes.get("hvac_action")
        if action is not None:
            return action in HEAT_ACTIONS
        target = _float(state, ATTR_TEMPERATURE)
        current = _float(state, "current_temperature")
        if target is None or current is None:
            return None
        return current < target

    @callback
    def _boiler_changed(self, new: State | None) -> None:
        """Close the burner slice at every change of the heat call, so it is split right."""
        demand = self._boiler_demand(new)
        if demand == self.heat_demand:
            return
        now = dt_util.utcnow()
        if self.burner_on_since is not None:
            self._flush_burner(now)
        if self.heat_demand is not False and demand is False:
            self._demand_off_at = now
        self.heat_demand = demand

    def _weight(self) -> float:
        if not self.gas_by_power:
            return 1.0
        return power_weight(self.burner_power, self.power_ref)

    def _slice(self, now: datetime) -> tuple[float, float, float]:
        """The running burner slice: (seconds, hot water seconds, weight)."""
        if self.burner_on_since is None:
            return 0.0, 0.0, 1.0
        start = self.burner_on_since
        seconds = max(0.0, (now - start).total_seconds())
        dhw = 0.0
        if self.split_hot_water:
            _heat, dhw = split_hot_water(
                start, now, self.heat_demand is not False, self._demand_off_at, HOT_WATER_GRACE_SECONDS
            )
        return seconds, dhw, self._weight()

    @callback
    def _flush_burner(self, now: datetime) -> None:
        """Book the burner time since it started (or since the last flush)."""
        if self.burner_on_since is None:
            return
        seconds, dhw_s, weight = self._slice(now)
        self.burner_seconds += seconds
        self.burner_total_seconds += seconds
        self.burner_load_seconds += seconds * weight
        gas = seconds * weight / 3600 * self.gas_rate
        dhw_gas = dhw_s * weight / 3600 * self.gas_rate
        self.gas_total_m3 += gas
        self._add_period("gas_m3", gas)
        self._add_period("burner_h", seconds / 3600)
        if dhw_s:
            self._add_period("dhw_m3", dhw_gas)
            self._add_period("dhw_h", dhw_s / 3600)
        price = self.gas_price_kwh
        if price is not None:
            self._add_period("gas_cost", gas * self.gas_kwh_per_m3 * price)
            if dhw_s:
                self._add_period("dhw_cost", dhw_gas * self.gas_kwh_per_m3 * price)
        self.power_ref = update_power_ref(self.power_ref, self.burner_power, seconds)
        self.burner_on_since = now

    @callback
    def _roll_burner_day(self) -> None:
        today = dt_util.now().date().isoformat()
        if today == self.burner_day:
            return
        self._flush_burner(dt_util.utcnow())
        self.burner_day = today
        self.burner_seconds = 0.0
        self._roll_periods()
        self._save()

    @callback
    def _track_burner(self, new: State | None) -> None:
        self._roll_burner_day()
        power = _float(new)
        running = power is not None and power > self._burner_threshold
        now = dt_util.utcnow()
        if running and self.burner_on_since is None:
            self.burner_on_since = now
            self.burner_power = power
        elif running:
            # the fan speed changed: book the time at the old power first
            self._flush_burner(now)
            self.burner_power = power
        elif self.burner_on_since is not None:
            self._flush_burner(now)
            self.burner_on_since = None
            self.burner_power = None
            self._save()

    # ------------------------------------------------------------------ gas
    @property
    def gas_rate(self) -> float:
        """m³ of gas per burner hour: learned from the meter, else the option."""
        if self.gas_rate_learned:
            return float(self.gas_rate_learned)
        return self.equipment.gas_rate_default

    @property
    def equipment(self) -> Equipment:
        return resolve_equipment(self.config)

    @property
    def gas_kwh_per_m3(self) -> float:
        return float(self.config.get(CONF_GAS_KWH_PER_M3, DEFAULT_GAS_KWH_PER_M3))

    def _live_seconds(self) -> float:
        if self.burner_on_since is None:
            return 0.0
        return max(0.0, (dt_util.utcnow() - self.burner_on_since).total_seconds())

    def _live_gas(self) -> tuple[float, float]:
        """Gas of the burner run still in progress: (all m³, hot water m³)."""
        seconds, dhw_s, weight = self._slice(dt_util.utcnow())
        rate = weight / 3600 * self.gas_rate
        return seconds * rate, dhw_s * rate

    @property
    def burner_total_live_seconds(self) -> float:
        return self.burner_total_seconds + self._live_seconds()

    @property
    def burner_load_live_seconds(self) -> float:
        seconds, _dhw, weight = self._slice(dt_util.utcnow())
        return self.burner_load_seconds + seconds * weight

    @property
    def gas_today_live(self) -> float:
        return self.period_value("gas_m3", "today")

    @property
    def gas_total_live(self) -> float:
        return self.gas_total_m3 + self._live_gas()[0]

    @property
    def gas_price_kwh(self) -> float | None:
        return self._price(CONF_GAS_PRICE_ENTITY, CONF_GAS_PRICE)

    @property
    def gas_cost_today(self) -> float | None:
        if self.gas_price_kwh is None:
            return None
        return self.period_value("gas_cost", "today")

    # ------------------------------------------------------------- periods
    @callback
    def _migrate_periods(self, gas: dict[str, Any], same_day: bool) -> None:
        """Fill the periods from the gas counted by 0.3.x/0.4.x (only the day and total existed).

        Gas tracking was first released in November 2026, so everything counted
        before this version belongs to this month and this year.
        """
        today = self.period_values["today"]
        if same_day and not today["gas_m3"]:
            today["gas_m3"] = float(gas.get("today_m3", 0))
        if dt_util.now().date().isoformat() < "2026-12-01":
            for period in ("month", "year"):
                values = self.period_values[period]
                values["gas_m3"] = max(values["gas_m3"], self.gas_total_m3, today["gas_m3"])
        price = self.gas_price_kwh
        if price is not None:
            for values in self.period_values.values():
                if not values["gas_cost"] and values["gas_m3"]:
                    values["gas_cost"] = values["gas_m3"] * self.gas_kwh_per_m3 * price
        self._save()

    @staticmethod
    def _empty_period() -> dict[str, float]:
        return {
            "gas_m3": 0.0,
            "gas_cost": 0.0,
            "ac_kwh": 0.0,
            "ac_cost": 0.0,
            "burner_h": 0.0,
            "dhw_m3": 0.0,
            "dhw_cost": 0.0,
            "dhw_h": 0.0,
        }

    @staticmethod
    def _current_period_keys() -> dict[str, str]:
        today = dt_util.now().date()
        return {
            "today": today.isoformat(),
            "week": "{}-W{:02d}".format(*today.isocalendar()[:2]),
            "month": today.strftime("%Y-%m"),
            "year": str(today.year),
        }

    @callback
    def _roll_periods(self) -> None:
        keys = self._current_period_keys()
        for period in STORED_PERIODS:
            if keys[period] != self.period_keys.get(period):
                if period == "week" and self.period_keys.get("week"):
                    self.last_week = dict(self.period_values["week"])
                self.period_values[period] = self._empty_period()
        self.period_keys = keys

    @callback
    def _add_period(self, metric: str, amount: float) -> None:
        self._roll_periods()
        for period in STORED_PERIODS:
            values = self.period_values[period]
            values[metric] = values.get(metric, 0.0) + amount

    def period_value(self, metric: str, period: str) -> float:
        """Booked value plus the part of a burner run still in progress."""
        value = self.period_values.get(period, {}).get(metric, 0.0)
        if self.period_keys.get(period) != self._current_period_keys()[period]:
            value = 0.0
        if self.burner_on_since is None:
            return value
        live_gas, live_dhw = self._live_gas()
        price = self.gas_price_kwh
        if metric == "burner_h":
            value += self._live_seconds() / 3600
        elif metric == "gas_m3":
            value += live_gas
        elif metric == "dhw_m3":
            value += live_dhw
        elif metric == "gas_cost" and price is not None:
            value += live_gas * self.gas_kwh_per_m3 * price
        elif metric == "dhw_cost" and price is not None:
            value += live_dhw * self.gas_kwh_per_m3 * price
        return value

    def heating_cost(self, period: str) -> float:
        """Gas for the heating plus the ACs; hot water is counted apart when it can be told."""
        gas = self.period_value("gas_cost", period)
        if self.split_hot_water:
            gas -= self.period_value("dhw_cost", period)
        return max(gas, 0.0) + self.period_value("ac_cost", period)

    @property
    def has_ac_power(self) -> bool:
        return any(z.get(CONF_ZONE_AC_POWER) for z in self.zones)

    @property
    def electricity_price_kwh(self) -> float | None:
        return self._price(CONF_EL_PRICE_ENTITY, CONF_EL_PRICE)

    @callback
    def _integrate_ac_power(self, zone: dict[str, Any], entity_id: str, state: State | None) -> None:
        """Add the energy an AC used since the last reading, while it was heating."""
        now = dt_util.utcnow()
        last = self._ac_power_last.get(entity_id)
        watts = _float(state)
        self._ac_power_last[entity_id] = (watts or 0.0, now)
        if last is None:
            return
        last_watts, since = last
        seconds = min((now - since).total_seconds(), AC_POWER_MAX_GAP_SECONDS)
        if seconds <= 0 or last_watts <= 0:
            return
        heating = any(
            (st := self.hass.states.get(ac)) is not None and st.state == "heat"
            for ac in zone.get(CONF_ZONE_ACS, [])
        )
        if not heating:
            return
        kwh = last_watts * seconds / 3600 / 1000
        self._add_period("ac_kwh", kwh)
        price = self.electricity_price_kwh
        if price is not None:
            self._add_period("ac_cost", kwh * price)

    @callback
    def _gas_meter_update(self, state: State | None) -> None:
        """A new index from the gas meter sensor (supplier integration, pulse counter…)."""
        value = _float(state)
        if value is not None:
            self._meter_reading(value, METER_SOURCE_SENSOR)

    @callback
    def async_manual_meter_reading(self, value: float) -> str:
        """An index read on the gas meter and typed in by hand. Returns the outcome."""
        if value < 0:
            raise MeterReadingError("meter_negative")
        action = meter_reading_action(self.gas_baseline, value, METER_SOURCE_MANUAL)
        if action == "too_low":
            raise MeterReadingError(
                "meter_too_low", last=f"{float(self.gas_baseline['meter']):g}"
            )
        outcome = self._meter_reading(value, METER_SOURCE_MANUAL)
        self.last_manual_reading = (value, dt_util.utcnow().isoformat())
        self._save()
        async_dispatcher_send(self.hass, SIGNAL_UPDATE.format(self.entry.entry_id))
        return outcome

    def _new_baseline(self, value: float, source: str) -> None:
        self.gas_baseline = {
            "meter": value,
            "burner_s": self.burner_total_live_seconds,
            "load_s": self.burner_load_live_seconds,
            "at": dt_util.utcnow().isoformat(),
            "source": source,
        }

    @callback
    def _meter_reading(self, value: float, source: str) -> str:
        """Learn the real gas use per burner hour from meter readings."""
        action = meter_reading_action(self.gas_baseline, value, source)
        if action in ("ignore", "too_low"):
            return action
        if action == "baseline":
            if self.gas_baseline is not None:
                # a new meter: older readings typed in by hand no longer apply
                self.last_manual_reading = None
            self._new_baseline(value, source)
            self._save()
            return "baseline"
        base = self.gas_baseline
        used = value - float(base["meter"])
        load_hours = (self.burner_load_live_seconds - float(base["load_s"])) / 3600
        rate, outcome = learned_rate(self.gas_rate_learned, used, load_hours)
        if outcome == "wait":
            # too little gas since the last reading: keep counting from it
            return "wait"
        if rate is not None:
            self.gas_rate_learned = rate
            self.gas_calibrations += 1
            _LOGGER.info("HeatWise learned %.3f m³ per burner hour", rate)
        else:
            _LOGGER.warning(
                "HeatWise ignored an implausible gas reading: %.2f m³ in %.1f burner hours", used, load_hours
            )
        self._new_baseline(value, source)
        self._save()
        return outcome

    @property
    def last_meter_reading(self) -> float | None:
        """The latest index HeatWise knows, typed in or from the sensor."""
        manual = self.last_manual_reading
        base = (self.gas_baseline or {}).get("meter")
        if manual and (base is None or manual[0] > float(base)):
            return manual[0]
        return float(base) if base is not None else None

    @property
    def burner_running(self) -> bool:
        return self.burner_on_since is not None

    @property
    def burner_runtime_seconds(self) -> float:
        extra = 0.0
        if self.burner_on_since is not None:
            extra = (dt_util.utcnow() - self.burner_on_since).total_seconds()
        return self.burner_seconds + extra

    # ------------------------------------------------------------ user actions
    @callback
    def set_override(self, zone_id: str, temperature: float, evaluate: bool = True) -> None:
        until = dt_util.utcnow() + timedelta(minutes=self._override_minutes)
        self.overrides[zone_id] = (float(temperature), until.isoformat())
        self._save()
        if evaluate:
            self.async_schedule_evaluate(delay=0)

    @callback
    def set_preset(self, zone_id: str, preset: str) -> None:
        until = None
        if preset == engine.PRESET_BOOST:
            until = (dt_util.utcnow() + timedelta(minutes=BOOST_MINUTES)).isoformat()
        self.presets[zone_id] = (preset, until)
        self.overrides.pop(zone_id, None)
        self._save()
        self.async_schedule_evaluate(delay=0)

    @callback
    def set_enabled(self, zone_id: str, enabled: bool) -> None:
        self.enabled[zone_id] = enabled
        self._save()
        self.async_schedule_evaluate(delay=0)

    @callback
    def set_control(self, enabled: bool) -> None:
        self.control_enabled = enabled
        self._save()
        self.async_schedule_evaluate(delay=0)

    @callback
    def set_use_ac(self, enabled: bool) -> None:
        self.use_ac = enabled
        self._save()
        self.async_schedule_evaluate(delay=0)

    def preset_of(self, zone_id: str) -> str:
        preset, until = self.presets.get(zone_id, (engine.PRESET_SCHEDULE, None))
        if until and dt_util.parse_datetime(until) <= dt_util.utcnow():
            self.presets.pop(zone_id, None)
            return engine.PRESET_SCHEDULE
        return preset

    def override_of(self, zone_id: str) -> tuple[float, str] | None:
        override = self.overrides.get(zone_id)
        if override is None:
            return None
        until = dt_util.parse_datetime(override[1])
        if until is None or until <= dt_util.utcnow():
            self.overrides.pop(zone_id, None)
            return None
        return override

    # ---------------------------------------------------------------- snapshot
    def _state(self, entity_id: str | None) -> State | None:
        return self.hass.states.get(entity_id) if entity_id else None

    def _outdoor(self) -> float | None:
        eid = self.config.get(CONF_OUTDOOR)
        if not eid:
            return None
        state = self._state(eid)
        if eid.startswith("weather."):
            return _float(state, "temperature")
        return _float(state)

    def _price(self, entity_key: str, value_key: str) -> float | None:
        value = _float(self._state(self.config.get(entity_key)))
        if value is None and self.config.get(value_key) is not None:
            value = float(self.config[value_key])
        return value

    def _schedule_on(self, entity_id: str | None) -> bool | None:
        state = self._state(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        return state.state == STATE_ON

    def _windows_open(self, entity_ids: list[str]) -> bool:
        now = dt_util.utcnow()
        for eid in entity_ids:
            state = self._state(eid)
            if state is not None and state.state == STATE_ON:
                if (now - state.last_changed).total_seconds() >= WINDOW_DELAY_SECONDS:
                    return True
        return False

    def _presence(self) -> bool | None:
        persons = self.config.get(CONF_PERSONS, [])
        if not persons:
            return None
        states = [self._state(p) for p in persons]
        known = [s for s in states if s is not None and s.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN)]
        if not known:
            return None
        if any(s.state == "home" for s in known):
            self._departed_at = None
            return True
        if self._departed_at is None:
            return False
        delay = timedelta(minutes=int(self.config.get(CONF_AWAY_DELAY, DEFAULT_AWAY_DELAY)))
        return dt_util.utcnow() - self._departed_at < delay

    def room_temperature(self, zone_id: str) -> float | None:
        if zone_id == HOUSE_ZONE_ID:
            value = _float(self._state(self.config.get(CONF_HOUSE_SENSOR)))
            if value is None:
                value = _float(self._state(self.config.get(CONF_BOILER)), "current_temperature")
            return value
        zone = self._zone(zone_id)
        if zone is None:
            return None
        value = _float(self._state(zone.get(CONF_ZONE_SENSOR)))
        if value is not None:
            return value
        readings = [
            _float(self._state(eid), "current_temperature")
            for eid in zone.get(CONF_ZONE_TRVS, []) + zone.get(CONF_ZONE_ACS, [])
        ]
        readings = [r for r in readings if r is not None]
        return round(sum(readings) / len(readings), 2) if readings else None

    def _wall_temperature(self, zone_id: str) -> float | None:
        """A room reading that can show a window: a room sensor or the wall thermostat.

        Valves and ACs measure next to themselves and cool down fast when they stop,
        so their own readings are never used to guess a window.
        """
        if zone_id == HOUSE_ZONE_ID:
            value = _float(self._state(self.config.get(CONF_HOUSE_SENSOR)))
            if value is None:
                value = _float(self._state(self.config.get(CONF_BOILER)), "current_temperature")
            return value
        zone = self._zone(zone_id) or {}
        return _float(self._state(zone.get(CONF_ZONE_SENSOR)))

    def _window_detected(self, zone_id: str) -> bool:
        c = self.config
        if not c.get(CONF_WINDOW_DETECT, True):
            self.window_detector.forget(zone_id)
            return False
        return self.window_detector.update(
            zone_id,
            self._wall_temperature(zone_id),
            dt_util.utcnow(),
            float(c.get(CONF_WINDOW_DROP, DEFAULT_WINDOW_DROP)),
            float(c.get(CONF_WINDOW_DROP_MINUTES, DEFAULT_WINDOW_DROP_MINUTES)),
            float(c.get(CONF_WINDOW_HOLD, DEFAULT_WINDOW_HOLD)),
        )

    def _zone(self, zone_id: str) -> dict[str, Any] | None:
        for zone in self.zones:
            if zone[CONF_ZONE_ID] == zone_id:
                return zone
        return None

    def _ac_flags(self, zone: dict[str, Any]) -> tuple[bool, bool]:
        """(ours running, user controlled) for the ACs of a zone."""
        ours = False
        user = False
        now = dt_util.utcnow()
        for eid in zone.get(CONF_ZONE_ACS, []):
            state = self._state(eid)
            blocked = self.ac_blocked.get(eid)
            if blocked:
                until = dt_util.parse_datetime(blocked)
                if until and until > now:
                    user = True
                else:
                    self.ac_blocked.pop(eid, None)
            if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                continue
            if state.state != "off":
                if eid in self.ac_owned:
                    ours = True
                else:
                    user = True
            elif eid in self.ac_owned and not self._recently_sent(eid, None):
                self.ac_owned.discard(eid)
        return ours, user

    def _hybrid(self) -> engine.HybridConfig:
        c = self.config
        mode = c.get(CONF_HYBRID_MODE, engine.HYBRID_AUTO)
        if not self.use_ac:
            mode = engine.HYBRID_BOILER
        return engine.HybridConfig(
            mode=mode,
            ac_threshold=float(c.get(CONF_AC_THRESHOLD, DEFAULT_AC_THRESHOLD)),
            ac_min_outdoor=float(c.get(CONF_AC_MIN_OUTDOOR, DEFAULT_AC_MIN_OUTDOOR)),
            ac_offset=float(c.get(CONF_AC_OFFSET, DEFAULT_AC_OFFSET)),
            gas_price=self._price(CONF_GAS_PRICE_ENTITY, CONF_GAS_PRICE),
            electricity_price=self._price(CONF_EL_PRICE_ENTITY, CONF_EL_PRICE),
            boiler_efficiency=self.equipment.boiler_efficiency,
            cop_at_7=self.equipment.cop_at_7,
        )

    def _zone_state(
        self,
        zone_id: str,
        schedule: str | None,
        windows: list[str],
        preheat_schedule: str | None = None,
        comfort: float | None = None,
    ) -> engine.ZoneState:
        override = self.override_of(zone_id)
        room = self.room_temperature(zone_id)
        preheat = self._preheat(zone_id, preheat_schedule or schedule, room, comfort)
        self.preheating[zone_id] = preheat
        detected = self._window_detected(zone_id)
        self.windows_detected[zone_id] = detected
        return engine.ZoneState(
            room_temp=room,
            schedule_on=self._schedule_on(schedule),
            window_open=self._windows_open(windows),
            window_detected=detected,
            preset=self.preset_of(zone_id),
            override_temp=override[0] if override else None,
            enabled=self.enabled.get(zone_id, True),
            preheat=preheat,
        )

    # ------------------------------------------------------------ smart start
    def heat_rate(self, zone_id: str) -> float:
        return self.heat_rates.get(zone_id) or self.heat_rates.get(HOUSE_ZONE_ID) or DEFAULT_HEAT_RATE

    def _preheat(
        self, zone_id: str, schedule: str | None, room: float | None, comfort: float | None
    ) -> bool:
        """Start comfort early so the room is warm when the schedule turns on."""
        if not self.config.get(CONF_PREHEAT, True) or comfort is None or room is None:
            return False
        zone = self._zone(zone_id) if zone_id != HOUSE_ZONE_ID else None
        if zone and zone.get(CONF_ZONE_ACS):
            # Air conditioners warm a room in minutes and are loud: never start one
            # early (e.g. in a bedroom at 4 in the morning), only at the schedule.
            return False
        state = self._state(schedule)
        if state is None or state.state != "off":
            return False
        next_event = state.attributes.get("next_event")
        if isinstance(next_event, str):
            next_event = dt_util.parse_datetime(next_event)
        if not isinstance(next_event, datetime):
            return False
        return preheat_due(
            dt_util.as_utc(next_event),
            dt_util.utcnow(),
            comfort - room,
            self.heat_rate(zone_id),
            float(self.config.get(CONF_PREHEAT_MAX, DEFAULT_PREHEAT_MAX)),
        )

    def _heat_driver(self, zone_id: str) -> str | None:
        """The device whose target drives the heating of a zone (for learning)."""
        if zone_id == HOUSE_ZONE_ID:
            return self.config.get(CONF_BOILER)
        zone = self._zone(zone_id) or {}
        devices = zone.get(CONF_ZONE_TRVS, []) + zone.get(CONF_ZONE_ACS, [])
        return devices[0] if devices else None

    @callback
    def _learn_heat(self, zone_id: str) -> None:
        """Measure how fast a zone warms up after its target is raised."""
        state = self._state(self._heat_driver(zone_id))
        room = self.room_temperature(zone_id)
        target = _float(state, ATTR_TEMPERATURE)
        active = (
            state is not None
            and state.state in ("heat", "heat_cool", "auto")
            and target is not None
            and room is not None
        )
        now = dt_util.utcnow()
        session = self._heat_sessions.get(zone_id)
        if session is None:
            if active and target - room >= 0.8:
                self._heat_sessions[zone_id] = (now, room, target)
            return
        started, start_temp, session_target = session
        hours = (now - started).total_seconds() / 3600
        if not active or target < session_target - 0.01 or hours > HEAT_SESSION_MAX_HOURS:
            self._heat_sessions.pop(zone_id, None)
            return
        if room >= session_target - 0.1:
            self._heat_sessions.pop(zone_id, None)
            rate = learn_rate(self.heat_rates.get(zone_id), room - start_temp, hours)
            if rate is not None:
                self.heat_rates[zone_id] = rate
                _LOGGER.info("HeatWise learned %s warms up %.2f °C/h", self.zone_name(zone_id), rate)
                self._save()

    def _arriving(self) -> bool:
        sensors = self.config.get(CONF_ARRIVAL_SENSORS, [])
        if not sensors:
            return False
        readings: dict[str, tuple[float | None, str | None]] = {}
        for eid in sensors:
            state = self._state(eid)
            if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                continue
            km = ArrivalWatcher.to_km(state.state, state.attributes.get("unit_of_measurement"))
            direction = self._state(ArrivalWatcher.direction_entity(eid))
            readings[eid] = (km, direction.state if direction is not None else None)
        return self.arrival.update(
            readings,
            float(self.config.get(CONF_ARRIVAL_KM, DEFAULT_ARRIVAL_KM)),
            self.anyone_home,
            dt_util.utcnow(),
        )

    # ----------------------------------------------------------- notifications
    async def notify(self, title: str, message: str) -> None:
        for target in self.config.get(CONF_NOTIFY, []):
            domain, _, service = target.partition(".")
            if not service:
                domain, service = "notify", target
            await self._call(domain, service, {"title": title, "message": message})

    @callback
    def _check_windows(self, states: dict[str, engine.ZoneState]) -> None:
        for zone_id, st in states.items():
            now_open = st.window_open or st.window_detected
            before = self._windows_seen.get(zone_id)
            self._windows_seen[zone_id] = now_open
            if before is False and now_open and self.config.get(CONF_NOTIFY_WINDOW, True):
                key = "window" if st.window_open else "window_drop"
                if self.control_enabled:
                    key += "_lowered"
                self.hass.async_create_task(
                    self.notify(
                        notify_text("window_title", self.language),
                        notify_text(key, self.language, zone=self.zone_name(zone_id)),
                    )
                )

    def _devices(self) -> list[str]:
        ids = [self.config[CONF_BOILER]] if self.config.get(CONF_BOILER) else []
        for zone in self.zones:
            ids += zone.get(CONF_ZONE_TRVS, []) + zone.get(CONF_ZONE_ACS, [])
        return ids

    async def _check_offline(self) -> None:
        if not self.config.get(CONF_NOTIFY_OFFLINE, True) or not self.config.get(CONF_NOTIFY):
            return
        now = dt_util.utcnow()
        lang = self.language
        for eid in self._devices():
            state = self._state(eid)
            name = state.name if state is not None else eid
            down = state is None or state.state == STATE_UNAVAILABLE
            if down and eid not in self._offline_notified:
                since = state.last_changed if state is not None else None
                if since is not None and now - since >= timedelta(minutes=OFFLINE_MINUTES):
                    self._offline_notified.add(eid)
                    await self.notify(
                        notify_text("offline_title", lang),
                        notify_text("offline", lang, device=name, minutes=OFFLINE_MINUTES),
                    )
            elif not down and eid in self._offline_notified:
                self._offline_notified.discard(eid)
                await self.notify(notify_text("offline_title", lang), notify_text("online", lang, device=name))

    async def _on_report_time(self, now: datetime) -> None:
        if dt_util.as_local(now).weekday() != REPORT_WEEKDAY:
            return
        await self.async_send_weekly_report()

    async def async_send_weekly_report(self) -> None:
        if not self.config.get(CONF_WEEKLY_REPORT, True) or not self.config.get(CONF_NOTIFY):
            return
        self._roll_periods()
        week = {m: self.period_value(m, "week") for m in self._empty_period()}
        text = weekly_report(
            week,
            self.last_week,
            self.language,
            self.hass.config.currency,
            self.has_power,
            self.has_ac_power,
            self.split_hot_water,
        )
        await self.notify(notify_text("report_title", self.language), text)

    # -------------------------------------------------------------- evaluation
    async def async_evaluate(self) -> None:
        self._roll_burner_day()
        c = self.config
        self.anyone_home = self._presence()
        arriving = self._arriving()
        house_temps = self._house_temps()
        house_cfg = engine.ZoneConfig(
            HOUSE_ZONE_ID, self.name, self._house_temps(), is_house=True
        )
        states = {
            HOUSE_ZONE_ID: self._zone_state(
                HOUSE_ZONE_ID,
                c.get(CONF_SCHEDULE),
                c.get(CONF_WINDOWS, []),
                comfort=house_temps.comfort,
            )
        }
        zone_cfgs: list[engine.ZoneConfig] = []
        for zone in self.zones:
            zid = zone[CONF_ZONE_ID]
            zone_cfgs.append(
                engine.ZoneConfig(
                    zid,
                    zone[CONF_ZONE_NAME],
                    self._zone_temps(zone),
                    has_ac=bool(zone.get(CONF_ZONE_ACS)),
                    has_trv=bool(zone.get(CONF_ZONE_TRVS)),
                    trv_follow_boiler=bool(zone.get(CONF_ZONE_FOLLOW_BOILER, False)),
                )
            )
            st = self._zone_state(
                zid,
                zone.get(CONF_SCHEDULE),
                zone.get(CONF_WINDOWS, []),
                preheat_schedule=zone.get(CONF_SCHEDULE) or c.get(CONF_SCHEDULE),
                comfort=self._zone_temps(zone).comfort,
            )
            st.ac_ours_running, st.ac_user_controlled = self._ac_flags(zone)
            states[zid] = st

        house = engine.HouseState(
            anyone_home=self.anyone_home,
            outdoor_temp=self._outdoor(),
            warm_off_threshold=(
                float(c[CONF_WARM_OFF]) if c.get(CONF_WARM_OFF) is not None else None
            ),
            previous_source=self.previous_source,
            previous_warm_off=self.previous_warm_off,
            arriving=arriving,
        )
        for zid in states:
            self._learn_heat(zid)
        self._check_windows(states)
        plan = engine.evaluate(house_cfg, zone_cfgs, states, house, self._hybrid())
        self.zone_states = states
        if plan.source != self.previous_source or plan.warm_off != self.previous_warm_off:
            _LOGGER.info(
                "HeatWise %s: source %s (%s), warm_off=%s",
                self.name, plan.source, plan.source_reason, plan.warm_off,
            )
            self.previous_source = plan.source
            self.previous_warm_off = plan.warm_off
            self._save()
        self.plan = plan
        if self.control_enabled:
            await self._apply(plan)
        async_dispatcher_send(self.hass, SIGNAL_UPDATE.format(self.entry.entry_id))

    # ------------------------------------------------------------------ output
    async def _apply(self, plan: engine.Plan) -> None:
        c = self.config
        if c.get(CONF_BOILER):
            await self._set_temperature(c[CONF_BOILER], plan.boiler_target, turn_on=False)
        for zone in self.zones:
            zp = plan.zones.get(zone[CONF_ZONE_ID])
            if zp is None:
                continue
            if zp.trv_target is not None:
                for trv in zone.get(CONF_ZONE_TRVS, []):
                    await self._set_temperature(trv, zp.trv_target, turn_on=True)
            for ac in zone.get(CONF_ZONE_ACS, []):
                await self._apply_ac(ac, zp)

    async def _apply_ac(self, entity_id: str, zp: engine.ZonePlan) -> None:
        state = self._state(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return
        if zp.ac_action == engine.AC_HEAT and zp.ac_setpoint is not None:
            if state.state != "off" and entity_id not in self.ac_owned:
                return  # a person is using it
            if entity_id in self.ac_blocked:
                return
            self.ac_owned.add(entity_id)
            await self._set_temperature(entity_id, zp.ac_setpoint, turn_on=True, hvac="heat")
            self._save()
        elif zp.ac_action == engine.AC_OFF and entity_id in self.ac_owned:
            if state.state != "off":
                self._last_sent[entity_id] = (0.0, dt_util.utcnow())
                await self._call("climate", "turn_off", {ATTR_ENTITY_ID: entity_id})
            self.ac_owned.discard(entity_id)
            self._save()

    async def _set_temperature(
        self, entity_id: str, temperature: float, turn_on: bool, hvac: str = "heat"
    ) -> None:
        state = self._state(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return
        attrs = state.attributes
        step = float(attrs.get("target_temp_step") or 0.5)
        low = float(attrs.get("min_temp", 5))
        high = float(attrs.get("max_temp", 35))
        value = round(round(temperature / step) * step, 2)
        value = min(max(value, low), high)

        if state.state == "off":
            if not turn_on:
                return
            if hvac in attrs.get("hvac_modes", []):
                self._last_sent[entity_id] = (value, dt_util.utcnow())
                await self._call("climate", "set_hvac_mode", {ATTR_ENTITY_ID: entity_id, "hvac_mode": hvac})
        elif hvac == "heat" and turn_on and state.state not in ("heat", "heat_cool") and "heat" in attrs.get("hvac_modes", []):
            self._last_sent[entity_id] = (value, dt_util.utcnow())
            await self._call("climate", "set_hvac_mode", {ATTR_ENTITY_ID: entity_id, "hvac_mode": "heat"})

        presets = attrs.get("preset_modes") or []
        if attrs.get("preset_mode") in SCHEDULE_PRESETS and "manual" in presets:
            self._last_sent[entity_id] = (value, dt_util.utcnow())
            await self._call("climate", "set_preset_mode", {ATTR_ENTITY_ID: entity_id, "preset_mode": "manual"})

        current = _float(state, ATTR_TEMPERATURE)
        if current is not None and abs(current - value) < step / 2:
            return
        self._last_sent[entity_id] = (value, dt_util.utcnow())
        await self._call(
            "climate", "set_temperature", {ATTR_ENTITY_ID: entity_id, ATTR_TEMPERATURE: value}
        )

    async def _call(self, domain: str, service: str, data: dict[str, Any]) -> None:
        try:
            await self.hass.services.async_call(domain, service, data, blocking=True)
        except Exception as err:  # noqa: BLE001 - one bad device must not stop the house
            _LOGGER.warning("HeatWise could not call %s.%s %s: %s", domain, service, data, err)

    # -------------------------------------------------------------- reporting
    def explanation(self, zone_id: str = HOUSE_ZONE_ID) -> str | None:
        if self.plan is None:
            return None
        lang = self.language
        if zone_id == HOUSE_ZONE_ID:
            text = engine.explain(self.plan.house_reason, lang)
            if self.has_ac:
                text += " · " + engine.explain(self.plan.source_reason, lang)
            if not self.control_enabled:
                text += " · " + ("doar observă" if lang.startswith("ro") else "observing only")
            return text
        zp = self.plan.zones.get(zone_id)
        return engine.explain(zp.reason, lang) if zp else None

    def diagnostics(self) -> dict[str, Any]:
        plan = self.plan
        return {
            "control_enabled": self.control_enabled,
            "use_ac": self.use_ac,
            "anyone_home": self.anyone_home,
            "presets": self.presets,
            "overrides": self.overrides,
            "ac_owned": sorted(self.ac_owned),
            "ac_blocked": self.ac_blocked,
            "burner_runtime_seconds": self.burner_runtime_seconds,
            "language": self.language,
            "heat_rates": self.heat_rates,
            "heat_sessions": {k: [v[0].isoformat(), v[1], v[2]] for k, v in self._heat_sessions.items()},
            "preheating": self.preheating,
            "arrival": {
                "until": self.arrival.until.isoformat() if self.arrival.until else None,
                "who": self.arrival.who,
                "farthest_km": self.arrival.farthest,
            },
            "last_week": self.last_week,
            "equipment": vars(self.equipment),
            "gas": {
                "rate": self.gas_rate,
                "rate_learned": self.gas_rate_learned,
                "calibrations": self.gas_calibrations,
                "baseline": self.gas_baseline,
                "today_m3": self.gas_today_live,
                "total_m3": self.gas_total_live,
                "by_power": self.gas_by_power,
                "burner_power": self.burner_power,
                "power_ref": self.power_ref,
                "load_hours_total": round(self.burner_load_live_seconds / 3600, 3),
                "last_manual_reading": self.last_manual_reading,
            },
            "hot_water": {
                "split": self.split_hot_water,
                "heat_demand": self.heat_demand,
                "demand_off_at": self._demand_off_at.isoformat() if self._demand_off_at else None,
            },
            "windows_detected": self.windows_detected,
            "plan": None
            if plan is None
            else {
                "source": plan.source,
                "source_reason": plan.source_reason,
                "warm_off": plan.warm_off,
                "boiler_target": plan.boiler_target,
                "house_reason": plan.house_reason,
                "cop": plan.cop,
                "cost_gas": plan.cost_gas,
                "cost_ac": plan.cost_ac,
                "zones": {k: vars(v) for k, v in plan.zones.items()},
            },
        }
