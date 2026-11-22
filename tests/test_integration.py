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
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "equipment"
    # everything on the equipment page may stay empty
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"boiler_type": "unknown", "ac_energy_class": "unknown"}
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
    for step in ("house", "equipment", "hybrid", "power", "smart", "notify", "add_zone", "edit_zone", "remove_zone"):
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


async def test_ac_energy_and_periods(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2026-01-31 20:00:00+02:00")
    _thermostat(hass, AC, 21, 18, state="heat", step=1)
    hass.states.async_set("sensor.ac_power", "0", {"unit_of_measurement": "W", "device_class": "power"})
    entry = await _setup(
        hass,
        {
            "comfort_temp": 21, "eco_temp": 18, "away_temp": 16, "frost_temp": 7,
            "electricity_price": 1.0, "control": False,
            "zones": [{"zone_id": "l1", "zone_name": "Living", "acs": [AC], "ac_power_sensors": ["sensor.ac_power"], "trv_follow_boiler": False}],
        },
    )
    c = entry.runtime_data
    await _tick(hass, 70)  # first reading
    hass.states.async_set("sensor.ac_power", "1000", {"unit_of_measurement": "W", "device_class": "power"})
    await hass.async_block_till_done()
    # 10 minutes at 1 kW while heating = 0.1667 kWh (gaps are capped at 15 min)
    freezer.tick(timedelta(minutes=10))
    hass.states.async_set("sensor.ac_power", "0", {"unit_of_measurement": "W", "device_class": "power"})
    await hass.async_block_till_done()
    assert abs(c.period_value("ac_kwh", "today") - 1 / 6) < 0.01
    assert abs(c.heating_cost("month") - 1 / 6) < 0.01
    # cooling does not count as heating
    _thermostat(hass, AC, 21, 18, state="cool", step=1)
    hass.states.async_set("sensor.ac_power", "900", {"unit_of_measurement": "W", "device_class": "power"})
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=10))
    hass.states.async_set("sensor.ac_power", "0", {"unit_of_measurement": "W", "device_class": "power"})
    await hass.async_block_till_done()
    assert abs(c.period_value("ac_kwh", "today") - 1 / 6) < 0.01
    # a new month resets today and month, keeps the year
    freezer.move_to("2026-02-01 22:00:00+02:00")
    c._add_period("ac_kwh", 0.0)
    assert c.period_value("ac_kwh", "today") == 0
    assert c.period_value("ac_kwh", "month") == 0
    assert abs(c.period_value("ac_kwh", "year") - 1 / 6) < 0.01


