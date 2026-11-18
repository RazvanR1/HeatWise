"""Config and options flow for HeatWise."""

from __future__ import annotations

import uuid
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from . import engine
from .const import (
    CONF_AC_ENERGY_CLASS,
    CONF_AC_HEAT_W,
    CONF_AC_INPUT_W,
    CONF_AC_MIN_OUTDOOR,
    CONF_AC_MODEL,
    CONF_AC_OFFSET,
    CONF_AC_THRESHOLD,
    CONF_ARRIVAL_KM,
    CONF_ARRIVAL_SENSORS,
    CONF_AWAY,
    CONF_AWAY_DELAY,
    CONF_BOILER,
    CONF_BOILER_EFFICIENCY_PCT,
    CONF_BOILER_MODEL,
    CONF_BOILER_POWER,
    CONF_BOILER_POWER_KW,
    CONF_BOILER_TYPE,
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
    CONF_GAS_RATE,
    CONF_HOUSE_SENSOR,
    CONF_HYBRID_MODE,
    CONF_LANGUAGE,
    CONF_NAME,
    CONF_NOTIFY,
    CONF_NOTIFY_WINDOW_TARGETS,
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
    DEFAULT_OVERRIDE_MINUTES,
    DEFAULT_PREHEAT_MAX,
    DEFAULT_WINDOW_DROP,
    DEFAULT_WINDOW_DROP_MINUTES,
    DEFAULT_WINDOW_HOLD,
    DOMAIN,
    LANG_AUTO,
    LANGUAGES,
)
from .controller import effective_config
from .equipment import (
    BOILER_CONDENSING,
    BOILER_CONVENTIONAL,
    BOILER_UNKNOWN,
    SCOP_BY_CLASS,
)


def _temp(min_v: float = 5, max_v: float = 30, step: float = 0.5) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(min=min_v, max=max_v, step=step, mode=selector.NumberSelectorMode.BOX)
    )


def _number(min_v: float, max_v: float, step: float | str) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(min=min_v, max=max_v, step=step, mode=selector.NumberSelectorMode.BOX)
    )


CLIMATE = selector.EntitySelector(selector.EntitySelectorConfig(domain="climate"))
CLIMATES = selector.EntitySelector(selector.EntitySelectorConfig(domain="climate", multiple=True))
TEMP_SENSOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
)
OUTDOOR = selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor", "weather"]))
PERSONS = selector.EntitySelector(selector.EntitySelectorConfig(domain="person", multiple=True))
SCHEDULE = selector.EntitySelector(
    selector.EntitySelectorConfig(domain=["schedule", "input_boolean", "binary_sensor"])
)
WINDOWS = selector.EntitySelector(selector.EntitySelectorConfig(domain="binary_sensor", multiple=True))
SENSOR = selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor", "input_number"]))
POWER = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", device_class="power"))
POWER_MULTI = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="sensor", device_class="power", multiple=True)
)
DISTANCES = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="sensor", device_class="distance", multiple=True)
)
GAS_METER = selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor", "input_number"]))


def _opt(key: str, values: dict[str, Any], default: Any = None) -> vol.Optional:
    """Optional field pre-filled with the current value (clearable)."""
    if key in values and values[key] not in (None, "", []):
        return vol.Optional(key, description={"suggested_value": values[key]})
    if default is not None:
        return vol.Optional(key, description={"suggested_value": default})
    return vol.Optional(key)


def _req(key: str, values: dict[str, Any], default: Any) -> vol.Required:
    return vol.Required(key, default=values.get(key, default))


