"""HeatWise climate entities: one for the house, one per zone."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HeatWiseConfigEntry, engine
from .const import CONF_BOILER, CONF_ZONE_ACS, CONF_ZONE_ID, CONF_ZONE_TRVS, HOUSE_ZONE_ID
from .entity import HeatWiseEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: HeatWiseConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    controller = entry.runtime_data
    entities = [HeatWiseClimate(controller, HOUSE_ZONE_ID)]
    entities += [HeatWiseClimate(controller, z[CONF_ZONE_ID]) for z in controller.zones]
    async_add_entities(entities)


class HeatWiseClimate(HeatWiseEntity, ClimateEntity):
    """Virtual thermostat that HeatWise drives the real devices from."""

    _attr_translation_key = "heatwise"
    _attr_name = None
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_preset_modes = engine.PRESETS
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_target_temperature_step = 0.5
    _attr_min_temp = 5
    _attr_max_temp = 30

    def __init__(self, controller, zone_id: str) -> None:
        super().__init__(controller, zone_id, "climate")
        self._attr_temperature_unit = controller.hass.config.units.temperature_unit or UnitOfTemperature.CELSIUS

    @property
    def current_temperature(self) -> float | None:
        return self.controller.room_temperature(self.zone_id)

    @property
    def target_temperature(self) -> float | None:
        plan = self.controller.plan
        if plan is None:
            return None
        if self.zone_id == HOUSE_ZONE_ID:
            state = self.controller.zone_states.get(HOUSE_ZONE_ID)
            if state is not None and state.override_temp is not None:
                return state.override_temp
            return plan.boiler_target
        zp = plan.zones.get(self.zone_id)
        return zp.target if zp else None

    @property
    def hvac_mode(self) -> HVACMode:
        return HVACMode.HEAT if self.controller.enabled.get(self.zone_id, True) else HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction | None:
        if self.hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        hass = self.hass
        devices: list[str] = []
        if self.zone_id == HOUSE_ZONE_ID:
            if self.controller.has_power:
                return HVACAction.HEATING if self.controller.burner_running else HVACAction.IDLE
            if self.controller.config.get(CONF_BOILER):
                devices = [self.controller.config[CONF_BOILER]]
        else:
            zone = next(
                (z for z in self.controller.zones if z[CONF_ZONE_ID] == self.zone_id), {}
            )
            devices = zone.get(CONF_ZONE_TRVS, []) + zone.get(CONF_ZONE_ACS, [])
        for eid in devices:
            state = hass.states.get(eid)
            if state is not None and state.attributes.get("hvac_action") == HVACAction.HEATING:
                return HVACAction.HEATING
        return HVACAction.IDLE

    @property
    def preset_mode(self) -> str | None:
        return self.controller.preset_of(self.zone_id)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self.controller
        attrs: dict[str, Any] = {"explanation": c.explanation(self.zone_id)}
        plan = c.plan
        if plan is not None:
            if self.zone_id == HOUSE_ZONE_ID:
                attrs["reason"] = plan.house_reason
                attrs["heat_source"] = plan.source
                attrs["boiler_target"] = plan.boiler_target
            else:
                zp = plan.zones.get(self.zone_id)
                if zp is not None:
                    attrs["reason"] = zp.reason
                    attrs["demand"] = zp.demand
                    attrs["valve_target"] = zp.trv_target
                    attrs["ac_action"] = zp.ac_action
        override = c.override_of(self.zone_id)
        if override:
            attrs["manual_until"] = override[1]
        return attrs

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is not None:
            self.controller.set_override(self.zone_id, float(temperature))

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        self.controller.set_preset(self.zone_id, preset_mode)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        self.controller.set_enabled(self.zone_id, hvac_mode != HVACMode.OFF)
