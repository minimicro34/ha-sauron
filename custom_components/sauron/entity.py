"""Base entity class for SAURon meter entities."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_SUBSCRIPTION_ID, DOMAIN

if TYPE_CHECKING:
    from .coordinator import SauronCoordinator


class SauronMeterEntity(CoordinatorEntity["SauronCoordinator"]):
    """Base class for all SAURon entities tied to a water meter."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SauronCoordinator,
        translation_key: str,
    ) -> None:
        super().__init__(coordinator)
        subscription_id = coordinator.config_entry.data[CONF_SUBSCRIPTION_ID]
        self._attr_unique_id = f"{subscription_id}_{translation_key}"
        self._attr_translation_key = translation_key
        info = coordinator.data.meter_info if coordinator.data else None
        manufacturer = (info.meter_brand if info and info.meter_brand else None) or "SAUR"
        model = (info.meter_model if info and info.meter_model else None) or "Smart Meter"
        serial = info.meter_serial if info and info.meter_serial else None
        area = info.address if info and info.address else None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, subscription_id)},
            name="SAUR Water Meter",
            manufacturer=manufacturer,
            model=model,
            serial_number=serial,
            configuration_url="https://mon-espace.saurclient.fr",
            suggested_area=area,
        )

    @property
    def extra_state_attributes(self) -> dict | None:
        """Expose meter hardware metadata as entity attributes.

        This allows Lovelace 'type: attribute' rows to display serial_number,
        manufacturer and model without relying on device_attr() Jinja templates,
        which are not supported by the visual card editor.
        """
        data = self.coordinator.data
        if data is None:
            return None
        info = data.meter_info
        attrs: dict = {}
        if info.meter_serial:
            attrs["serial_number"] = info.meter_serial
        if info.meter_brand:
            attrs["manufacturer"] = info.meter_brand
        if info.meter_model:
            attrs["model"] = info.meter_model
        if info.meter_diameter:
            attrs["diameter"] = info.meter_diameter
        if info.telereleve_tech:
            attrs["telereleve"] = info.telereleve_tech
        if info.address:
            attrs["address"] = info.address
        return attrs or None
