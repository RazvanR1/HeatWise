"""HeatWise sensors."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfEnergy,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import HeatWiseConfigEntry, engine
from .const import CONF_OUTDOOR, HDD_BASE, HOUSE_ZONE_ID, PERIODS
from .entity import HeatWiseEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: HeatWiseConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    controller = entry.runtime_data
    entities: list[SensorEntity] = [
        DecisionSensor(controller),
        BoilerTargetSensor(controller),
    ]
    if controller.has_ac:
        entities.append(HeatSourceSensor(controller))
    if controller.has_power:
        entities += [BurnerRuntimeSensor(controller), GasTotalSensor(controller), GasRateSensor(controller)]
        entities += [PeriodSensor(controller, "gas", p) for p in PERIODS]
        entities += [PeriodSensor(controller, "gas_cost", p) for p in PERIODS]
        if controller.split_hot_water:
            entities += [PeriodSensor(controller, "hot_water", p) for p in PERIODS]
            entities += [PeriodSensor(controller, "hot_water_cost", p) for p in PERIODS]
    if controller.has_ac_power:
        entities += [PeriodSensor(controller, "ac_energy", p) for p in PERIODS]
        entities += [PeriodSensor(controller, "ac_cost", p) for p in PERIODS]
    if controller.has_power or controller.has_ac_power:
        entities += [PeriodSensor(controller, "heating_cost", p) for p in PERIODS]
    if controller.has_power and controller.config.get(CONF_OUTDOOR):
        entities.append(EfficiencySensor(controller))
    async_add_entities(entities)


class DecisionSensor(HeatWiseEntity, SensorEntity):
    """Why HeatWise does what it does, in plain words."""

    _attr_translation_key = "decision"
    _attr_icon = "mdi:head-lightbulb-outline"

    def __init__(self, controller) -> None:
        super().__init__(controller, HOUSE_ZONE_ID, "decision")

    @property
    def native_value(self) -> str | None:
        text = self.controller.explanation()
        return text[:255] if text else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        plan = self.controller.plan
        if plan is None:
            return {}
        return {
            "house_reason": plan.house_reason,
            "source_reason": plan.source_reason,
            "warm_outside": plan.warm_off,
            "anyone_home": self.controller.anyone_home,
            "observing_only": not self.controller.control_enabled,
            "on_the_way_home": self.controller.arrival.until is not None,
            "window_suspected": [
                self.controller.zone_name(zid) for zid, on in self.controller.windows_detected.items() if on
            ],
            "mould_risk": [
                self.controller.zone_name(zid) for zid, on in self.controller.mould_risk.items() if on
            ],
            "good_time_to_air": self.controller.air_rooms,
            "preheating": [
                self.controller.zone_name(zid) for zid, on in self.controller.preheating.items() if on
            ],
            "heat_up_rate": {
                self.controller.zone_name(zid): rate for zid, rate in self.controller.heat_rates.items()
            },
            "zones": {
                self.controller.zone_name(zid): engine.explain(zp.reason, self.controller.language)
                for zid, zp in plan.zones.items()
            },
        }


class EfficiencySensor(HeatWiseEntity, SensorEntity):
    """Burner hours for heating per heating degree-day this week: lower is better."""

    _attr_translation_key = "efficiency"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "h/°C·d"
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:speedometer"

    def __init__(self, controller) -> None:
        super().__init__(controller, HOUSE_ZONE_ID, "efficiency")

    @property
    def native_value(self) -> float | None:
        return self.controller.efficiency()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self.controller
        last = c.last_week or {}
        return {
            "degree_days_this_week": round(c.period_value("hdd", "week"), 1),
            "degree_days_today": round(c.period_value("hdd", "today"), 1),
            "last_week": c.efficiency(last) if last else None,
            "degree_days_last_week": round(last.get("hdd", 0.0), 1) if last else None,
            "base_temperature": HDD_BASE,
        }


class BoilerTargetSensor(HeatWiseEntity, SensorEntity):
    """The temperature HeatWise asks from the main thermostat."""

    _attr_translation_key = "boiler_target"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, controller) -> None:
        super().__init__(controller, HOUSE_ZONE_ID, "boiler_target")
        self._attr_native_unit_of_measurement = (
            controller.hass.config.units.temperature_unit or UnitOfTemperature.CELSIUS
        )

    @property
    def native_value(self) -> float | None:
        plan = self.controller.plan
        return plan.boiler_target if plan else None


class HeatSourceSensor(HeatWiseEntity, SensorEntity):
    """Boiler or air conditioner, with the cost comparison."""

    _attr_translation_key = "heat_source"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [engine.SOURCE_BOILER, engine.SOURCE_AC]
    _attr_icon = "mdi:swap-horizontal"

    def __init__(self, controller) -> None:
        super().__init__(controller, HOUSE_ZONE_ID, "heat_source")

    @property
    def native_value(self) -> str | None:
        plan = self.controller.plan
        return plan.source if plan else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        plan = self.controller.plan
        if plan is None:
            return {}
        eq = self.controller.equipment
        return {
            "reason": plan.source_reason,
            "estimated_cop": round(plan.cop, 2) if plan.cop else None,
            "gas_cost_per_kwh_heat": round(plan.cost_gas, 4) if plan.cost_gas else None,
            "ac_cost_per_kwh_heat": round(plan.cost_ac, 4) if plan.cost_ac else None,
            "boiler_efficiency": eq.boiler_efficiency,
            "boiler_efficiency_from": eq.boiler_efficiency_source,
            "ac_cop_at_7": eq.cop_at_7,
            "ac_cop_from": eq.cop_source,
            "boiler_model": self.controller.config.get("boiler_model"),
            "ac_model": self.controller.config.get("ac_model"),
        }


class BurnerRuntimeSensor(HeatWiseEntity, SensorEntity):
    """How long the boiler burner ran today (from the power plug)."""

    _attr_translation_key = "burner_runtime"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_suggested_display_precision = 2

    def __init__(self, controller) -> None:
        super().__init__(controller, HOUSE_ZONE_ID, "burner_runtime")

    @property
    def native_value(self) -> float:
        return round(self.controller.burner_runtime_seconds / 3600, 3)


class GasTotalSensor(HeatWiseEntity, SensorEntity):
    """Running total of the estimated gas use, for the Energy dashboard."""

    _attr_translation_key = "gas_total"
    _attr_device_class = SensorDeviceClass.GAS
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
    _attr_suggested_display_precision = 2

    def __init__(self, controller) -> None:
        super().__init__(controller, HOUSE_ZONE_ID, "gas_total")

    @property
    def native_value(self) -> float:
        return round(self.controller.gas_total_live, 3)


class GasRateSensor(HeatWiseEntity, SensorEntity):
    """m³ of gas per burner hour, learned from the gas meter readings."""

    _attr_translation_key = "gas_rate"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = "m³/h"
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:gauge"

    def __init__(self, controller) -> None:
        super().__init__(controller, HOUSE_ZONE_ID, "gas_rate")

    @property
    def native_value(self) -> float:
        return round(self.controller.gas_rate, 3)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self.controller
        return {
            "learned_from_meter": c.gas_rate_learned is not None,
            "starting_value_from": c.equipment.gas_rate_source,
            "calibrations": c.gas_calibrations,
            "last_meter_reading": (c.gas_baseline or {}).get("meter"),
            "last_reading_at": (c.gas_baseline or {}).get("at"),
            "burner_hours_total": round(c.burner_total_live_seconds / 3600, 2),
            "weighted_by_plug_power": c.gas_by_power,
            "usual_burner_power_w": c.power_ref,
            "burner_power_now_w": c.burner_power,
            "hot_water_counted_apart": c.split_hot_water,
        }


_METRICS = {
    # kind: (controller metric, device class, unit or None for currency, needs price)
    "gas": ("gas_m3", SensorDeviceClass.GAS, UnitOfVolume.CUBIC_METERS, None),
    "gas_cost": ("gas_cost", SensorDeviceClass.MONETARY, None, "gas"),
    "hot_water": ("dhw_m3", SensorDeviceClass.GAS, UnitOfVolume.CUBIC_METERS, None),
    "hot_water_cost": ("dhw_cost", SensorDeviceClass.MONETARY, None, "gas"),
    "ac_energy": ("ac_kwh", SensorDeviceClass.ENERGY, UnitOfEnergy.KILO_WATT_HOUR, None),
    "ac_cost": ("ac_cost", SensorDeviceClass.MONETARY, None, "electricity"),
    "heating_cost": (None, SensorDeviceClass.MONETARY, None, "any"),
}


def _period_start(period: str):
    start = dt_util.start_of_local_day()
    if period == "month":
        return start.replace(day=1)
    if period == "year":
        return start.replace(month=1, day=1)
    return start


class PeriodSensor(HeatWiseEntity, SensorEntity):
    """Consumption or cost for today, this month or this year."""

    _attr_suggested_display_precision = 2

    def __init__(self, controller, kind: str, period: str) -> None:
        super().__init__(controller, HOUSE_ZONE_ID, f"{kind}_{period}")
        self._kind = kind
        self._period = period
        metric, device_class, unit, price = _METRICS[kind]
        self._metric = metric
        self._price = price
        self._attr_translation_key = f"{kind}_{period}"
        self._attr_device_class = device_class
        if device_class == SensorDeviceClass.MONETARY:
            self._attr_state_class = SensorStateClass.TOTAL
            self._attr_native_unit_of_measurement = controller.hass.config.currency
        else:
            self._attr_state_class = SensorStateClass.TOTAL_INCREASING
            self._attr_native_unit_of_measurement = unit

    @property
    def available(self) -> bool:
        c = self.controller
        if self._price == "gas":
            return c.gas_price_kwh is not None
        if self._price == "electricity":
            return c.electricity_price_kwh is not None
        if self._price == "any":
            return c.gas_price_kwh is not None or c.electricity_price_kwh is not None
        return True

    @property
    def native_value(self) -> float:
        c = self.controller
        if self._kind == "heating_cost":
            return round(c.heating_cost(self._period), 2)
        return round(c.period_value(self._metric, self._period), 3)

    @property
    def last_reset(self):
        if self._attr_state_class == SensorStateClass.TOTAL:
            return _period_start(self._period)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self.controller
        if self._kind in ("gas", "hot_water"):
            m3 = c.period_value(self._metric, self._period)
            attrs = {"energy_kwh": round(m3 * c.gas_kwh_per_m3, 2), "estimated": True}
            if self._kind == "gas" and c.split_hot_water:
                hot = c.period_value("dhw_m3", self._period)
                attrs["heating_m3"] = round(max(m3 - hot, 0.0), 3)
                attrs["hot_water_m3"] = round(hot, 3)
            return attrs
        if self._kind == "heating_cost" and c.split_hot_water:
            return {"hot_water_excluded": True}
        return {}
