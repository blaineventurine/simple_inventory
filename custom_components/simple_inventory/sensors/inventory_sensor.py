"""Individual inventory sensor for Simple Inventory."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import Event, HomeAssistant, callback

from ..const import DOMAIN
from ..coordinator import SimpleInventoryCoordinator

_LOGGER = logging.getLogger(__name__)


class InventorySensor(SensorEntity):
    """Representation of an Inventory sensor."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: SimpleInventoryCoordinator,
        inventory_name: str,
        icon: str,
        entry_id: str,
    ) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self.coordinator = coordinator
        self._entry_id = entry_id
        self._attr_name = f"{inventory_name} Inventory"
        self._attr_unique_id = f"inventory_{entry_id}"
        self._attr_icon = icon
        self._attr_native_unit_of_measurement = "items"
        self._attr_extra_state_attributes: dict[str, Any] = {}
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": inventory_name,
        }

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        await self._async_update_state()

        self.async_on_remove(
            self.hass.bus.async_listen(f"{DOMAIN}_updated_{self._entry_id}", self._handle_update)
        )
        self.async_on_remove(self.hass.bus.async_listen(f"{DOMAIN}_updated", self._handle_update))
        self.async_on_remove(self.coordinator.async_add_listener(self._handle_update))

    @callback
    def _handle_update(self, _event: Event | None = None) -> None:
        """Invalidate the per-inventory expiry cache and schedule an async refresh."""
        expiry_cache = getattr(self.coordinator, "_expiry_cache", None)
        if expiry_cache is not None:
            expiry_cache.pop(self._entry_id, None)
        self.hass.async_create_task(self._async_update_state())

    async def _async_update_state(self) -> None:
        """Fetch stats/items from the repository."""
        try:
            stats = await self.coordinator.async_get_inventory_statistics(self._entry_id)
        except Exception as err:
            _LOGGER.error("Failed to refresh inventory sensor %s: %s", self._entry_id, err)
            return

        self._attr_native_value = stats["total_quantity"]

        description = ""
        config_entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if config_entry:
            description = config_entry.data.get("description", "")

        self._attr_extra_state_attributes = {
            "inventory_id": self._entry_id,
            "description": description,
            "total_items": stats["total_items"],
            "total_quantity": stats["total_quantity"],
            "below_threshold": stats["below_threshold"],
            "expiring_soon": len(stats["expiring_items"]),
        }
        self.async_write_ha_state()
