"""Expiry notification sensor for Simple Inventory."""

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import Event, HomeAssistant, callback

from ..const import DOMAIN
from ..coordinator import SimpleInventoryCoordinator

_LOGGER = logging.getLogger(__name__)


class ExpiryNotificationSensor(SensorEntity):
    """Sensor to track items nearing expiry for a specific inventory."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: SimpleInventoryCoordinator,
        inventory_id: str,
        inventory_name: str,
    ) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self.coordinator = coordinator
        self.inventory_id = inventory_id
        self.inventory_name = inventory_name
        self._attr_name = f"{inventory_name} Items Expiring Soon"
        self._attr_unique_id = f"simple_inventory_expiring_items_{
            inventory_id}"
        self._attr_icon = "mdi:calendar-alert"
        self._attr_native_unit_of_measurement = "items"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, inventory_id)},
            "name": inventory_name,
        }
        self._update_data()

    async def async_added_to_hass(self) -> None:
        """Register callbacks for inventory updates."""
        self.async_on_remove(
            self.hass.bus.async_listen(
                f"{DOMAIN}_updated_{self.inventory_id}", self._handle_update
            )
        )

        self.async_on_remove(
            self.hass.bus.async_listen(f"{DOMAIN}_updated", self._handle_update)
        )

        if hasattr(self.coordinator, "async_add_listener"):
            self.async_on_remove(
                self.coordinator.async_add_listener(
                    self._handle_coordinator_update
                )
            )

    @callback
    def _handle_update(self, _event: Event) -> None:
        """Handle inventory updates."""
        self._update_data()
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle coordinator updates."""
        self._update_data()
        self.async_write_ha_state()

    def _update_data(self) -> None:
        """Update sensor data for this specific inventory."""
        all_items = self.coordinator.get_items_expiring_soon(self.inventory_id)

        expired_items = [
            item for item in all_items if item["days_until_expiry"] < 0
        ]
        expiring_items = [
            item for item in all_items if item["days_until_expiry"] >= 0
        ]

        for item in all_items:
            item["inventory"] = self.inventory_name

        total_items = len(all_items)
        self._attr_native_value = total_items
        self._attr_extra_state_attributes = {
            "expiring_items": expiring_items,
            "expired_items": expired_items,
            "inventory_id": self.inventory_id,
            "inventory_name": self.inventory_name,
            "total_expiring": len(expiring_items),
            "total_expired": len(expired_items),
        }

        if expired_items:
            self._attr_icon = "mdi:calendar-remove"
        elif expiring_items:
            self._attr_icon = "mdi:calendar-alert"
        else:
            self._attr_icon = "mdi:calendar-check"
