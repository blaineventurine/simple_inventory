"""Expired items sensor for Simple Inventory."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import Event, HomeAssistant, callback

from ..const import DOMAIN
from ..coordinator import SimpleInventoryCoordinator

_LOGGER = logging.getLogger(__name__)


class ExpiredItemsSensor(SensorEntity):
    """Sensor to track expired items for a specific inventory."""

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
        self._attr_name = f"{inventory_name} Expired Items"
        self._attr_unique_id = f"simple_inventory_expired_items_{inventory_id}"
        self._attr_icon = "mdi:calendar-remove"
        self._attr_native_unit_of_measurement = "items"
        self._attr_extra_state_attributes: dict[str, Any] = {}
        self._attr_device_info = {
            "identifiers": {(DOMAIN, inventory_id)},
            "name": inventory_name,
        }

    async def async_added_to_hass(self) -> None:
        """Register callbacks for inventory updates."""
        await self._async_update_state()

        self.async_on_remove(
            self.hass.bus.async_listen(f"{DOMAIN}_updated_{self.inventory_id}", self._handle_update)
        )
        self.async_on_remove(self.hass.bus.async_listen(f"{DOMAIN}_updated", self._handle_update))
        self.async_on_remove(self.coordinator.async_add_listener(self._handle_update))

    @callback
    def _handle_update(self, _event: Event | None = None) -> None:
        """Invalidate the per-inventory expiry cache and schedule refresh."""
        expiry_cache = getattr(self.coordinator, "_expiry_cache", None)
        if expiry_cache is not None:
            expiry_cache.pop(self.inventory_id, None)
        self.hass.async_create_task(self._async_update_state())

    async def _async_update_state(self) -> None:
        """Update sensor data for this specific inventory."""
        try:
            all_items = await self.coordinator.async_get_items_expiring_soon(self.inventory_id)
        except Exception as err:
            _LOGGER.error(
                "Failed to refresh expired items sensor for %s: %s",
                self.inventory_id,
                err,
            )
            return

        expired_items = [item for item in all_items if item["days_until_expiry"] < 0]

        for item in expired_items:
            item["inventory"] = self.inventory_name

        self._attr_native_value = len(expired_items)
        self._attr_extra_state_attributes = {
            "expired_items": expired_items,
            "total_expired": len(expired_items),
            "inventory_id": self.inventory_id,
            "inventory_name": self.inventory_name,
        }

        self.async_write_ha_state()