def house_schema(values: dict[str, Any], with_name: bool) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if with_name:
        fields[_req(CONF_NAME, values, "Home")] = selector.TextSelector()
    fields.update(
        {
            _opt(CONF_BOILER, values): CLIMATE,
            _opt(CONF_HOUSE_SENSOR, values): TEMP_SENSOR,
            _opt(CONF_OUTDOOR, values): OUTDOOR,
            _opt(CONF_PERSONS, values): PERSONS,
            _opt(CONF_SCHEDULE, values): SCHEDULE,
            _opt(CONF_WINDOWS, values): WINDOWS,
            _req(CONF_COMFORT, values, DEFAULT_COMFORT): _temp(),
            _req(CONF_ECO, values, DEFAULT_ECO): _temp(),
            _req(CONF_AWAY, values, DEFAULT_AWAY): _temp(),
            _req(CONF_FROST, values, DEFAULT_FROST): _temp(3, 12),
        }
    )
    if not with_name:
        fields.update(
            {
                _opt(CONF_WARM_OFF, values): _temp(10, 30),
                _req(CONF_AWAY_DELAY, values, DEFAULT_AWAY_DELAY): _number(0, 240, 1),
                _req(CONF_OVERRIDE_MINUTES, values, DEFAULT_OVERRIDE_MINUTES): _number(10, 1440, 5),
                vol.Required(
                    CONF_WINDOW_DETECT, default=values.get(CONF_WINDOW_DETECT, True)
                ): selector.BooleanSelector(),
                _req(CONF_WINDOW_DROP, values, DEFAULT_WINDOW_DROP): _number(0.3, 3, 0.1),
                _req(CONF_WINDOW_DROP_MINUTES, values, DEFAULT_WINDOW_DROP_MINUTES): _number(2, 30, 1),
                _req(CONF_WINDOW_HOLD, values, DEFAULT_WINDOW_HOLD): _number(5, 120, 5),
            }
        )
    fields[_req(CONF_LANGUAGE, values, LANG_AUTO)] = selector.SelectSelector(
        selector.SelectSelectorConfig(options=list(LANGUAGES), translation_key="language")
    )
    return vol.Schema(fields)


def hybrid_schema(values: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            _req(CONF_HYBRID_MODE, values, engine.HYBRID_AUTO): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[engine.HYBRID_AUTO, engine.HYBRID_BOILER, engine.HYBRID_AC],
                    translation_key="hybrid_mode",
                )
            ),
            _req(CONF_AC_THRESHOLD, values, DEFAULT_AC_THRESHOLD): _temp(-20, 25),
            _req(CONF_AC_MIN_OUTDOOR, values, DEFAULT_AC_MIN_OUTDOOR): _temp(-30, 10),
            _req(CONF_AC_OFFSET, values, DEFAULT_AC_OFFSET): _number(0, 6, 0.5),
            _opt(CONF_GAS_PRICE_ENTITY, values): SENSOR,
            _opt(CONF_GAS_PRICE, values): _number(0, 100, "any"),
            _opt(CONF_EL_PRICE_ENTITY, values): SENSOR,
            _opt(CONF_EL_PRICE, values): _number(0, 100, "any"),
        }
    )


def power_schema(values: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            _opt(CONF_BOILER_POWER, values): POWER,
            _req(CONF_BURNER_THRESHOLD, values, DEFAULT_BURNER_THRESHOLD): _number(1, 2000, 1),
            _opt(CONF_GAS_METER, values): GAS_METER,
            _opt(CONF_GAS_RATE, values): _number(0.2, 6, 0.01),
            _req(CONF_GAS_KWH_PER_M3, values, DEFAULT_GAS_KWH_PER_M3): _number(8, 12, 0.01),
            vol.Required(
                CONF_GAS_BY_POWER, default=values.get(CONF_GAS_BY_POWER, True)
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_SPLIT_HOT_WATER, default=values.get(CONF_SPLIT_HOT_WATER, True)
            ): selector.BooleanSelector(),
        }
    )


