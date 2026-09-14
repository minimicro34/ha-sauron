"""Sensor platform for the SAURon integration."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime, UnitOfVolume

from .const import DOMAIN
from .coordinator import _data_age_hours
from .entity import SauronMeterEntity

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import SauronCoordinator

PARALLEL_UPDATES = 0

METER_SENSORS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="estimated_index",
        translation_key="estimated_index",
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        suggested_display_precision=3,
    ),
    SensorEntityDescription(
        key="daily_liters",
        translation_key="daily_liters",
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="daily_date",
        translation_key="daily_date",
        device_class=SensorDeviceClass.DATE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="weekly_m3",
        translation_key="weekly_m3",
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        suggested_display_precision=3,
    ),
    SensorEntityDescription(
        key="monthly_m3",
        translation_key="monthly_m3",
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        suggested_display_precision=3,
    ),
    SensorEntityDescription(
        key="yearly_m3",
        translation_key="yearly_m3",
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        suggested_display_precision=3,
    ),
    SensorEntityDescription(
        key="last_index",
        translation_key="last_index",
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=3,
    ),
    SensorEntityDescription(
        key="last_index_date",
        translation_key="last_index_date",
        device_class=SensorDeviceClass.DATE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="data_freshness_hours",
        translation_key="data_freshness_hours",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.HOURS,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="last_successful_poll",
        translation_key="last_successful_poll",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="meter_serial",
        translation_key="meter_serial",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="meter_brand",
        translation_key="meter_brand",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="meter_model",
        translation_key="meter_model",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="meter_diameter",
        translation_key="meter_diameter",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="telereleve_tech",
        translation_key="telereleve_tech",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


class SauronSensor(SauronMeterEntity, SensorEntity):
    """A SAURon sensor entity backed by a SauronData snapshot."""

    entity_description: SensorEntityDescription

    def __init__(
        self, coordinator: SauronCoordinator, description: SensorEntityDescription
    ) -> None:
        super().__init__(
            coordinator,
            translation_key=description.translation_key or description.key,
        )
        self.entity_description = description

    @property
    def native_value(self) -> float | date | datetime | str | None:
        data = self.coordinator.data
        key = self.entity_description.key

        if key == "last_index":
            return data.latest_reading.value_m3
        if key == "estimated_index":
            return data.estimated_index_m3
        if key == "last_index_date":
            return data.latest_reading.reading_date
        if key == "daily_liters":
            return data.daily_liters
        if key == "daily_date":
            return data.daily_date
        if key == "weekly_m3":
            return data.weekly_m3
        if key == "monthly_m3":
            return data.monthly_m3
        if key == "yearly_m3":
            return data.yearly_m3
        if key == "data_freshness_hours":
            return _data_age_hours(data.daily_date, datetime.now(UTC))
        if key == "last_successful_poll":
            return data.latest_reading.fetched_at
        if key == "meter_serial":
            return data.meter_info.meter_serial
        if key == "meter_brand":
            return data.meter_info.meter_brand
        if key == "meter_model":
            return data.meter_info.meter_model
        if key == "meter_diameter":
            return data.meter_info.meter_diameter
        if key == "telereleve_tech":
            return data.meter_info.telereleve_tech
        return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Register sensor entities."""
    coordinator: SauronCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(SauronSensor(coordinator, desc) for desc in METER_SENSORS)