async def test_migrates_gas_from_older_versions(hass: HomeAssistant, freezer, hass_storage) -> None:
    freezer.move_to("2026-11-14 20:00:00+02:00")
    entry = MockConfigEntry(
        domain=DOMAIN, title="Home", data={"name": "Home"},
        options={"comfort_temp": 21, "eco_temp": 18, "away_temp": 16, "frost_temp": 7,
                 "boiler_power_sensor": "sensor.p", "gas_price": 0.25, "gas_kwh_per_m3": 10.0},
    )
    hass_storage[f"heatwise.{entry.entry_id}"] = {
        "version": 1, "key": f"heatwise.{entry.entry_id}",
        "data": {"burner": {"day": "2026-11-14", "seconds": 3600, "total_seconds": 7200},
                 "gas": {"today_m3": 4.0, "total_m3": 7.0}},
    }
    hass.states.async_set("sensor.p", "3", {"unit_of_measurement": "W", "device_class": "power"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    c = entry.runtime_data
    assert c.period_value("gas_m3", "today") == 4.0
    assert c.period_value("gas_m3", "month") == 7.0
    assert abs(c.period_value("gas_cost", "year") - 17.5) < 0.01


BASE = {"comfort_temp": 21, "eco_temp": 18, "away_temp": 16, "frost_temp": 7}


async def test_preheat_before_the_schedule(hass: HomeAssistant) -> None:
    _thermostat(hass, BOILER, 18, 19.5)
    soon = dt_util.utcnow() + timedelta(minutes=40)
    later = dt_util.utcnow() + timedelta(minutes=120)
    hass.states.async_set("schedule.heat", "off", {"next_event": later})
    entry = await _setup(hass, {**BASE, "boiler_entity": BOILER, "schedule_entity": "schedule.heat"})
    async_mock_service(hass, "climate", "set_temperature")
    await _tick(hass)
    assert entry.runtime_data.plan.house_reason == "schedule_eco"
    # 1.5 °C to gain at 1.5 °C/h: one hour ahead
    hass.states.async_set("schedule.heat", "off", {"next_event": soon})
    await hass.async_block_till_done()
    await _tick(hass)
    assert entry.runtime_data.plan.house_reason == "preheat"
    assert entry.runtime_data.plan.boiler_target == 21


async def test_learns_how_fast_the_house_warms_up(hass: HomeAssistant, freezer) -> None:
    _thermostat(hass, BOILER, 21, 19.5)
    entry = await _setup(hass, {**BASE, "boiler_entity": BOILER})
    controller = entry.runtime_data
    controller.set_control(False)
    await _tick(hass)
    assert "house" in controller._heat_sessions
    freezer.tick(timedelta(hours=1))
    _thermostat(hass, BOILER, 21, 21.0)
    await hass.async_block_till_done()
    await _tick(hass, 60)
    assert controller.heat_rates["house"] == 1.5
    assert controller.heat_rate("kitchen") == 1.5


async def test_warms_up_when_someone_heads_home(hass: HomeAssistant) -> None:
    hass.states.async_set("person.a", "not_home")
    dist = "sensor.home_a_distance"
    direction = "sensor.home_a_direction_of_travel"
    hass.states.async_set(dist, "12000", {"unit_of_measurement": "m", "device_class": "distance"})
    hass.states.async_set(direction, "stationary")
    entry = await _setup(
        hass, {**BASE, "persons": ["person.a"], "arrival_sensors": [dist], "arrival_km": 15}
    )
    await _tick(hass)
    assert entry.runtime_data.plan.house_reason == "away"
    hass.states.async_set(dist, "9500", {"unit_of_measurement": "m", "device_class": "distance"})
    hass.states.async_set(direction, "towards")
    await hass.async_block_till_done()
    await _tick(hass)
    assert entry.runtime_data.plan.house_reason == "arriving"
    assert hass.states.get("sensor.heatwise_home_decision").attributes["on_the_way_home"] is True


async def test_notifications_and_language(hass: HomeAssistant, freezer) -> None:
    hass.states.async_set("binary_sensor.window", "off")
    _thermostat(hass, BOILER, 21, 20.5)
    entry = await _setup(
        hass,
        {
            **BASE,
            "boiler_entity": BOILER,
            "window_sensors": ["binary_sensor.window"],
            "notify_targets": ["notify.phone"],
            "language": "ro",
        },
    )
    sent = async_mock_service(hass, "notify", "phone")
    async_mock_service(hass, "climate", "set_temperature")
    controller = entry.runtime_data
    assert controller.language == "ro"
    assert "Program" not in (controller.explanation() or "")
    await _tick(hass)
    hass.states.async_set("binary_sensor.window", "on")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=70))
    await _tick(hass, 70)
    assert any("Fereastră deschisă în Home" in c.data["message"] for c in sent)

    # device offline for 15 minutes, then back
    hass.states.async_set(BOILER, "unavailable")
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=16))
    await _tick(hass, 60)
    assert any("nu mai răspunde" in c.data["message"] for c in sent)
    _thermostat(hass, BOILER, 21, 20.5)
    await hass.async_block_till_done()
    await _tick(hass, 60)
    assert any("răspunde din nou" in c.data["message"] for c in sent)

    await controller.async_send_weekly_report()
    await hass.async_block_till_done()
    assert sent[-1].data["title"] == "HeatWise: săptămâna aceasta"


def _power(hass, watts) -> None:
    hass.states.async_set("sensor.boiler_power", str(watts), {"unit_of_measurement": "W", "device_class": "power"})


def _boiler_call(hass, heating: bool) -> None:
    hass.states.async_set(
        BOILER,
        "heat",
        {
            "temperature": 21, "current_temperature": 20.5, "min_temp": 5, "max_temp": 30,
            "target_temp_step": 0.5, "hvac_modes": ["off", "heat"],
            "hvac_action": "heating" if heating else "idle",
        },
    )


