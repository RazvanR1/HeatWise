"""HeatWise binary sensors."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HeatWiseConfigEntry
from .const import CONF_PERSONS, HOUSE_ZONE_ID
from .entity import HeatWiseEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: HeatWiseConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    controller = entry.runtime_data
    entities: list[BinarySensorEntity] = []
    if controller.has_power:
        entities.append(BurnerRunningSensor(controller))
    if controller.config.get(CONF_PERSONS):
        entities.append(AnyoneHomeSensor(controller))
    async_add_entities(entities)


class BurnerRunningSensor(HeatWiseEntity, BinarySensorEntity):
    """On while the boiler burns gas (power above the threshold)."""

    _attr_translation_key = "burner_running"
    _attr_device_class = BinarySensorDeviceClass.HEAT

    def __init__(self, controller) -> None:
        super().__init__(controller, HOUSE_ZONE_ID, "burner_running")

    @property
    def is_on(self) -> bool:
        return self.controller.burner_running


class AnyoneHomeSensor(HeatWiseEntity, BinarySensorEntity):
    """Presence as HeatWise sees it (after the away delay)."""

    _attr_translation_key = "anyone_home"
    _attr_device_class = BinarySensorDeviceClass.PRESENCE

    def __init__(self, controller) -> None:
        super().__init__(controller, HOUSE_ZONE_ID, "anyone_home")

    @property
    def is_on(self) -> bool | None:
        return self.controller.anyone_home
