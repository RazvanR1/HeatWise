"""HeatWise switches."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HeatWiseConfigEntry
from .const import HOUSE_ZONE_ID
from .entity import HeatWiseEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: HeatWiseConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    controller = entry.runtime_data
    entities: list[SwitchEntity] = [ControlSwitch(controller)]
    if controller.has_ac:
        entities.append(UseAcSwitch(controller))
    async_add_entities(entities)


class ControlSwitch(HeatWiseEntity, SwitchEntity):
    """Off = HeatWise only observes and shows what it would do."""

    _attr_translation_key = "control"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:robot"

    def __init__(self, controller) -> None:
        super().__init__(controller, HOUSE_ZONE_ID, "control")

    @property
    def is_on(self) -> bool:
        return self.controller.control_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.controller.set_control(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.controller.set_control(False)
        self.async_write_ha_state()


class UseAcSwitch(HeatWiseEntity, SwitchEntity):
    """Allow HeatWise to heat with the air conditioners."""

    _attr_translation_key = "use_ac"
    _attr_icon = "mdi:air-conditioner"

    def __init__(self, controller) -> None:
        super().__init__(controller, HOUSE_ZONE_ID, "use_ac")

    @property
    def is_on(self) -> bool:
        return self.controller.use_ac

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.controller.set_use_ac(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.controller.set_use_ac(False)
        self.async_write_ha_state()
