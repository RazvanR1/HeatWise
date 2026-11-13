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


async def test_every_options_page_opens(hass: HomeAssistant) -> None:
    """Each options form must serialize (the UI rejects invalid selectors)."""
    import voluptuous_serialize
    from homeassistant.helpers import config_validation as cv

    _thermostat(hass, TRV, 18, 18)
    entry = await _setup(
        hass,
        {
            "comfort_temp": 21, "eco_temp": 18, "away_temp": 16, "frost_temp": 7,
            "zones": [{"zone_id": "k1", "zone_name": "Kitchen", "trvs": [TRV], "trv_follow_boiler": False}],
        },
    )
    for step in ("house", "hybrid", "power", "add_zone", "edit_zone", "remove_zone"):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": step})
        assert result["type"] is FlowResultType.FORM, step
        voluptuous_serialize.convert(result["data_schema"], custom_serializer=cv.custom_serializer)
        hass.config_entries.options.async_abort(result["flow_id"])


async def test_empty_house_at_start_is_away(hass: HomeAssistant) -> None:
    hass.states.async_set("person.a", "Work")
    entry = await _setup(
        hass,
        {"persons": ["person.a"], "comfort_temp": 21, "eco_temp": 18, "away_temp": 16, "frost_temp": 7},
    )
    await _tick(hass)
    assert entry.runtime_data.plan.house_reason == "away"
    hass.states.async_set("person.a", "home")
    await hass.async_block_till_done()
    await _tick(hass)
    assert entry.runtime_data.anyone_home is True
    assert entry.runtime_data.plan.house_reason == "home"


async def test_away_delay_after_leaving(hass: HomeAssistant, freezer) -> None:
    hass.states.async_set("person.a", "home")
    entry = await _setup(
        hass,
        {"persons": ["person.a"], "away_delay": 10, "comfort_temp": 21, "eco_temp": 18, "away_temp": 16, "frost_temp": 7},
    )
    await _tick(hass)
    hass.states.async_set("person.a", "not_home")
    await hass.async_block_till_done()
    await _tick(hass, 60)
    assert entry.runtime_data.anyone_home is True  # still inside the delay
    freezer.tick(timedelta(minutes=11))
    await _tick(hass, 60)
    assert entry.runtime_data.anyone_home is False


async def test_panel_and_status_api(hass: HomeAssistant, hass_ws_client) -> None:
    from homeassistant.components import frontend

    _thermostat(hass, BOILER, 21, 19.5)
    _thermostat(hass, TRV, 18, 18)
    entry = await _setup(
        hass,
        {
            "boiler_entity": BOILER, "comfort_temp": 21, "eco_temp": 18, "away_temp": 16, "frost_temp": 7,
            "zones": [{"zone_id": "k1", "zone_name": "Kitchen", "trvs": [TRV], "trv_follow_boiler": True}],
        },
    )
    await _tick(hass)
    assert "heatwise" in hass.data[frontend.DATA_PANELS]
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "heatwise/status"})
    msg = await client.receive_json()
    assert msg["success"]
    house = msg["result"]["houses"][0]
    assert house["name"] == "Home"
    assert [z["climate"] for z in house["zones"]] == ["climate.heatwise_home", "climate.heatwise_kitchen"]
    assert house["zones"][1]["kind"] == "trv"
    assert house["entities"]["control"] == "switch.heatwise_home_heatwise_control"

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert "heatwise" not in hass.data[frontend.DATA_PANELS]


async def test_gas_estimate_and_calibration(hass: HomeAssistant, freezer) -> None:
    hass.states.async_set("sensor.boiler_power", "4", {"unit_of_measurement": "W", "device_class": "power"})
    hass.states.async_set("sensor.gas_meter", "100", {"unit_of_measurement": "m³"})
    entry = await _setup(
        hass,
        {
            "comfort_temp": 21, "eco_temp": 18, "away_temp": 16, "frost_temp": 7,
            "boiler_power_sensor": "sensor.boiler_power", "burner_threshold": 30,
            "gas_meter_entity": "sensor.gas_meter", "gas_rate": 2.0, "gas_kwh_per_m3": 10.0,
            "gas_price": 0.3,
        },
    )
    c = entry.runtime_data
    assert c.gas_baseline["meter"] == 100

    # 30 minutes of burner at 2 m³/h -> 1 m³, 10 kWh, 3 lei
    hass.states.async_set("sensor.boiler_power", "65", {"unit_of_measurement": "W", "device_class": "power"})
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=30))
    hass.states.async_set("sensor.boiler_power", "5", {"unit_of_measurement": "W", "device_class": "power"})
    await hass.async_block_till_done()
    assert abs(c.gas_today_live - 1.0) < 0.01
    assert abs(c.gas_cost_today - 3.0) < 0.05
    await _tick(hass, 70)
    assert abs(float(hass.states.get("sensor.heatwise_home_gas_today").state) - 1.0) < 0.01

    # 5 more burner hours, then the meter shows 8 m³ used since the baseline -> 8 / 5.5 h
    hass.states.async_set("sensor.boiler_power", "65", {"unit_of_measurement": "W", "device_class": "power"})
    await hass.async_block_till_done()
    freezer.tick(timedelta(hours=5))
    hass.states.async_set("sensor.boiler_power", "5", {"unit_of_measurement": "W", "device_class": "power"})
    await hass.async_block_till_done()
    hass.states.async_set("sensor.gas_meter", "108", {"unit_of_measurement": "m³"})
    await hass.async_block_till_done()
    assert c.gas_calibrations == 1
    assert abs(c.gas_rate - 8 / 5.5) < 0.01
    total_before = c.gas_total_live
    # a meter replacement (lower index) only resets the baseline
    hass.states.async_set("sensor.gas_meter", "3", {"unit_of_measurement": "m³"})
    await hass.async_block_till_done()
    assert c.gas_baseline["meter"] == 3 and c.gas_calibrations == 1
    assert c.gas_total_live >= total_before
