"""Smart start helpers and the new engine rules."""

from datetime import UTC, datetime, timedelta

from custom_components.heatwise import engine
from custom_components.heatwise.smart import (
    ArrivalWatcher,
    learn_rate,
    preheat_due,
    weekly_report,
)

NOW = datetime(2026, 11, 16, 5, 0, tzinfo=UTC)


def test_preheat_starts_when_the_lead_time_is_reached() -> None:
    # 2 °C below comfort at 1.5 °C/h needs 80 minutes
    assert not preheat_due(NOW + timedelta(minutes=90), NOW, 2.0, 1.5, 180)
    assert preheat_due(NOW + timedelta(minutes=75), NOW, 2.0, 1.5, 180)
    assert not preheat_due(NOW + timedelta(minutes=75), NOW, 0.0, 1.5, 180)
    assert not preheat_due(NOW - timedelta(minutes=5), NOW, 2.0, 1.5, 180)
    # capped by the maximum
    assert not preheat_due(NOW + timedelta(minutes=50), NOW, 10.0, 1.0, 45)


def test_learn_rate_smooths_and_rejects_noise() -> None:
    assert learn_rate(None, 1.3, 53 / 60) == 1.47
    assert learn_rate(1.5, 1.0, 1.0) == 1.35
    assert learn_rate(None, 0.2, 1.0) is None
    assert learn_rate(None, 3.0, 0.1) is None


def test_arrival_needs_real_progress_towards_home() -> None:
    watcher = ArrivalWatcher()
    s = "sensor.home_a_distance"
    assert ArrivalWatcher.direction_entity(s) == "sensor.home_a_direction_of_travel"
    assert ArrivalWatcher.to_km("2500", "m") == 2.5
    # at work, 12 km away, not moving
    assert not watcher.update({s: (12.0, "stationary")}, 15, False, NOW)
    # small wobble towards home is not enough
    assert not watcher.update({s: (11.6, "towards")}, 15, False, NOW)
    # driving home
    assert watcher.update({s: (10.5, "towards")}, 15, False, NOW)
    # latched even if the direction flaps
    assert watcher.update({s: (10.0, "away_from")}, 15, False, NOW + timedelta(minutes=10))
    # once home everything resets
    assert not watcher.update({s: (0.0, "arrived")}, 15, True, NOW + timedelta(minutes=20))
    assert watcher.until is None and not watcher.farthest


def test_arrival_ignores_far_away() -> None:
    watcher = ArrivalWatcher()
    s = "sensor.home_a_distance"
    watcher.update({s: (300.0, "stationary")}, 15, False, NOW)
    assert not watcher.update({s: (200.0, "towards")}, 15, False, NOW)


def test_engine_preheat_and_arriving_reasons() -> None:
    cfg = engine.ZoneConfig("house", "Home", is_house=True)
    house = engine.HouseState(anyone_home=True)
    st = engine.ZoneState(schedule_on=False, preheat=True)
    assert engine.zone_target(cfg, st, house, False, None) == (21.0, "preheat")
    away = engine.HouseState(anyone_home=False, arriving=True)
    st = engine.ZoneState(schedule_on=True)
    assert engine.zone_target(cfg, st, away, False, None) == (21.0, "arriving")
    away.arriving = False
    assert engine.zone_target(cfg, st, away, False, None) == (16.0, "away")
    assert engine.explain("arriving", "ro") == "Cineva vine spre casă"


def test_weekly_report_in_romanian() -> None:
    text = weekly_report(
        {"gas_m3": 23.45, "gas_cost": 66.1, "burner_h": 13.8, "ac_kwh": 2.0, "ac_cost": 2.32},
        {"gas_cost": 70.0, "ac_cost": 0.0},
        "ro",
        "RON",
        True,
        True,
    )
    assert "Gaz: 23,4 m³ (66,10 RON)" in text or "Gaz: 23,5 m³ (66,10 RON)" in text
    assert "Total încălzire: 68,42 RON" in text
    assert "Săptămâna trecută: 70,00 RON" in text
