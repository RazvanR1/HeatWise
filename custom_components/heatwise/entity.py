"""Base entity for HeatWise."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, HOUSE_ZONE_ID, SIGNAL_UPDATE
from .controller import HeatWiseController


class HeatWiseEntity(Entity):
    """Common bits: device, updates from the controller."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, controller: HeatWiseController, zone_id: str, key: str) -> None:
        self.controller = controller
        self.zone_id = zone_id
        entry_id = controller.entry.entry_id
        self._attr_unique_id = f"{entry_id}_{zone_id}_{key}"
        if zone_id == HOUSE_ZONE_ID:
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, f"{entry_id}_{HOUSE_ZONE_ID}")},
                name=f"HeatWise {controller.name}",
                manufacturer="HeatWise",
                model="House",
            )
        else:
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, f"{entry_id}_{zone_id}")},
                name=f"HeatWise {controller.zone_name(zone_id)}",
                manufacturer="HeatWise",
                model="Zone",
                via_device=(DOMAIN, f"{entry_id}_{HOUSE_ZONE_ID}"),
            )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_UPDATE.format(self.controller.entry.entry_id),
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