GAS = {
    **BASE,
    "boiler_entity": BOILER,
    "boiler_power_sensor": "sensor.boiler_power", "burner_threshold": 30,
    "gas_rate": 2.0, "gas_kwh_per_m3": 10.0, "gas_price": 0.3,
}


async def test_hot_water_is_counted_apart(hass: HomeAssistant, freezer) -> None:
    _boiler_call(hass, False)
    _power(hass, 4)
    entry = await _setup(hass, GAS)
    async_mock_service(hass, "climate", "set_temperature")
    c = entry.runtime_data
    assert c.split_hot_water

    # a 30 minute shower: burner on, no heat call
    _power(hass, 70)
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=30))
    _power(hass, 4)
    await hass.async_block_till_done()

    # 30 minutes of heating, the burner keeps going 60 s after the call ends (pump overrun)
    _boiler_call(hass, True)
    await hass.async_block_till_done()
    _power(hass, 70)
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=30))
    _boiler_call(hass, False)
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=60))
    _power(hass, 4)
    await hass.async_block_till_done()

    assert abs(c.period_value("dhw_m3", "today") - 1.0) < 0.01
    assert abs(c.period_value("gas_m3", "today") - (2.0 + 2.0 / 60)) < 0.01
    await _tick(hass, 70)
    assert abs(float(hass.states.get("sensor.heatwise_home_hot_water_gas_today").state) - 1.0) < 0.01
    assert abs(float(hass.states.get("sensor.heatwise_home_hot_water_cost_today").state) - 3.0) < 0.05
    # heating cost leaves the shower out: 1.033 m³ × 10 kWh × 0.3
    assert abs(float(hass.states.get("sensor.heatwise_home_heating_cost_today").state) - 3.1) < 0.05
    gas = hass.states.get("sensor.heatwise_home_gas_today")
    assert abs(gas.attributes["hot_water_m3"] - 1.0) < 0.01


async def test_gas_counts_by_plug_power(hass: HomeAssistant, freezer) -> None:
    _boiler_call(hass, True)
    _power(hass, 4)
    entry = await _setup(hass, {**GAS, "split_hot_water": False})
    async_mock_service(hass, "climate", "set_temperature")
    c = entry.runtime_data
    assert not c.split_hot_water
    _power(hass, 60)
    await hass.async_block_till_done()
    freezer.tick(timedelta(hours=1))
    # the fan speeds up: the boiler burns more gas
    _power(hass, 90)
    await hass.async_block_till_done()
    freezer.tick(timedelta(hours=1))
    _power(hass, 4)
    await hass.async_block_till_done()
    assert c.power_ref is not None
    # 1 h × 2 m³/h at the usual power + 1 h × 2 m³/h × 1.5
    assert abs(c.gas_today_live - 5.0) < 0.01
    assert abs(c.burner_load_live_seconds / 3600 - 2.5) < 0.01


async def test_gas_meter_reading_typed_in(hass: HomeAssistant, freezer) -> None:
    from homeassistant.exceptions import ServiceValidationError

    _boiler_call(hass, True)
    _power(hass, 4)
    hass.states.async_set("sensor.gas_meter", "290", {"unit_of_measurement": "m³"})
    entry = await _setup(hass, {**GAS, "gas_meter_entity": "sensor.gas_meter"})
    async_mock_service(hass, "climate", "set_temperature")
    c = entry.runtime_data
    meter = "number.heatwise_home_gas_meter_reading"
    await _tick(hass)
    assert float(hass.states.get(meter).state) == 290

    _power(hass, 65)
    await hass.async_block_till_done()
    freezer.tick(timedelta(hours=4))
    _power(hass, 4)
    await hass.async_block_till_done()

    # read on the meter: 6 m³ in 4 burner hours
    await hass.services.async_call("number", "set_value", {"entity_id": meter, "value": 296}, blocking=True)
    assert c.gas_calibrations == 1 and abs(c.gas_rate - 1.5) < 0.001
    assert c.gas_baseline["source"] == "manual"
    await hass.async_block_till_done()
    assert float(hass.states.get(meter).state) == 296

    # a typo below the last reading is refused
    try:
        await hass.services.async_call("number", "set_value", {"entity_id": meter, "value": 280}, blocking=True)
        raise AssertionError("expected a validation error")
    except ServiceValidationError as err:
        assert err.translation_key == "meter_too_low"
    assert c.gas_baseline["meter"] == 296

    # the supplier's sensor still shows last month's index: ignored, not a new meter
    hass.states.async_set("sensor.gas_meter", "291", {"unit_of_measurement": "m³"})
    await hass.async_block_till_done()
    assert c.gas_baseline["meter"] == 296 and c.gas_calibrations == 1

    # a reading soon after keeps counting from the last calibration
    await hass.services.async_call("number", "set_value", {"entity_id": meter, "value": 296.2}, blocking=True)
    assert c.gas_baseline["meter"] == 296 and c.last_meter_reading == 296.2


