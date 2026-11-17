"""Unit tests for the burner bookkeeping and the window guess."""

from datetime import UTC, datetime, timedelta

from custom_components.heatwise import engine
from custom_components.heatwise.burner import (
    learned_rate,
    meter_reading_action,
    power_weight,
    split_hot_water,
    update_power_ref,
)
from custom_components.heatwise.smart import WindowDetector, weekly_report

T0 = datetime(2026, 11, 17, 6, 0, tzinfo=UTC)


def test_power_weight_counts_higher_fan_power_more() -> None:
    assert power_weight(None, 60) == 1.0
    assert power_weight(60, None) == 1.0
    assert power_weight(75, 60) == 1.25
    assert power_weight(600, 60) == 1.6  # capped
    assert power_weight(10, 60) == 0.5  # capped


def test_power_reference_follows_recent_burns() -> None:
    assert update_power_ref(None, 62, 600) == 62
    assert update_power_ref(60, None, 600) == 60
    # one hour at 75 W moves a 60 W reference a tenth of the way
    assert abs(update_power_ref(60, 75, 3600) - 61.5) < 0.001
    assert update_power_ref(60, 75, 20 * 3600) == 75


def test_split_hot_water() -> None:
    end = T0 + timedelta(minutes=17)
    # heat call on: all heating
    assert split_hot_water(T0, end, True, None, 90) == (17 * 60, 0.0)
    # no heat call since long ago: all hot water (the 06:02 shower)
    assert split_hot_water(T0, end, False, T0 - timedelta(hours=1), 90) == (0.0, 17 * 60)
    # never seen a heat call
    assert split_hot_water(T0, end, False, None, 90) == (0.0, 17 * 60)
    # the heat call ended at the start of the slice (22:00): 90 s of heating, the rest is a shower
    assert split_hot_water(T0, end, False, T0, 90) == (90, 17 * 60 - 90)


def test_meter_readings_typed_and_from_the_supplier() -> None:
    assert meter_reading_action(None, 290, "sensor") == "baseline"
    manual = {"meter": 305.0, "source": "manual"}
    supplier = {"meter": 290.0, "source": "sensor"}
    assert meter_reading_action(manual, 306, "sensor") == "calibrate"
    # the supplier still shows the index sent last month: an old reading, not a new meter
    assert meter_reading_action(manual, 290, "sensor") == "ignore"
    # a typo below the last reading is refused, a new meter (much lower) starts over
    assert meter_reading_action(supplier, 280, "manual") == "too_low"
    assert meter_reading_action(supplier, 3, "manual") == "baseline"
    assert meter_reading_action(supplier, 3, "sensor") == "baseline"


def test_learned_rate() -> None:
    assert learned_rate(None, 0.2, 10) == (None, "wait")
    assert learned_rate(None, 5, 1) == (None, "wait")
    assert learned_rate(None, 50, 4) == (None, "implausible")
    assert learned_rate(None, 6, 4) == (1.5, "learned")
    assert learned_rate(1.0, 6, 4) == (1.25, "learned")


def _feed(det, key, temps, step_min=1, start=T0, **kw):
    params = {"drop": 0.8, "minutes": 10, "hold_minutes": 30, **kw}
    result = []
    for i, temp in enumerate(temps):
        result.append(det.update(key, temp, start + timedelta(minutes=i * step_min), **params))
    return result


def test_window_guess_ignores_normal_cooling() -> None:
    det = WindowDetector()
    # the biggest drop in a week of real data: 0.5 °C in 15 minutes
    temps = [21.5, 21.5, 21.4, 21.4, 21.3, 21.3, 21.2, 21.2, 21.1, 21.1, 21.0, 21.0, 21.0]
    assert not any(_feed(det, "living", temps))


def test_window_guess_opens_and_closes() -> None:
    det = WindowDetector()
    states = _feed(det, "living", [21.0, 21.0, 20.7, 20.4, 20.1, 19.9, 19.8, 19.8, 19.9, 20.2])
    assert states[:4] == [False, False, False, False]
    assert states[4] is True  # 0.9 °C in 4 minutes
    assert states[7] is True
    assert states[-1] is False  # warming again: window closed
    # a closed window needs a new drop to count again
    assert det.update("living", 20.0, T0 + timedelta(minutes=11), 0.8, 10, 30) is False


def test_window_guess_gives_up_after_the_hold_time() -> None:
    det = WindowDetector()
    states = _feed(det, "bedroom", [20.0, 19.0] + [18.5] * 20, step_min=2, hold_minutes=30)
    assert states[1] is True
    assert states[-1] is False


def test_engine_window_drop_and_follow_valve() -> None:
    house = engine.ZoneConfig("house", "Home", is_house=True)
    kitchen = engine.ZoneConfig("k", "Kitchen", has_trv=True, trv_follow_boiler=True)
    states = {
        "house": engine.ZoneState(room_temp=20),
        "k": engine.ZoneState(room_temp=19, window_detected=True),
    }
    plan = engine.evaluate(house, [kitchen], states, engine.HouseState(anyone_home=True), engine.HybridConfig())
    assert plan.zones["k"].reason == "window_drop"
    assert plan.zones["k"].trv_target == 7.0  # the valve closes even though it copies the boiler
    assert plan.boiler_target == 21.0
    assert "fereastră" in engine.explain("window_drop", "ro")


def test_weekly_report_with_hot_water() -> None:
    week = {"gas_m3": 20.0, "gas_cost": 60.0, "burner_h": 12.0, "dhw_m3": 4.0, "dhw_cost": 12.0, "dhw_h": 2.0}
    text = weekly_report(week, {"gas_cost": 50.0, "dhw_cost": 10.0}, "ro", "RON", True, False, True)
    assert "Gaz pentru încălzire: 16,0 m³ (48,00 RON), arzătorul a mers 10,0 h" in text
    assert "Total încălzire: 48,00 RON" in text
    assert "Apă caldă: 4,0 m³ gaz (12,00 RON)" in text
    assert "Săptămâna trecută: 40,00 RON" in text
