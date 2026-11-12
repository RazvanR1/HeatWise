# HeatWise

**English** | [Română](README.ro.md)

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)
[![Validate](https://github.com/RazvanR1/HeatWise/actions/workflows/validate.yml/badge.svg)](https://github.com/RazvanR1/HeatWise/actions/workflows/validate.yml)
[![Tests](https://github.com/RazvanR1/HeatWise/actions/workflows/tests.yml/badge.svg)](https://github.com/RazvanR1/HeatWise/actions/workflows/tests.yml)

**Smart heating for Home Assistant that also decides _what_ to heat with.**

Most homes have more than one way to make heat: a gas boiler, radiator valves,
and air conditioners that can heat too. HeatWise runs all of them as one system.
On a mild day it heats the rooms with the air conditioners and lets the boiler
rest; when it gets cold, or gas is cheaper, it hands the job back to the boiler.
It works with any thermostat, valve or AC that Home Assistant can see.

## What it does

- **Picks the cheapest heat source.** Give it your gas and electricity prices
  (fixed numbers or any price sensor) and it compares gas against the AC's
  efficiency at the current outdoor temperature. No prices? It switches at an
  outdoor temperature you choose.
- **Regulates the AC on the room sensor**, not on the AC's own thermometer, and
  only switches off the units it switched on. If someone turns an AC on or off
  by hand, HeatWise leaves it alone for a while.
- **Knows who is home.** Comfort while someone is home, away level when the
  house is empty (after a delay you choose).
- **Follows your schedule.** Any Schedule helper (or input boolean): on =
  comfort, off = eco. Zones can have their own schedule or follow the house.
- **Rooms with radiator valves** get their own target and can call the boiler
  when they need heat, or simply copy the main thermostat.
- **Windows:** an open window lowers that zone to frost protection.
- **Manual changes are respected** for the time you choose, or until the next
  schedule step.
- **Warm outside:** stops heating above an outdoor temperature.
- **Boiler power plug (optional):** shows when the burner runs and its runtime today.
- **Observe-only mode:** turn off the *HeatWise control* switch and it shows
  what it would do without touching any device. Ideal for trying it next to
  your current setup.
- **Explains itself:** a *Decision* sensor says in plain words why the house is
  at the temperature it is. English and Romanian.

Everything except the name is optional: one thermostat is enough to start.

## Install

1. In HACS (the **Marketplace** in Home Assistant 2026.11+): ⋮ → **Custom
   repositories** → `https://github.com/RazvanR1/HeatWise`, type
   **Integration**. Install **HeatWise** and restart Home Assistant.
   Without HACS, copy `custom_components/heatwise` into `config/custom_components`.
2. **Settings → Devices & services → Add integration → HeatWise.**
3. Pick what you have: the main thermostat, an outdoor sensor, the people,
   a schedule. You can leave anything empty.
4. Open the integration's **Configure** menu to add zones (valves, air
   conditioners), prices and the boiler plug.

Requires Home Assistant 2025.6 or newer.

## Entities

| Entity | What it is |
|---|---|
| `climate.heatwise_<house>` | The house thermostat. Presets: schedule, comfort, eco, away, boost (1 h). Setting a temperature is a manual change. Off = frost protection. |
| `climate.heatwise_<zone>` | One per zone, same controls. |
| `sensor.…_decision` | Why HeatWise does what it does. |
| `sensor.…_main_thermostat_target` | What HeatWise asks from the main thermostat. |
| `sensor.…_heat_source` | `boiler` or `ac`, with the estimated COP and the cost of 1 kWh of heat from each. Only with an AC. |
| `sensor.…_burner_runtime_today` / `binary_sensor.…_burner_running` | Only with a boiler power plug. |
| `binary_sensor.…_anyone_home` | Presence as HeatWise sees it. Only with people. |
| `switch.…_heatwise_control` | Off = observe only. |
| `switch.…_heat_with_air_conditioners` | Allow or block AC heating. Only with an AC. |

## How the heat source is chosen

With both prices known:

```
cost of gas heat = gas price per kWh / boiler efficiency
cost of AC heat  = electricity price per kWh / COP(outdoor)
COP(outdoor)     = COP at 7 °C + 0.08 × (outdoor − 7), at least 1.5
```

HeatWise uses the AC when it is at least 5 % cheaper and goes back to the
boiler when it is 5 % more expensive, so it does not flip back and forth.
Below the "never use the AC below" temperature it always uses the boiler.
Gas billed in m³? 1 m³ ≈ 10.5 kWh.

While the ACs heat, the main thermostat drops to the away level so the boiler
does not start, and the valves in AC rooms close down.

## Moving from your own automations

1. Install HeatWise and turn **HeatWise control** off.
2. Watch the *Decision* sensor and the targets for a day or two.
3. Disable your old heating automations, then turn **HeatWise control** on.

## Support

If HeatWise is useful to you: [Buy me a coffee](https://buymeacoffee.com/razvanr1).

## License

MIT