async def test_window_guessed_from_a_temperature_drop(hass: HomeAssistant, freezer) -> None:
    _thermostat(hass, BOILER, 21, 20.5)
    _thermostat(hass, TRV, 21, 21)
    hass.states.async_set("sensor.kitchen_temp", "21.0", {"unit_of_measurement": "°C", "device_class": "temperature"})
    entry = await _setup(
        hass,
        {
            **BASE,
            "boiler_entity": BOILER,
            "notify_targets": ["notify.phone"],
            "zones": [{"zone_id": "k1", "zone_name": "Kitchen", "trvs": [TRV], "temp_sensor": "sensor.kitchen_temp", "trv_follow_boiler": False}],
        },
    )
    sent = async_mock_service(hass, "notify", "phone")
    calls = async_mock_service(hass, "climate", "set_temperature")
    await _tick(hass)
    for temp in ("20.7", "20.4", "20.1"):
        freezer.tick(timedelta(minutes=1))
        hass.states.async_set("sensor.kitchen_temp", temp, {"unit_of_measurement": "°C", "device_class": "temperature"})
        await _tick(hass, 5)
    c = entry.runtime_data
    assert c.plan.zones["k1"].reason == "window_drop"
    assert any(x.data["entity_id"] == TRV and x.data["temperature"] == 7 for x in calls)
    assert any("probably open" in x.data["message"] for x in sent)
    assert hass.states.get("sensor.heatwise_home_decision").attributes["window_suspected"] == ["Kitchen"]
    # the valve's own reading is never used: the house zone has no sensor of its own here
    assert c.plan.house_reason != "window_drop"

    # the room warms again: window closed
    for temp in ("20.2", "20.5"):
        freezer.tick(timedelta(minutes=2))
        hass.states.async_set("sensor.kitchen_temp", temp, {"unit_of_measurement": "°C", "device_class": "temperature"})
        await hass.async_block_till_done()
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=5), fire_all=True)
        await hass.async_block_till_done()
    assert c.plan.zones["k1"].reason != "window_drop"


async def test_window_guess_can_be_turned_off(hass: HomeAssistant, freezer) -> None:
    _thermostat(hass, TRV, 21, 21)
    hass.states.async_set("sensor.kitchen_temp", "21.0", {"unit_of_measurement": "°C", "device_class": "temperature"})
    entry = await _setup(
        hass,
        {
            **BASE, "window_detect": False,
            "zones": [{"zone_id": "k1", "zone_name": "Kitchen", "trvs": [TRV], "temp_sensor": "sensor.kitchen_temp", "trv_follow_boiler": False}],
        },
    )
    async_mock_service(hass, "climate", "set_temperature")
    await _tick(hass)
    freezer.tick(timedelta(minutes=2))
    hass.states.async_set("sensor.kitchen_temp", "19.5", {"unit_of_measurement": "°C", "device_class": "temperature"})
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=5), fire_all=True)
    await hass.async_block_till_done()
    c = entry.runtime_data
    assert c.room_temperature("k1") == 19.5
    assert c.plan.zones["k1"].reason != "window_drop"
    assert not c.window_detector.is_open("k1")


