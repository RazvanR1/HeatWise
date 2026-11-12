"""Config and options flow for HeatWise."""

from __future__ import annotations

from typing import Any
import uuid

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from . import engine
from .controller import effective_config
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
            }
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
            _req(CONF_BOILER_EFFICIENCY, values, DEFAULT_BOILER_EFFICIENCY): _number(0.5, 1.1, 0.01),
            _req(CONF_COP_AT_7, values, DEFAULT_COP_AT_7): _number(1.5, 7, 0.1),
        }
    )


def power_schema(values: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            _opt(CONF_BOILER_POWER, values): POWER,
            _req(CONF_BURNER_THRESHOLD, values, DEFAULT_BURNER_THRESHOLD): _number(1, 2000, 1),
        }
    )


def zone_schema(values: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_ZONE_NAME, default=values.get(CONF_ZONE_NAME, "")): selector.TextSelector(),
            _opt(CONF_ZONE_SENSOR, values): TEMP_SENSOR,
            _opt(CONF_ZONE_TRVS, values): CLIMATES,
            _opt(CONF_ZONE_ACS, values): CLIMATES,
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
        if key in user_input and user_input[key] not in (None, "", []):
            result[key] = user_input[key]
        else:
            result.pop(key, None)
    return result


class HeatWiseConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create a HeatWise house."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        schema = house_schema(user_input or {}, with_name=True)
        if user_input is not None:
            data = _merge({}, schema, user_input)
            return self.async_create_entry(title=data[CONF_NAME], data=data)
        return self.async_show_form(step_id="user", data_schema=schema)

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
        menu = ["house", "hybrid", "power", "add_zone"]
        if self._values.get(CONF_ZONES):
            menu += ["edit_zone", "remove_zone"]
        return self.async_show_menu(step_id="init", menu_options=menu)

    async def async_step_house(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        schema = house_schema(self._values, with_name=False)
        if user_input is not None:
            return self._save(_merge(self._values, schema, user_input))
        return self.async_show_form(step_id="house", data_schema=schema)

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
