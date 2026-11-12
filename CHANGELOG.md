# Changelog

## 0.1.2 - 2026-11-12

- An empty house at start-up is away right away, without waiting for the away delay

## 0.1.1 - 2026-11-12

- Fix: the "Air conditioner and prices" options page did not open
- Use the native climate temperature properties on Home Assistant 2026.11+

## 0.1.0 - 2026-11-12

First release.

- House with an optional main thermostat, schedule, presence, windows and comfort / eco / away / frost levels
- Zones with radiator valves (TRV), air conditioners, room sensor, windows and their own schedule
- Hybrid heating: picks the boiler or the air conditioners by price (gas vs electricity and the AC efficiency at the outdoor temperature) or by an outdoor threshold
- AC regulated on the room sensor, only the units HeatWise switched on are switched off by it; a person's manual use is respected
- Boiler demand from rooms with valves, valves that copy the main thermostat
- Manual changes kept for a set time or until the next schedule step
- Stop heating when it is warm outside
- Burner on / runtime today from a smart plug on the boiler
- Observe-only mode: shows what it would do without touching any device
- Decision sensor that explains every choice, English and Romanian