async def test_burner_run_in_progress_survives_a_restart(hass: HomeAssistant, freezer) -> None:
    """A shower still running when Home Assistant restarts keeps its gas (and hot water)."""
    from homeassistant.const import EVENT_HOMEASSISTANT_STOP

    _boiler_call(hass, False)
    _power(hass, 4)
    entry = await _setup(hass, GAS)
    async_mock_service(hass, "climate", "set_temperature")
    c = entry.runtime_data
    _power(hass, 70)
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=17))
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    stored = hass_storage_values(hass, entry)
    assert abs(stored["periods"]["values"]["today"]["dhw_m3"] - 2.0 * 17 / 60) < 0.01
    assert abs(stored["periods"]["values"]["today"]["gas_m3"] - 2.0 * 17 / 60) < 0.01
    # still counting on: the run in progress is not booked twice
    freezer.tick(timedelta(minutes=3))
    assert abs(c.period_value("dhw_m3", "today") - 2.0 * 20 / 60) < 0.01


async def test_long_burner_run_is_booked_as_it_goes(hass: HomeAssistant, freezer) -> None:
    _boiler_call(hass, True)
    _power(hass, 4)
    entry = await _setup(hass, GAS)
    async_mock_service(hass, "climate", "set_temperature")
    c = entry.runtime_data
    _power(hass, 70)
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=6))
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=1), fire_all=True)
    await hass.async_block_till_done()
    assert abs(c.period_values["today"]["gas_m3"] - 0.2) < 0.01


def hass_storage_values(hass, entry):
    return entry.runtime_data._store_data()


async def test_no_preheat_for_air_conditioners(hass: HomeAssistant) -> None:
    _thermostat(hass, AC, 21, 18, state="off", step=1)
    hass.states.async_set("sensor.bed", "18", {"unit_of_measurement": "°C", "device_class": "temperature"})
    soon = dt_util.utcnow() + timedelta(minutes=40)
    hass.states.async_set("schedule.bed", "off", {"next_event": soon})
    entry = await _setup(
        hass,
        {
            **BASE,
            "zones": [{"zone_id": "b1", "zone_name": "Bedroom", "acs": [AC], "temp_sensor": "sensor.bed",
                       "schedule_entity": "schedule.bed"}],
        },
    )
    async_mock_service(hass, "climate", "set_temperature")
    async_mock_service(hass, "climate", "set_hvac_mode")
    await _tick(hass)
    assert entry.runtime_data.preheating["b1"] is False
    assert entry.runtime_data.plan.zones["b1"].reason == "schedule_eco"


async def test_preheat_keeps_going_once_the_room_is_warm(hass: HomeAssistant) -> None:
    _thermostat(hass, BOILER, 18, 20.5)
    soon = dt_util.utcnow() + timedelta(minutes=20)
    hass.states.async_set("schedule.heat", "off", {"next_event": soon})
    entry = await _setup(hass, {**BASE, "boiler_entity": BOILER, "schedule_entity": "schedule.heat"})
    async_mock_service(hass, "climate", "set_temperature")
    await _tick(hass)
    assert entry.runtime_data.plan.house_reason == "preheat"
    # the room reaches comfort before the schedule: stay on comfort, no flip to eco
    _thermostat(hass, BOILER, 21, 21.2)
    await hass.async_block_till_done()
    await _tick(hass, 60)
    assert entry.runtime_data.plan.house_reason == "preheat"


async def test_window_alerts_go_to_the_extra_targets_only(hass: HomeAssistant, freezer) -> None:
    hass.states.async_set("binary_sensor.window", "off")
    _thermostat(hass, BOILER, 21, 20.5)
    entry = await _setup(
        hass,
        {
            **BASE,
            "boiler_entity": BOILER,
            "window_sensors": ["binary_sensor.window"],
            "notify_targets": ["notify.phone"],
            "notify_window_targets": ["notify.partner"],
        },
    )
    mine = async_mock_service(hass, "notify", "phone")
    theirs = async_mock_service(hass, "notify", "partner")
    async_mock_service(hass, "climate", "set_temperature")
    await _tick(hass)
    hass.states.async_set("binary_sensor.window", "on")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=70))
    await _tick(hass, 70)
    assert len(mine) == 1 and len(theirs) == 1
    await entry.runtime_data.async_send_weekly_report()
    await hass.async_block_till_done()
    assert len(mine) == 2 and len(theirs) == 1


