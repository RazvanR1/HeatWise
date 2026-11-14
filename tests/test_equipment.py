"""Datasheet numbers -> engine values, with averages as the fallback."""

import importlib.util
import pathlib
import sys
import types

BASE = pathlib.Path(__file__).parents[1] / "custom_components" / "heatwise"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"hw_pkg.{name}", BASE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"hw_pkg.{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


pkg = types.ModuleType("hw_pkg")
pkg.__path__ = [str(BASE)]
sys.modules["hw_pkg"] = pkg
_load("const")
eq = _load("equipment")


def test_everything_unknown_uses_averages():
    r = eq.resolve({})
    assert (r.boiler_efficiency, r.boiler_efficiency_source) == (0.92, "average")
    assert (r.cop_at_7, r.cop_source) == (3.5, "average")
    assert (r.gas_rate_default, r.gas_rate_source) == (1.5, "average")


def test_razvan_beretta_and_gree():
    r = eq.resolve(
        {
            "boiler_type": "condensing",
            "boiler_power_kw": 20,
            "boiler_efficiency_pct": 97.5,
            "gas_kwh_per_m3": 10.767,
            "ac_heat_w": 3399,
            "ac_input_w": 916,
        }
    )
    assert r.boiler_efficiency == 0.879 and r.boiler_efficiency_source == "datasheet"
    assert r.cop_at_7 == 3.71 and r.cop_source == "datasheet"
    assert abs(r.gas_rate_default - 1.69) < 0.01 and r.gas_rate_source == "boiler_power"


def test_type_and_energy_class_fallbacks():
    r = eq.resolve({"boiler_type": "conventional", "ac_energy_class": "A+"})
    assert r.boiler_efficiency == 0.84 and r.boiler_efficiency_source == "boiler_type"
    assert r.cop_at_7 == 3.72 and r.cop_source == "energy_class"


def test_older_manual_values_still_count():
    r = eq.resolve({"boiler_efficiency": 0.9, "cop_at_7": 3.7, "gas_rate": 1.7})
    assert r.boiler_efficiency == 0.9 and r.boiler_efficiency_source == "manual"
    assert r.cop_at_7 == 3.7 and r.cop_source == "manual"
    assert r.gas_rate_default == 1.7 and r.gas_rate_source == "manual"
