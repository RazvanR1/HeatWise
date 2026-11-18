# Changelog

## 0.7.3 - 2026-11-18

- Fix: once the early start begins it now lasts until the schedule turns to comfort. Before, it stopped as soon as the room touched comfort and the main thermostat jumped between comfort and eco every few minutes

## 0.7.2 - 2026-11-18

- Fix: the early start before the schedule no longer turns on air conditioners (it started a bedroom AC at 4 in the morning). ACs warm a room in minutes, so they start at the schedule; the early start is for the boiler and radiator valves

## 0.7.1 - 2026-11-17

- Fix: the gas (and hot water) of a burner run still in progress was lost when Home Assistant restarted, e.g. after an update. It is now booked when Home Assistant stops, and every 5 minutes during a long run

## 0.7.0 - 2026-11-17

- Gas meter reading typed in by hand: a field in the panel and a `Gas meter reading` entity. Every reading corrects the gas estimate right away, without waiting for the supplier. An older index still shown by the supplier's sensor is ignored instead of being taken for a new meter
- Hot water counted apart: on a combi boiler, burner time while the main thermostat is not calling for heat is hot water. New hot water gas and cost sensors for today, this month and this year; the heating cost and the weekly report leave it out
- Gas counted by the plug power: a burn at a higher power than usual (the fan of a modulating boiler spins faster when it burns more) counts proportionally more. Meter readings calibrate against this weighted time
- Open windows guessed from a fast temperature drop (0.8 °C in 10 minutes by default), without window sensors. The room goes to frost protection until it warms up again, at most 30 minutes, with a notification. Uses room sensors and the wall thermostat only, never a valve's or an AC's own reading
- Valves that copy the main thermostat now close when their room has an open window

## 0.6.1 - 2026-11-15

- Rooms are linked to the house device the way Home Assistant 2026.11 expects (`via_device_id`), removing the deprecation warning

## 0.6.0 - 2026-11-15

- Warm on time: HeatWise learns how fast every room warms up and starts comfort early, so the room is warm when the schedule turns to comfort
- Coming home: with Proximity distance sensors the house goes back to comfort while someone is heading home
- Notifications to any notify service: window opened, a thermostat, valve or AC that stopped responding, and a weekly report on Sunday at 19:00 with gas, AC electricity and cost
- Language option for HeatWise only (automatic, English, Romanian), used by the panel, the decision texts and the notifications

## 0.5.1 - 2026-11-14

- Upgrading from 0.3/0.4: the gas already counted now fills this month and this year, with its cost, instead of starting from zero

## 0.5.0 - 2026-11-14

- Consumption and cost for today, this month and this year: gas (m³ and money), AC electricity while heating (kWh and money, from the ACs' power sensors) and the total cost of heating
- Costs are booked with the price in force at the time, so a price change does not rewrite the past
- Panel: "Consumption and cost" table with today / this month / this year
- New per-room option: AC power sensors

## 0.4.0 - 2026-11-14

- New "Boiler and air conditioner" page at setup and in Configure: boiler type, maximum heating power and efficiency, AC heating capacity and power input or energy class, all from the datasheet and all optional
- The cost comparison and the first guess of gas per burner hour use those numbers; anything left empty gets an average for that kind of device
- The heat source and gas sensors show which values are in use and where they came from

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