async def _ac_running(hass: HomeAssistant, **extra):
    _thermostat(hass, BOILER, 21, 19.5)
    _thermostat(hass, AC, 21, 18, state="off", step=1)
    hass.states.async_set("sensor.outdoor", "12", {"unit_of_measurement": "°C", "device_class": "temperature"})
    hass.states.async_set("sensor.living", "18.5", {"unit_of_measurement": "°C", "device_class": "temperature"})
    entry = await _setup(
        hass,
        {
            "boiler_entity": BOILER, "outdoor_sensor": "sensor.outdoor", **BASE, **extra,
            "zones": [{"zone_id": "l1", "zone_name": "Living", "acs": [AC], "temp_sensor": "sensor.living", "trv_follow_boiler": False}],
        },
    )
    async_mock_service(hass, "climate", "set_temperature")
    async_mock_service(hass, "climate", "set_hvac_mode")
    off = async_mock_service(hass, "climate", "turn_off")
    await _tick(hass)
    assert AC in entry.runtime_data.ac_owned
    _thermostat(hass, AC, 23, 18, state="heat", step=1)
    await hass.async_block_till_done()
    return entry, off


async def test_turning_control_off_hands_the_acs_back(hass: HomeAssistant) -> None:
    entry, off = await _ac_running(hass)
    entry.runtime_data.set_control(False)
    await hass.async_block_till_done()
    assert [c.data["entity_id"] for c in off] == [AC]
    assert not entry.runtime_data.ac_owned


async def test_removing_heatwise_switches_its_acs_off(hass: HomeAssistant) -> None:
    entry, off = await _ac_running(hass)
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert AC in [c.data["entity_id"] for c in off]


async def test_mould_protection(hass: HomeAssistant, freezer) -> None:
    _thermostat(hass, BOILER, 18, 18.5)
    _thermostat(hass, "climate.kitchen_valve", 18, 18.0)
    hass.states.async_set("person.a", "not_home")
    hass.states.async_set("sensor.kitchen_rh", "70", {"unit_of_measurement": "%", "device_class": "humidity"})
    hass.states.async_set("sensor.kitchen_t", "18.0", {"unit_of_measurement": "°C", "device_class": "temperature"})
    entry = await _setup(
        hass,
        {
            **BASE, "boiler_entity": BOILER, "persons": ["person.a"], "notify_targets": ["notify.phone"],
            "zones": [{"zone_id": "k1", "zone_name": "Kitchen", "trvs": ["climate.kitchen_valve"],
                       "temp_sensor": "sensor.kitchen_t", "humidity_sensor": "sensor.kitchen_rh", "trv_follow_boiler": False}],
        },
    )
    sent = async_mock_service(hass, "notify", "phone")
    async_mock_service(hass, "climate", "set_temperature")
    await _tick(hass)
    plan = entry.runtime_data.plan
    assert plan.zones["k1"].reason == "away"
    freezer.tick(timedelta(hours=2, minutes=1))
    await entry.runtime_data.async_evaluate()
    await hass.async_block_till_done()
    plan = entry.runtime_data.plan
    assert plan.zones["k1"].target == 19 and plan.zones["k1"].reason == "mould"
    assert any("Kitchen" in c.data["message"] for c in sent)
    hass.states.async_set("sensor.kitchen_rh", "60", {"unit_of_measurement": "%", "device_class": "humidity"})
    await hass.async_block_till_done()
    await entry.runtime_data.async_evaluate()
    assert entry.runtime_data.plan.zones["k1"].reason == "away"


