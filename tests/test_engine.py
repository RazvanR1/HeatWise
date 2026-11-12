"""Tests for the HeatWise decision engine (no Home Assistant needed)."""

import importlib.util
import pathlib
import sys

_PATH = pathlib.Path(__file__).parents[1] / "custom_components" / "heatwise" / "engine.py"
_spec = importlib.util.spec_from_file_location("heatwise_engine", _PATH)
engine = importlib.util.module_from_spec(_spec)
sys.modules["heatwise_engine"] = engine
_spec.loader.exec_module(engine)

Temps = engine.Temps
ZoneConfig = engine.ZoneConfig
ZoneState = engine.ZoneState
HouseState = engine.HouseState
HybridConfig = engine.HybridConfig

HOUSE = ZoneConfig("house", "House", Temps(21, 18, 16, 7), is_house=True)
LIVING = ZoneConfig("living", "Living", Temps(21, 18, 16, 7), has_ac=True)
KITCHEN = ZoneConfig("kitchen", "Kitchen", Temps(21, 18, 16, 7), has_trv=True)
KITCHEN_FOLLOW = ZoneConfig(
    "kitchen", "Kitchen", Temps(21, 18, 16, 7), has_trv=True, trv_follow_boiler=True
)


def run(zones, states=None, house=None, hybrid=None):
    return engine.evaluate(
        HOUSE, zones, states or {}, house or HouseState(), hybrid or HybridConfig()
    )


def test_single_thermostat_home_without_schedule_is_comfort():
    plan = run([])
    assert plan.boiler_target == 21
    assert plan.source == "boiler"
    assert plan.source_reason == "no_ac"


def test_schedule_and_away():
    plan = run([], {"house": ZoneState(schedule_on=False)})
    assert plan.boiler_target == 18
    plan = run([], {"house": ZoneState(schedule_on=True)}, HouseState(anyone_home=False))
    assert plan.boiler_target == 16
    assert plan.house_reason == "away"


def test_window_and_off_give_frost():
    assert run([], {"house": ZoneState(window_open=True)}).boiler_target == 7
    assert run([], {"house": ZoneState(enabled=False)}).boiler_target == 7


def test_override_and_presets():
    assert run([], {"house": ZoneState(override_temp=23)}).boiler_target == 23
    assert run([], {"house": ZoneState(preset="boost")}).boiler_target == 23
    assert run([], {"house": ZoneState(preset="eco")}).boiler_target == 18


def test_warm_outside_with_hysteresis():
    house = HouseState(outdoor_temp=19.5, warm_off_threshold=19)
    plan = run([], house=house)
    assert plan.warm_off and plan.boiler_target == 7
    house = HouseState(outdoor_temp=18.5, warm_off_threshold=19, previous_warm_off=True)
    assert run([], house=house).warm_off
    house = HouseState(outdoor_temp=17.5, warm_off_threshold=19, previous_warm_off=True)
    assert not run([], house=house).warm_off


def test_threshold_hybrid_uses_ac_when_mild():
    states = {"living": ZoneState(room_temp=19.0)}
    plan = run([LIVING], states, HouseState(outdoor_temp=12))
    assert plan.source == "ac"
    assert plan.boiler_target == 16  # boiler drops to away level
    assert plan.zones["living"].ac_action == "heat"
    assert plan.zones["living"].ac_setpoint == 23


def test_threshold_hybrid_hysteresis():
    plan = run([LIVING], house=HouseState(outdoor_temp=8.3))
    assert plan.source == "boiler"
    plan = run([LIVING], house=HouseState(outdoor_temp=7.8, previous_source="ac"))
    assert plan.source == "ac"


def test_price_based_hybrid():
    hybrid = HybridConfig(gas_price=0.30, electricity_price=1.0)
    # 5 C: COP 3.34 -> AC 0.30 lei/kWh vs gas 0.326 -> AC cheaper by > 5 %
    plan = run([LIVING], house=HouseState(outdoor_temp=5), hybrid=hybrid)
    assert plan.source == "ac" and plan.source_reason == "ac_cheaper"
    # -5 C: COP 2.54 -> AC 0.39 -> gas cheaper
    plan = run([LIVING], house=HouseState(outdoor_temp=-5), hybrid=hybrid)
    assert plan.source == "boiler" and plan.source_reason == "gas_cheaper"


def test_too_cold_and_forced_modes():
    plan = run([LIVING], house=HouseState(outdoor_temp=-20))
    assert plan.source_reason == "too_cold_for_ac"
    plan = run([LIVING], house=HouseState(outdoor_temp=15), hybrid=HybridConfig(mode="boiler_only"))
    assert plan.source == "boiler"
    plan = run([LIVING], house=HouseState(outdoor_temp=0), hybrid=HybridConfig(mode="ac_only"))
    assert plan.source == "ac"


def test_ac_hysteresis_and_ownership():
    house = HouseState(outdoor_temp=12)
    # Warm enough, AC not ours -> leave it alone
    plan = run([LIVING], {"living": ZoneState(room_temp=20.8)}, house)
    assert plan.zones["living"].ac_action == "none"
    # Ours running, still below target + 0.3 -> keep heating
    plan = run([LIVING], {"living": ZoneState(room_temp=21.1, ac_ours_running=True)}, house)
    assert plan.zones["living"].ac_action == "heat"
    # Ours running, reached target + 0.3 -> off
    plan = run([LIVING], {"living": ZoneState(room_temp=21.4, ac_ours_running=True)}, house)
    assert plan.zones["living"].ac_action == "off"
    # User turned the AC on by hand -> never touched
    plan = run([LIVING], {"living": ZoneState(room_temp=18, ac_user_controlled=True)}, house)
    assert plan.zones["living"].ac_action == "none"


def test_ours_ac_switched_off_when_boiler_takes_over():
    plan = run([LIVING], {"living": ZoneState(room_temp=18, ac_ours_running=True)}, HouseState(outdoor_temp=2))
    assert plan.source == "boiler"
    assert plan.zones["living"].ac_action == "off"


def test_trv_zone_demand_raises_boiler():
    states = {"house": ZoneState(schedule_on=False), "kitchen": ZoneState(room_temp=17, schedule_on=True)}
    plan = run([KITCHEN], states)
    assert plan.zones["kitchen"].trv_target == 21
    assert plan.zones["kitchen"].demand
    assert plan.boiler_target == 21


def test_trv_follow_boiler():
    plan = run([LIVING, KITCHEN_FOLLOW], {"living": ZoneState(room_temp=19)}, HouseState(outdoor_temp=12))
    assert plan.boiler_target == 16
    assert plan.zones["kitchen"].trv_target == 16


def test_zone_without_schedule_follows_house_schedule():
    states = {"house": ZoneState(schedule_on=False), "kitchen": ZoneState(room_temp=20)}
    plan = run([KITCHEN], states)
    assert plan.zones["kitchen"].target == 18
    assert plan.zones["kitchen"].reason == "schedule_eco"


def test_explain_languages():
    assert engine.explain("away", "ro") == "Nu e nimeni acasă"
    assert engine.explain("away", "en-GB") == "Nobody home"
    assert engine.explain("unknown_code", "de") == "unknown_code"
