"""HeatWise sidebar panel and its websocket API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_integration

from .const import (
    CONF_OUTDOOR,
    CONF_ZONE_ACS,
    CONF_ZONE_ID,
    CONF_ZONE_TRVS,
    DOMAIN,
    HOUSE_ZONE_ID,
)

PANEL_URL = "heatwise"
STATIC_URL = "/heatwise_static"
_DATA_STATIC = f"{DOMAIN}_static_registered"
_DATA_WS = f"{DOMAIN}_ws_registered"
_DATA_PANEL = f"{DOMAIN}_panel_registered"


async def async_setup_panel(hass: HomeAssistant) -> None:
    """Register the static files, the websocket command and the sidebar panel once."""
    if not hass.data.get(_DATA_STATIC):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL, str(Path(__file__).parent / "frontend"), False)]
        )
        hass.data[_DATA_STATIC] = True
    if not hass.data.get(_DATA_WS):
        websocket_api.async_register_command(hass, ws_status)
        hass.data[_DATA_WS] = True
    if hass.data.get(_DATA_PANEL):
        return
    version = (await async_get_integration(hass, DOMAIN)).version
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL,
        webcomponent_name="heatwise-panel",
        sidebar_title="HeatWise",
        sidebar_icon="mdi:radiator",
        module_url=f"{STATIC_URL}/heatwise-panel.js?v={version}",
        require_admin=False,
        config={},
    )
    hass.data[_DATA_PANEL] = True


@callback
def async_remove_panel_if_unused(hass: HomeAssistant, unloading_entry_id: str) -> None:
    """Remove the sidebar panel when the last HeatWise house is unloaded."""
    others = [
        e for e in hass.config_entries.async_loaded_entries(DOMAIN)
        if e.entry_id != unloading_entry_id
    ]
    if not others and hass.data.pop(_DATA_PANEL, False):
        frontend.async_remove_panel(hass, PANEL_URL, warn_if_unknown=False)


def _entity(reg: er.EntityRegistry, domain: str, unique_id: str) -> str | None:
    return reg.async_get_entity_id(domain, DOMAIN, unique_id)


def _house_status(hass: HomeAssistant, entry) -> dict[str, Any]:
    controller = entry.runtime_data
    reg = er.async_get(hass)
    eid = entry.entry_id
    zones = [
        {
            "zone_id": HOUSE_ZONE_ID,
            "name": controller.name,
            "kind": "house",
            "climate": _entity(reg, "climate", f"{eid}_{HOUSE_ZONE_ID}_climate"),
        }
    ]
    for zone in controller.zones:
        has_ac = bool(zone.get(CONF_ZONE_ACS))
        has_trv = bool(zone.get(CONF_ZONE_TRVS))
        zones.append(
            {
                "zone_id": zone[CONF_ZONE_ID],
                "name": controller.zone_name(zone[CONF_ZONE_ID]),
                "kind": "mixed" if has_ac and has_trv else ("ac" if has_ac else "trv"),
                "climate": _entity(reg, "climate", f"{eid}_{zone[CONF_ZONE_ID]}_climate"),
            }
        )
    plan = controller.plan
    return {
        "entry_id": eid,
        "name": controller.name,
        "has_ac": controller.has_ac,
        "has_power": controller.has_power,
        "outdoor": controller.config.get(CONF_OUTDOOR),
        "entities": {
            "control": _entity(reg, "switch", f"{eid}_{HOUSE_ZONE_ID}_control"),
            "use_ac": _entity(reg, "switch", f"{eid}_{HOUSE_ZONE_ID}_use_ac"),
            "decision": _entity(reg, "sensor", f"{eid}_{HOUSE_ZONE_ID}_decision"),
            "boiler_target": _entity(reg, "sensor", f"{eid}_{HOUSE_ZONE_ID}_boiler_target"),
            "heat_source": _entity(reg, "sensor", f"{eid}_{HOUSE_ZONE_ID}_heat_source"),
            "burner_runtime": _entity(reg, "sensor", f"{eid}_{HOUSE_ZONE_ID}_burner_runtime"),
            "burner_running": _entity(reg, "binary_sensor", f"{eid}_{HOUSE_ZONE_ID}_burner_running"),
            "anyone_home": _entity(reg, "binary_sensor", f"{eid}_{HOUSE_ZONE_ID}_anyone_home"),
            "gas_today": _entity(reg, "sensor", f"{eid}_{HOUSE_ZONE_ID}_gas_today"),
            "gas_cost_today": _entity(reg, "sensor", f"{eid}_{HOUSE_ZONE_ID}_gas_cost_today"),
        },
        "zones": zones,
        "source_text": controller.explanation() if plan else None,
    }


@websocket_api.websocket_command({vol.Required("type"): "heatwise/status"})
@callback
def ws_status(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Describe every loaded HeatWise house for the panel."""
    houses = [
        _house_status(hass, entry)
        for entry in hass.config_entries.async_loaded_entries(DOMAIN)
        if getattr(entry, "runtime_data", None) is not None
    ]
    connection.send_result(msg["id"], {"houses": houses})