async def test_mould_in_an_ac_room_only_alerts(hass: HomeAssistant, freezer) -> None:
    _thermostat(hass, AC, 21, 17, state="off", step=1)
    hass.states.async_set("person.a", "not_home")
    hass.states.async_set("sensor.bed_rh", "70", {"unit_of_measurement": "%", "device_class": "humidity"})
    hass.states.async_set("sensor.bed_t", "17.0", {"unit_of_measurement": "°C", "device_class": "temperature"})
    entry = await _setup(
        hass,
        {
            **BASE, "persons": ["person.a"], "notify_targets": ["notify.phone"],
            "zones": [{"zone_id": "b1", "zone_name": "Bedroom", "acs": [AC],
                       "temp_sensor": "sensor.bed_t", "humidity_sensor": "sensor.bed_rh"}],
        },
    )
    sent = async_mock_service(hass, "notify", "phone")
    async_mock_service(hass, "climate", "set_temperature")
    await _tick(hass)
    freezer.tick(timedelta(hours=2, minutes=1))
    await entry.runtime_data.async_evaluate()
    await hass.async_block_till_done()
    assert entry.runtime_data.plan.zones["b1"].reason == "away"  # no AC at night for mould
    assert any("Bedroom" in c.data["message"] and "°C" not in c.data["message"] for c in sent)


def _rh(hass, entity_id, value):
    hass.states.async_set(entity_id, str(value), {"unit_of_measurement": "%", "device_class": "humidity"})


def _t(hass, entity_id, value):
    hass.states.async_set(entity_id, str(value), {"unit_of_measurement": "°C", "device_class": "temperature"})


async def test_humidity_wait_survives_a_restart(hass: HomeAssistant, freezer) -> None:
    _thermostat(hass, "climate.kitchen_valve", 18, 18.0)
    _rh(hass, "sensor.kitchen_rh", 70)
    _t(hass, "sensor.kitchen_t", 18.0)
    entry = await _setup(
        hass,
        {
            **BASE,
            "zones": [{"zone_id": "k1", "zone_name": "Kitchen", "trvs": ["climate.kitchen_valve"],
                       "temp_sensor": "sensor.kitchen_t", "humidity_sensor": "sensor.kitchen_rh", "trv_follow_boiler": False}],
        },
    )
    async_mock_service(hass, "climate", "set_temperature")
    await entry.runtime_data.async_evaluate()
    freezer.tick(timedelta(hours=1, minutes=10))
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=55))
    await entry.runtime_data.async_evaluate()
    assert entry.runtime_data.mould_risk.get("k1") is True


async def test_waits_for_sensors_after_start(hass: HomeAssistant, freezer) -> None:
    _thermostat(hass, BOILER, 18, 18.5)
    entry = await _setup(hass, {**BASE, "boiler_entity": BOILER, "outdoor_sensor": "sensor.outdoor"})
    async_mock_service(hass, "climate", "set_temperature")
    c = entry.runtime_data
    await c.async_evaluate()
    assert c.plan is None  # the outdoor sensor has not reported yet
    _t(hass, "sensor.outdoor", 5)
    await hass.async_block_till_done()
    await c.async_evaluate()
    assert c.plan is not None and c.plan.source_reason != "no_outdoor"


async def test_gives_up_waiting_for_a_dead_sensor(hass: HomeAssistant, freezer) -> None:
    _thermostat(hass, BOILER, 18, 18.5)
    entry = await _setup(hass, {**BASE, "boiler_entity": BOILER, "outdoor_sensor": "sensor.outdoor"})
    async_mock_service(hass, "climate", "set_temperature")
    freezer.tick(timedelta(seconds=130))
    await entry.runtime_data.async_evaluate()
    assert entry.runtime_data.plan is not None


