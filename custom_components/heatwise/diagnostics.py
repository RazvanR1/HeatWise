"""Diagnostics for HeatWise."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import HeatWiseConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HeatWiseConfigEntry
) -> dict[str, Any]:
    controller = entry.runtime_data
    return {"config": controller.config, "state": controller.diagnostics()}
