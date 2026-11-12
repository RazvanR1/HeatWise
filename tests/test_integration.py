"""End to end tests with a real Home Assistant instance."""

from datetime import timedelta

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.heatwise.const import DOMAIN

BOILER = "climate.boiler"
TRV = "climate.kitchen_trv"
AC = "climate.living_ac"


def _thermostat(hass, entity_id, temp, current, state="heat", preset=None, step=0.5):
    attrs = {
        "temperature": temp,
        "current_temperature": current,
        "min_temp": 5,
        "max_temp": 30,
        "target_temp_step": step,
        "hvac_modes": ["off", "heat"],
    }
    if preset:
        attrs["preset_modes"] = ["manual", "eco", "program"]
        attrs["preset_mode"] = preset
    hass.states.async_set(entity_id, state, attrs)


async def _setup(hass: HomeAssistant, options: dict) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, title="Home", data={"name": "Home"}, options=options)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _tick(hass: HomeAssistant, seconds: int = 10) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done()


async def test_config_flow_creates_entry(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Casa", "comfort_temp": 21, "eco_temp": 18, "away_temp": 16, "frost_temp": 7},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Casa"


async def test_options_add_zone(hass: HomeAssistant) -> None:
    entry = await _setup(hass, {"comfort_temp": 21, "eco_temp": 18, "away_temp": 16, "frost_temp": 7})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "add_zone"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"zone_name": "Kitchen", "trv_follow_boiler": False}
    )
    assert result["errors"] == {"base": "zone_needs_device"}
    _thermostat(hass, TRV, 18, 18)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"zone_name": "Kitchen", "trvs": [TRV], "trv_follow_boiler": True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options["zones"][0]["zone_name"] == "Kitchen"
    assert hass.states.get("climate.heatwise_kitchen") is not None


async def test_boiler_and_follow_valve(hass: HomeAssistant) -> None:
    _thermostat(hass, BOILER, 12, 19.5, preset="program")
    _thermostat(hass, TRV, 12, 18)
    entry = await _setup(
        hass,
        {
            "boiler_entity": BOILER,
            "comfort_temp": 21, "eco_temp": 18, "away_temp": 16, "frost_temp": 7,
            "zones": [{"zone_id": "k1", "zone_name": "Kitchen", "trvs": [TRV], "trv_follow_boiler": True}],
        },
    )
    assert entry.state is ConfigEntryState.LOADED
    calls_temp = async_mock_service(hass, "climate", "set_temperature")
    calls_preset = async_mock_service(hass, "climate", "set_preset_mode")
    await _tick(hass)
    assert any(c.data["preset_mode"] == "manual" for c in calls_preset)
    sent = {c.data["entity_id"]: c.data["temperature"] for c in calls_temp}
    assert sent[BOILER] == 21
    assert sent[TRV] == 21
    house = hass.states.get("climate.heatwise_home")
    assert house.attributes["temperature"] == 21
    assert house.attributes["reason"] == "home"


async def test_observe_only_sends_nothing(hass: HomeAssistant) -> None:
    _thermostat(hass, BOILER, 12, 19.5)
    entry = MockConfigEntry(
        domain=DOMAIN, title="Home", data={"name": "Home"},
        options={"boiler_entity": BOILER, "comfort_temp": 21, "eco_temp": 18, "away_temp": 16, "frost_temp": 7},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.heatwise_home_heatwise_control"}, blocking=True)
    calls = async_mock_service(hass, "climate", "set_temperature")
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=70))
    await hass.async_block_till_done()
    assert calls == []
    assert "observing" in hass.states.get("sensor.heatwise_home_decision").state


async def test_hybrid_ac_heats_when_mild(hass: HomeAssistant) -> None:
    _thermostat(hass, BOILER, 21, 19.5)
    _thermostat(hass, AC, 21, 18, state="off", step=1)
    hass.states.async_set("sensor.outdoor", "12", {"unit_of_measurement": "°C", "device_class": "temperature"})
    hass.states.async_set("sensor.living", "18.5", {"unit_of_measurement": "°C", "device_class": "temperature"})
    await _setup(
        hass,
        {
            "boiler_entity": BOILER, "outdoor_sensor": "sensor.outdoor",
            "comfort_temp": 21, "eco_temp": 18, "away_temp": 16, "frost_temp": 7,
            "zones": [{"zone_id": "l1", "zone_name": "Living", "acs": [AC], "temp_sensor": "sensor.living", "trv_follow_boiler": False}],
        },
    )
    calls_temp = async_mock_service(hass, "climate", "set_temperature")
    calls_mode = async_mock_service(hass, "climate", "set_hvac_mode")
    await _tick(hass)
    sent = {c.data["entity_id"]: c.data["temperature"] for c in calls_temp}
    assert sent[BOILER] == 16
    assert sent[AC] == 23
    assert any(c.data == {"entity_id": AC, "hvac_mode": "heat"} for c in calls_mode)
    assert hass.states.get("sensor.heatwise_home_heat_source").state == "ac"


async def test_manual_change_is_kept(hass: HomeAssistant) -> None:
    _thermostat(hass, BOILER, 21, 19.5)
    entry = await _setup(
        hass, {"boiler_entity": BOILER, "comfort_temp": 21, "eco_temp": 18, "away_temp": 16, "frost_temp": 7}
    )
    async_mock_service(hass, "climate", "set_temperature")
    await _tick(hass)
    controller = entry.runtime_data
    controller._last_sent.clear()
    _thermostat(hass, BOILER, 23, 19.5)
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=5))
    await hass.async_block_till_done()
    assert controller.plan.house_reason == "manual"
    assert controller.plan.boiler_target == 23