async def test_suggests_airing_when_outside_is_drier(hass: HomeAssistant, freezer) -> None:
    from datetime import datetime

    freezer.move_to(datetime(2026, 11, 19, 12, tzinfo=dt_util.get_default_time_zone()))
    _thermostat(hass, "climate.kitchen_valve", 21, 21.0)
    _rh(hass, "sensor.kitchen_rh", 70)
    _t(hass, "sensor.kitchen_t", 21.0)
    _t(hass, "sensor.outdoor", 5)
    _rh(hass, "sensor.outdoor_rh", 80)
    entry = await _setup(
        hass,
        {
            **BASE, "outdoor_sensor": "sensor.outdoor", "outdoor_humidity_sensor": "sensor.outdoor_rh",
            "notify_targets": ["notify.phone"],
            "zones": [{"zone_id": "k1", "zone_name": "Kitchen", "trvs": ["climate.kitchen_valve"],
                       "temp_sensor": "sensor.kitchen_t", "humidity_sensor": "sensor.kitchen_rh", "trv_follow_boiler": False}],
        },
    )
    sent = async_mock_service(hass, "notify", "phone")
    async_mock_service(hass, "climate", "set_temperature")
    c = entry.runtime_data
    await c.async_evaluate()
    await hass.async_block_till_done()
    assert c.air_rooms == ["Kitchen"]
    assert len(sent) == 1 and "Kitchen" in sent[0].data["message"]
    await c.async_evaluate()  # not again for hours
    await hass.async_block_till_done()
    assert len(sent) == 1
    _rh(hass, "sensor.outdoor_rh", 100)
    _t(hass, "sensor.outdoor", 18)
    await c.async_evaluate()
    assert c.air_rooms == []  # warm damp air outside would not help


async def test_ac_heats_once_per_period(hass: HomeAssistant, freezer) -> None:
    entry, off = await _ac_running(hass, ac_once_per_period=True, ac_stop_above=0)
    c = entry.runtime_data
    hass.states.async_set("sensor.living", "21.0", {"unit_of_measurement": "°C", "device_class": "temperature"})
    await hass.async_block_till_done()
    await c.async_evaluate()
    await hass.async_block_till_done()
    assert c.plan.zones["l1"].ac_action == "off" and "l1" in c._ac_done
    _thermostat(hass, AC, 23, 18, state="off", step=1)
    hass.states.async_set("sensor.living", "19.0", {"unit_of_measurement": "°C", "device_class": "temperature"})
    await hass.async_block_till_done()
    await c.async_evaluate()
    assert c.plan.zones["l1"].ac_action == "none"  # cold again, but done until the period ends
    freezer.move_to(dt_util.start_of_local_day() + timedelta(days=1, hours=1))
    await c.async_evaluate()
    assert c.plan.zones["l1"].ac_action == "heat"


async def test_degree_days_efficiency_report_button_and_meter_reminder(hass: HomeAssistant, freezer) -> None:
    freezer.move_to(dt_util.start_of_local_day() + timedelta(hours=10))
    _thermostat(hass, BOILER, 21, 20.0)
    hass.states.async_set("sensor.boiler_power", "4", {"unit_of_measurement": "W", "device_class": "power"})
    hass.states.async_set("sensor.outdoor", "6", {"unit_of_measurement": "°C", "device_class": "temperature"})
    entry = await _setup(
        hass,
        {
            **BASE, "boiler_entity": BOILER, "outdoor_sensor": "sensor.outdoor",
            "boiler_power_sensor": "sensor.boiler_power", "burner_threshold": 30,
            "notify_targets": ["notify.phone"], "meter_reminder_days": 14,
        },
    )
    sent = async_mock_service(hass, "notify", "phone")
    async_mock_service(hass, "climate", "set_temperature")
    c = entry.runtime_data
    for _ in range(14):  # over two hours, 12 °C below the base
        freezer.tick(timedelta(minutes=10))
        await c.async_evaluate()
    hdd = c.period_value("hdd", "week")
    assert 1.0 < hdd <= 1.17  # the first evaluation only starts the count
    c._add_period("burner_h", 0.5)
    assert c.efficiency() is not None and abs(c.efficiency() - 0.5 / hdd) < 0.01
    await hass.services.async_call("button", "press", {"entity_id": "button.heatwise_home_send_weekly_report"}, blocking=True)
    await hass.async_block_till_done()
    assert any("degree-day" in call.data["message"] for call in sent)
    before = len(sent)
    await c._on_report_time(dt_util.utcnow())  # never read the meter: remind
    await hass.async_block_till_done()
    assert any("meter" in call.data["title"].lower() for call in sent[before:])
    before = len(sent)
    await c._on_report_time(dt_util.utcnow() + timedelta(days=1))  # not again for 14 days
    await hass.async_block_till_done()
    assert not any("meter" in call.data["title"].lower() for call in sent[before:])
