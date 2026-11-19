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
    assert plan.zones["kitchen"].trv_target == 22  # boosted so the valve opens
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


def test_valve_room_heats_while_acs_heat_and_boiler_fires():
    # mild day: living on the AC, the kitchen valve room still gets its 21 °C from the boiler
    states = {
        "house": ZoneState(room_temp=20.9),  # the wall thermostat reads the warm hall
        "living": ZoneState(room_temp=20.6),
        "kitchen": ZoneState(room_temp=18.9),
    }
    plan = run([LIVING, KITCHEN], states, HouseState(outdoor_temp=12))
    assert plan.source == "ac"
    assert plan.zones["kitchen"].trv_target == 22
    assert plan.zones["kitchen"].demand
    assert plan.boiler_target == 21.5  # above the hall reading, so the boiler starts


def test_valve_boost_has_a_ceiling():
    states = {"house": ZoneState(room_temp=24), "kitchen": ZoneState(room_temp=18)}
    plan = run([KITCHEN], states)
    assert plan.boiler_target == 22.5  # never more than 1.5 °C above what the room asks


def test_mould_floor_keeps_a_damp_room_warm():
    away = HouseState(anyone_home=False)
    st = ZoneState(room_temp=17, min_temp=19)
    assert engine.zone_target(KITCHEN, st, away, False, None) == (19, "mould")
    # comfort above the floor stays comfort
    home = HouseState(anyone_home=True)
    assert engine.zone_target(KITCHEN, ZoneState(min_temp=19), home, False, None) == (21, "home")
    # an open window still wins
    assert engine.zone_target(KITCHEN, ZoneState(window_open=True, min_temp=19), home, False, None)[1] == "window_open"


def test_valve_keeps_asking_until_the_target_is_reached():
    home = {"house": ZoneState(room_temp=21.5)}
    plan = run([KITCHEN], {**home, "kitchen": ZoneState(room_temp=20.8)})
    assert not plan.zones["kitchen"].demand and plan.zones["kitchen"].trv_target == 21
    plan = run([KITCHEN], {**home, "kitchen": ZoneState(room_temp=20.8, prev_demand=True)})
    assert plan.zones["kitchen"].demand and plan.zones["kitchen"].trv_target == 22
    plan = run([KITCHEN], {**home, "kitchen": ZoneState(room_temp=21.0, prev_demand=True)})
    assert not plan.zones["kitchen"].demand and plan.zones["kitchen"].trv_target == 21


def test_no_ac_start_just_before_comfort_ends():
    ac = ZoneConfig("bed", "Bedroom", has_ac=True)
    states = {"bed": ZoneState(room_temp=19, schedule_on=True, comfort_ending=True)}
    plan = run([ac], states, HouseState(outdoor_temp=12))
    assert plan.zones["bed"].ac_action != "heat"
    # an AC already running keeps going until the end
    states = {"bed": ZoneState(room_temp=19, schedule_on=True, comfort_ending=True, ac_ours_running=True)}
    plan = run([ac], states, HouseState(outdoor_temp=12))
    assert plan.zones["bed"].ac_action == "heat"


def test_boiler_level_while_the_acs_heat():
    from custom_components.heatwise import engine as e

    house = e.ZoneConfig("house", "Home", e.Temps(comfort=21, eco=19, away=17), is_house=True)
    living = e.ZoneConfig("l1", "Living", e.Temps(comfort=21, eco=17, away=17), has_ac=True)
    states = {"house": e.ZoneState(room_temp=19, schedule_on=False), "l1": e.ZoneState(room_temp=18, schedule_on=True)}
    hs = e.HouseState(anyone_home=True, outdoor_temp=12)
    plan = e.evaluate(house, [living], states, hs, e.HybridConfig(mode=e.HYBRID_AC))
    assert plan.boiler_target == 17
    plan = e.evaluate(house, [living], states, hs, e.HybridConfig(mode=e.HYBRID_AC, boiler_while_ac=18))
    assert plan.boiler_target == 18
    hs_away = e.HouseState(anyone_home=False, outdoor_temp=12)
    plan = e.evaluate(house, [living], states, hs_away, e.HybridConfig(mode=e.HYBRID_AC, boiler_while_ac=18))
    assert plan.boiler_target == 17  # never above what the house asks for


def test_valve_room_does_not_overheat_the_house_past_the_ceiling():
    from custom_components.heatwise import engine as e

    house = e.ZoneConfig("house", "Home", e.Temps(comfort=21, eco=19, away=17), is_house=True)
    kitchen = e.ZoneConfig("k", "Kitchen", e.Temps(comfort=21, eco=19, away=17), has_trv=True, trv_follow_boiler=False)
    states = {"house": e.ZoneState(room_temp=22.0, schedule_on=True), "k": e.ZoneState(room_temp=20.6, schedule_on=True)}
    hs = e.HouseState(anyone_home=True, outdoor_temp=5)
    plan = e.evaluate(house, [kitchen], states, hs, e.HybridConfig(mode=e.HYBRID_BOILER))
    assert plan.boiler_target == 22.5  # no limit: pushed above the warm wall thermostat
    plan = e.evaluate(house, [kitchen], states, hs, e.HybridConfig(mode=e.HYBRID_BOILER, valve_ceiling=21))
    assert plan.boiler_target == 21
    assert plan.zones["k"].trv_target == 22  # the valve still opens if the boiler runs for the house
