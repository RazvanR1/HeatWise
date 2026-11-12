"""HeatWise controller: reads Home Assistant, runs the engine, drives devices."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import engine
from .const import (
    CONF_AC_MIN_OUTDOOR,
    CONF_AC_OFFSET,
    CONF_AC_THRESHOLD,
    CONF_AWAY,
    CONF_AWAY_DELAY,
    CONF_BOILER,
    CONF_BOILER_EFFICIENCY,
    CONF_BOILER_POWER,
    CONF_BURNER_THRESHOLD,
    CONF_COMFORT,
    CONF_COP_AT_7,
    CONF_ECO,
    CONF_EL_PRICE,
    CONF_EL_PRICE_ENTITY,
    CONF_FROST,
    CONF_GAS_PRICE,
    CONF_GAS_PRICE_ENTITY,
    CONF_HOUSE_SENSOR,
    CONF_HYBRID_MODE,
    CONF_NAME,
    CONF_OUTDOOR,
    CONF_OVERRIDE_MINUTES,
    CONF_PERSONS,
    CONF_SCHEDULE,
    CONF_WARM_OFF,
    CONF_WINDOWS,
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
    DEFAULT_AWAY,
    DEFAULT_AWAY_DELAY,
    DEFAULT_BOILER_EFFICIENCY,
    DEFAULT_BURNER_THRESHOLD,
    DEFAULT_COMFORT,
    DEFAULT_COP_AT_7,
    DEFAULT_ECO,
    DEFAULT_FROST,
    DEFAULT_OVERRIDE_MINUTES,
    DOMAIN,
    EVAL_INTERVAL_SECONDS,
    HOUSE_ZONE_ID,
    OWN_COMMAND_GRACE_SECONDS,
    SIGNAL_UPDATE,
    STORAGE_VERSION,
    WINDOW_DELAY_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

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
        self.anyone_home: bool | None = None
        self._nobody_since: datetime | None = None
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
    def language(self) -> str:
        return self.hass.config.language or "en"

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
        if burner.get("day") == self.burner_day:
            self.burner_seconds = float(burner.get("seconds", 0))

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
        if self.has_power:
            power = _float(self.hass.states.get(self.config[CONF_BOILER_POWER]))
            if power is not None and power > self._burner_threshold:
                self.burner_on_since = dt_util.utcnow()
        self.async_schedule_evaluate(delay=5)

    async def async_unload(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._debounce_unsub:
            self._debounce_unsub()
            self._debounce_unsub = None
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
            "burner": {"day": self.burner_day, "seconds": self.burner_runtime_seconds},
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
        ):
            if c.get(key):
                ids.append(c[key])
        ids.extend(c.get(CONF_PERSONS, []))
        ids.extend(c.get(CONF_WINDOWS, []))
        for zone in self.zones:
            for key in (CONF_ZONE_SENSOR, CONF_SCHEDULE):
                if zone.get(key):
                    ids.append(zone[key])
            for key in (CONF_ZONE_TRVS, CONF_ZONE_ACS, CONF_WINDOWS):
                ids.extend(zone.get(key, []))
        return sorted(set(ids))

    # ------------------------------------------------------------------ events
    @callback
    def _on_interval(self, _now: datetime) -> None:
        self.async_schedule_evaluate(delay=0)

    @callback
    def _on_state_change(self, event: Event) -> None:
        entity_id: str = event.data["entity_id"]
        old: State | None = event.data.get("old_state")
        new: State | None = event.data.get("new_state")
        c = self.config
        if entity_id == c.get(CONF_BOILER_POWER):
            self._track_burner(new)
        elif entity_id == c.get(CONF_BOILER):
            self._detect_manual(HOUSE_ZONE_ID, entity_id, old, new)
        elif entity_id == c.get(CONF_SCHEDULE):
            if old is not None and new is not None and old.state != new.state:
                self._schedule_changed(None)
        for zone in self.zones:
            zid = zone[CONF_ZONE_ID]
            if entity_id in zone.get(CONF_ZONE_TRVS, []):
                self._detect_manual(zid, entity_id, old, new)
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

    @callback
    def _roll_burner_day(self) -> None:
        today = dt_util.now().date().isoformat()
        if today == self.burner_day:
            return
        if self.burner_on_since is not None:
            self.burner_on_since = dt_util.utcnow()
        self.burner_day = today
        self.burner_seconds = 0.0

    @callback
    def _track_burner(self, new: State | None) -> None:
        self._roll_burner_day()
        power = _float(new)
        running = power is not None and power > self._burner_threshold
        now = dt_util.utcnow()
        if running and self.burner_on_since is None:
            self.burner_on_since = now
        elif not running and self.burner_on_since is not None:
            self.burner_seconds += (now - self.burner_on_since).total_seconds()
            self.burner_on_since = None
            self._save()

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
            self._nobody_since = None
            return True
        now = dt_util.utcnow()
        if self._nobody_since is None:
            self._nobody_since = max(s.last_changed for s in known)
        delay = timedelta(minutes=int(self.config.get(CONF_AWAY_DELAY, DEFAULT_AWAY_DELAY)))
        return False if now - self._nobody_since >= delay else True

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
            boiler_efficiency=float(c.get(CONF_BOILER_EFFICIENCY, DEFAULT_BOILER_EFFICIENCY)),
            cop_at_7=float(c.get(CONF_COP_AT_7, DEFAULT_COP_AT_7)),
        )

    def _zone_state(self, zone_id: str, schedule: str | None, windows: list[str]) -> engine.ZoneState:
        override = self.override_of(zone_id)
        return engine.ZoneState(
            room_temp=self.room_temperature(zone_id),
            schedule_on=self._schedule_on(schedule),
            window_open=self._windows_open(windows),
            preset=self.preset_of(zone_id),
            override_temp=override[0] if override else None,
            enabled=self.enabled.get(zone_id, True),
        )

    # -------------------------------------------------------------- evaluation
    async def async_evaluate(self) -> None:
        self._roll_burner_day()
        c = self.config
        self.anyone_home = self._presence()
        house_cfg = engine.ZoneConfig(
            HOUSE_ZONE_ID, self.name, self._house_temps(), is_house=True
        )
        states = {
            HOUSE_ZONE_ID: self._zone_state(
                HOUSE_ZONE_ID, c.get(CONF_SCHEDULE), c.get(CONF_WINDOWS, [])
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
            st = self._zone_state(zid, zone.get(CONF_SCHEDULE), zone.get(CONF_WINDOWS, []))
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
        )
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
