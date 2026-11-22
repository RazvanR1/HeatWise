"""HeatWise buttons."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HeatWiseConfigEntry
from .const import CONF_NOTIFY, HOUSE_ZONE_ID
from .entity import HeatWiseEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: HeatWiseConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    controller = entry.runtime_data
    if controller.config.get(CONF_NOTIFY):
        async_add_entities([SendReportButton(controller)])


class SendReportButton(HeatWiseEntity, ButtonEntity):
    """Send the weekly report now, without waiting for Sunday."""

    _attr_translation_key = "send_report"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:email-fast-outline"

    def __init__(self, controller) -> None:
        super().__init__(controller, HOUSE_ZONE_ID, "send_report")

    async def async_press(self) -> None:
        await self.controller.async_send_weekly_report(force=True)
