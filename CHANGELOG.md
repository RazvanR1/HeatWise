# Changelog

## 0.3.0 - 2026-11-13

- Gas use and cost: estimated from the burner time (m³ per burner hour), with sensors for today, the running total (Energy dashboard) and today's cost
- Learns the real m³ per burner hour from a gas meter index sensor (supplier integration or pulse counter); a meter replacement only resets the baseline
- Panel: gas today tile with the cost

## 0.2.1 - 2026-11-13

- Panel: fewer time labels on the chart on phones so they do not overlap
- README: screenshots of the panel

## 0.2.0 - 2026-11-13

- New HeatWise panel in the sidebar: the house and every room with temperatures, targets and presets, why HeatWise decided what it did, the heat source, burner time, the AC/gas cost comparison and a 24 hour chart. Switch between "in control" and "observe only" from it. English and Romanian

## 0.1.3 - 2026-11-12

- The away delay starts only when someone actually leaves home; an empty house at start-up is away right away

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
