"""Global expired items sensor for Simple Inventory."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import Event, HomeAssistant, callback

from ..const import DOMAIN
from ..coordinator import SimpleInventoryCoordinator

_LOGGER = logging.getLogger(__name__)


class GlobalExpiredItemsSensor(SensorEntity):
    """Sensor to track expired items across all inventories."""

    def __init__(self, hass: HomeAssistant, coordinator: SimpleInventoryCoordinator) -> None:
        """Initialize the global sensor."""
        self.hass = hass
        self.coordinator = coordinator
        self._attr_name = "All Expired Items"
        self._attr_unique_id = "simple_inventory_all_expired_items"
        self._attr_icon = "mdi:calendar-remove"
        self._attr_native_unit_of_measurement = "items"
        self._attr_extra_state_attributes: dict[str, Any] = {}
        self._attr_device_info = {
            "identifiers": {(DOMAIN, "global_expired_items")},
            "name": "All Expired Items",
        }

    async def async_added_to_hass(self) -> None:
        """Register callbacks and perform initial refresh."""
        await self._async_update_state()

        # The general DOMAIN_updated event fires on every inventory change, including
        # inventories added after startup — so per-inventory listeners are not needed.
        self.async_on_remove(self.hass.bus.async_listen(f"{DOMAIN}_updated", self._handle_update))
        self.async_on_remove(self.coordinator.async_add_listener(self._handle_update))

    @callback
    def _handle_update(self, _event: Event | None = None) -> None:
        """Invalidate the global expiry cache and schedule refresh."""
        expiry_cache = getattr(self.coordinator, "_expiry_cache", None)
        if expiry_cache is not None:
            expiry_cache.pop(None, None)
        self.hass.async_create_task(self._async_update_state())

    async def _async_update_state(self) -> None:
        """Aggregate expired items across inventories."""
        try:
            all_items = await self.coordinator.async_get_items_expiring_soon()
        except Exception as err:
            _LOGGER.error("Failed to refresh global expired items sensor: %s", err)
            return

        expired_items = [item for item in all_items if item["days_until_expiry"] < 0]

        for item in expired_items:
            item["inventory"] = self._get_inventory_name(item["inventory_id"])

        inventories_count = len({item["inventory_id"] for item in expired_items})

        self._attr_native_value = len(expired_items)
        self._attr_extra_state_attributes = {
            "expired_items": expired_items,
            "total_expired": len(expired_items),
            "oldest_expired": expired_items[0] if expired_items else None,
            "inventories_count": inventories_count,
        }

        self.async_write_ha_state()

    def _get_inventory_name(self, inventory_id: str) -> str:
        """Resolve inventory name from config entries."""
        try:
            config_entries = self.hass.config_entries.async_entries(DOMAIN)
            for entry in config_entries:
                if entry.entry_id == inventory_id:
                    return str(entry.data.get("name", "Unknown Inventory"))
        except Exception:
            pass
        return "Unknown Inventory"
