"""HeatWise sensors."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTemperature, UnitOfTime, UnitOfVolume
from homeassistant.util import dt as dt_util
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HeatWiseConfigEntry, engine
from .const import HOUSE_ZONE_ID
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
        entities += [
            BurnerRuntimeSensor(controller),
            GasTodaySensor(controller),
            GasTotalSensor(controller),
            GasCostTodaySensor(controller),
            GasRateSensor(controller),
        ]
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
            "zones": {
                self.controller.zone_name(zid): engine.explain(zp.reason, self.controller.language)
                for zid, zp in plan.zones.items()
            },
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
        return {
            "reason": plan.source_reason,
            "estimated_cop": round(plan.cop, 2) if plan.cop else None,
            "gas_cost_per_kwh_heat": round(plan.cost_gas, 4) if plan.cost_gas else None,
            "ac_cost_per_kwh_heat": round(plan.cost_ac, 4) if plan.cost_ac else None,
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


class GasTodaySensor(HeatWiseEntity, SensorEntity):
    """Estimated gas burned today (burner time × m³ per burner hour)."""

    _attr_translation_key = "gas_today"
    _attr_device_class = SensorDeviceClass.GAS
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
    _attr_suggested_display_precision = 2

    def __init__(self, controller) -> None:
        super().__init__(controller, HOUSE_ZONE_ID, "gas_today")

    @property
    def native_value(self) -> float:
        return round(self.controller.gas_today_live, 3)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self.controller
        return {"energy_kwh": round(c.gas_today_live * c.gas_kwh_per_m3, 2), "estimated": True}


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


class GasCostTodaySensor(HeatWiseEntity, SensorEntity):
    """What today's gas cost, from the gas price per kWh."""

    _attr_translation_key = "gas_cost_today"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:cash"

    def __init__(self, controller) -> None:
        super().__init__(controller, HOUSE_ZONE_ID, "gas_cost_today")
        self._attr_native_unit_of_measurement = controller.hass.config.currency

    @property
    def available(self) -> bool:
        return self.controller.gas_price_kwh is not None

    @property
    def native_value(self) -> float | None:
        cost = self.controller.gas_cost_today
        return round(cost, 2) if cost is not None else None

    @property
    def last_reset(self):
        return dt_util.start_of_local_day()


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
            "calibrations": c.gas_calibrations,
            "last_meter_reading": (c.gas_baseline or {}).get("meter"),
            "last_reading_at": (c.gas_baseline or {}).get("at"),
            "burner_hours_total": round(c.burner_total_live_seconds / 3600, 2),
        }
