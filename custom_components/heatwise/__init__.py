"""HeatWise: smart, hybrid heating control for Home Assistant."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import CONF_ZONE_ID, DOMAIN, HOUSE_ZONE_ID, PLATFORMS
from .controller import HeatWiseController

type HeatWiseConfigEntry = ConfigEntry[HeatWiseController]


async def async_setup_entry(hass: HomeAssistant, entry: HeatWiseConfigEntry) -> bool:
    """Set up a HeatWise house."""
    controller = HeatWiseController(hass, entry)
    entry.runtime_data = controller
    _remove_stale_zone_devices(hass, entry, controller)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await controller.async_setup()
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HeatWiseConfigEntry) -> bool:
    """Unload a HeatWise house."""
    await entry.runtime_data.async_unload()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _remove_stale_zone_devices(
    hass: HomeAssistant, entry: ConfigEntry, controller: HeatWiseController
) -> None:
    """Drop the devices of zones that were removed in the options."""
    keep = {f"{entry.entry_id}_{HOUSE_ZONE_ID}"}
    keep |= {f"{entry.entry_id}_{z[CONF_ZONE_ID]}" for z in controller.zones}
    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        ids = {ident for domain, ident in device.identifiers if domain == DOMAIN}
        if ids and not ids & keep:
            registry.async_remove_device(device.id)


async def _async_reload(hass: HomeAssistant, entry: HeatWiseConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove stored state when the house is deleted."""
    from homeassistant.helpers.storage import Store

    from .const import STORAGE_VERSION

    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}").async_remove()