def equipment_schema(values: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            _opt(CONF_BOILER_MODEL, values): selector.TextSelector(),
            _req(CONF_BOILER_TYPE, values, BOILER_UNKNOWN): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[BOILER_CONDENSING, BOILER_CONVENTIONAL, BOILER_UNKNOWN],
                    translation_key="boiler_type",
                )
            ),
            _opt(CONF_BOILER_POWER_KW, values): _number(1, 100, 0.1),
            _opt(CONF_BOILER_EFFICIENCY_PCT, values): _number(60, 115, 0.1),
            _opt(CONF_AC_MODEL, values): selector.TextSelector(),
            _opt(CONF_AC_HEAT_W, values): _number(300, 30000, 1),
            _opt(CONF_AC_INPUT_W, values): _number(100, 10000, 1),
            _req(CONF_AC_ENERGY_CLASS, values, "unknown"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[*SCOP_BY_CLASS, "unknown"],
                    translation_key="ac_energy_class",
                )
            ),
        }
    )


def smart_schema(values: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_PREHEAT, default=values.get(CONF_PREHEAT, True)): selector.BooleanSelector(),
            _req(CONF_PREHEAT_MAX, values, DEFAULT_PREHEAT_MAX): _number(15, 360, 5),
            _opt(CONF_ARRIVAL_SENSORS, values): DISTANCES,
            _req(CONF_ARRIVAL_KM, values, DEFAULT_ARRIVAL_KM): _number(1, 200, 0.5),
        }
    )


def notify_schema(values: dict[str, Any], services: list[str]) -> vol.Schema:
    options = sorted(
        set(services) | set(values.get(CONF_NOTIFY, [])) | set(values.get(CONF_NOTIFY_WINDOW_TARGETS, []))
    )
    targets = selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options, multiple=True, custom_value=True,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )
    return vol.Schema(
        {
            _opt(CONF_NOTIFY, values): targets,
            _opt(CONF_NOTIFY_WINDOW_TARGETS, values): targets,
            vol.Required(CONF_NOTIFY_WINDOW, default=values.get(CONF_NOTIFY_WINDOW, True)): selector.BooleanSelector(),
            vol.Required(CONF_NOTIFY_OFFLINE, default=values.get(CONF_NOTIFY_OFFLINE, True)): selector.BooleanSelector(),
            vol.Required(CONF_WEEKLY_REPORT, default=values.get(CONF_WEEKLY_REPORT, True)): selector.BooleanSelector(),
        }
    )


def zone_schema(values: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_ZONE_NAME, default=values.get(CONF_ZONE_NAME, "")): selector.TextSelector(),
            _opt(CONF_ZONE_SENSOR, values): TEMP_SENSOR,
            _opt(CONF_ZONE_TRVS, values): CLIMATES,
            _opt(CONF_ZONE_ACS, values): CLIMATES,
            _opt(CONF_ZONE_AC_POWER, values): POWER_MULTI,
            _opt(CONF_WINDOWS, values): WINDOWS,
            _opt(CONF_SCHEDULE, values): SCHEDULE,
            _opt(CONF_COMFORT, values): _temp(),
            _opt(CONF_ECO, values): _temp(),
            _opt(CONF_AWAY, values): _temp(),
            vol.Required(
                CONF_ZONE_FOLLOW_BOILER, default=values.get(CONF_ZONE_FOLLOW_BOILER, False)
            ): selector.BooleanSelector(),
        }
    )


def _merge(current: dict[str, Any], schema: vol.Schema, user_input: dict[str, Any]) -> dict[str, Any]:
    """Apply a form: keys of the form missing from the input were cleared."""
    result = dict(current)
    for marker in schema.schema:
        key = str(marker)
        if key in user_input and (user_input[key] is False or user_input[key] not in (None, "", [])):
            result[key] = user_input[key]
        else:
            result.pop(key, None)
    return result


class HeatWiseConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create a HeatWise house."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        schema = house_schema(user_input or {}, with_name=True)
        if user_input is not None:
            self._data = _merge({}, schema, user_input)
            return await self.async_step_equipment()
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_equipment(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Boiler and AC from the datasheet; everything may stay empty."""
        schema = equipment_schema(self._data)
        if user_input is not None:
            data = _merge(self._data, schema, user_input)
            return self.async_create_entry(title=data[CONF_NAME], data=data)
        return self.async_show_form(step_id="equipment", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return HeatWiseOptionsFlow()


class HeatWiseOptionsFlow(OptionsFlow):
    """Change the house, the hybrid rules and the zones."""

    def __init__(self) -> None:
        self._zone_id: str | None = None

    @property
    def _values(self) -> dict[str, Any]:
        return effective_config(self.config_entry)

    def _save(self, values: dict[str, Any]) -> ConfigFlowResult:
        values = dict(values)
        values.pop(CONF_NAME, None)
        return self.async_create_entry(data=values)

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        menu = ["house", "equipment", "hybrid", "power", "smart", "notify", "add_zone"]
        if self._values.get(CONF_ZONES):
            menu += ["edit_zone", "remove_zone"]
        return self.async_show_menu(step_id="init", menu_options=menu)

    async def async_step_house(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        schema = house_schema(self._values, with_name=False)
        if user_input is not None:
            return self._save(_merge(self._values, schema, user_input))
        return self.async_show_form(step_id="house", data_schema=schema)

    async def async_step_equipment(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        schema = equipment_schema(self._values)
        if user_input is not None:
            return self._save(_merge(self._values, schema, user_input))
        return self.async_show_form(step_id="equipment", data_schema=schema)

    async def async_step_hybrid(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        schema = hybrid_schema(self._values)
        if user_input is not None:
            return self._save(_merge(self._values, schema, user_input))
        return self.async_show_form(step_id="hybrid", data_schema=schema)

    async def async_step_power(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        schema = power_schema(self._values)
        if user_input is not None:
            return self._save(_merge(self._values, schema, user_input))
        return self.async_show_form(step_id="power", data_schema=schema)

    async def async_step_smart(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        schema = smart_schema(self._values)
        if user_input is not None:
            return self._save(_merge(self._values, schema, user_input))
        return self.async_show_form(step_id="smart", data_schema=schema)

    async def async_step_notify(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        services = [f"notify.{name}" for name in self.hass.services.async_services().get("notify", {})]
        schema = notify_schema(self._values, services)
        if user_input is not None:
            return self._save(_merge(self._values, schema, user_input))
        return self.async_show_form(step_id="notify", data_schema=schema)

    def _zones(self) -> list[dict[str, Any]]:
        return [dict(z) for z in self._values.get(CONF_ZONES, [])]

    async def _zone_form(
        self, step_id: str, current: dict[str, Any], user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        schema = zone_schema(user_input or current)
        errors: dict[str, str] = {}
        if user_input is not None:
            zone = _merge({CONF_ZONE_ID: current.get(CONF_ZONE_ID) or uuid.uuid4().hex[:8]}, schema, user_input)
            if not zone.get(CONF_ZONE_TRVS) and not zone.get(CONF_ZONE_ACS):
                errors["base"] = "zone_needs_device"
            else:
                zones = [z for z in self._zones() if z[CONF_ZONE_ID] != zone[CONF_ZONE_ID]]
                zones.append(zone)
                return self._save({**self._values, CONF_ZONES: zones})
        return self.async_show_form(step_id=step_id, data_schema=schema, errors=errors)

    async def async_step_add_zone(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._zone_form("add_zone", {}, user_input)

    def _zone_picker(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(CONF_ZONE_ID): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=z[CONF_ZONE_ID], label=z[CONF_ZONE_NAME])
                            for z in self._zones()
                        ]
                    )
                )
            }
        )

    async def async_step_edit_zone(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._zone_id = user_input[CONF_ZONE_ID]
            return await self.async_step_zone()
        return self.async_show_form(step_id="edit_zone", data_schema=self._zone_picker())

    async def async_step_zone(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        current = next((z for z in self._zones() if z[CONF_ZONE_ID] == self._zone_id), {})
        return await self._zone_form("zone", current, user_input)

    async def async_step_remove_zone(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            zones = [z for z in self._zones() if z[CONF_ZONE_ID] != user_input[CONF_ZONE_ID]]
            return self._save({**self._values, CONF_ZONES: zones})
        return self.async_show_form(step_id="remove_zone", data_schema=self._zone_picker())
