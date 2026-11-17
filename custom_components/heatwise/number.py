"""HeatWise numbers: the gas meter index read by hand."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HeatWiseConfigEntry
from .const import DOMAIN, HOUSE_ZONE_ID
from .controller import MeterReadingError
from .entity import HeatWiseEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: HeatWiseConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    controller = entry.runtime_data
    if controller.has_power:
        async_add_entities([GasMeterReading(controller)])


class GasMeterReading(HeatWiseEntity, NumberEntity):
    """Type in the index of the gas meter whenever you read it.

    Every reading corrects the gas estimate, without waiting for the supplier.
    """

    _attr_translation_key = "gas_meter_reading"
    _attr_icon = "mdi:meter-gas-outline"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = 9_999_999
    _attr_native_step = 0.001
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS

    def __init__(self, controller) -> None:
        super().__init__(controller, HOUSE_ZONE_ID, "gas_meter_reading")

    @property
    def native_value(self) -> float | None:
        return self.controller.last_meter_reading

    @property
    def extra_state_attributes(self) -> dict:
        c = self.controller
        base = c.gas_baseline or {}
        return {
            "calibrations": c.gas_calibrations,
            "counted_from": base.get("meter"),
            "counted_from_at": base.get("at"),
            "counted_from_source": base.get("source"),
            "last_typed_reading_at": c.last_manual_reading[1] if c.last_manual_reading else None,
        }

    async def async_set_native_value(self, value: float) -> None:
        try:
            self.controller.async_manual_meter_reading(float(value))
        except MeterReadingError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key=err.key,
                translation_placeholders=err.placeholders,
            ) from err
        self.async_write_ha_state()
