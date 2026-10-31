"""Global expired items sensor for Simple Inventory."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from ..const import DOMAIN, EVENT_UPDATED, partition_expiry
from ..entries import inventory_display_name
from ..hub import InventoryHub
from ._base import InventoryRefreshSensor


class GlobalExpiredItemsSensor(InventoryRefreshSensor):
    """Sensor to track expired items across all inventories."""

    def __init__(self, hass: HomeAssistant, hub: InventoryHub) -> None:
        """Initialize the global sensor."""
        # The general update event fires on every inventory change, including
        # inventories added after startup, so no per-inventory listeners are needed.
        super().__init__(hass, hub, cache_key=None, update_event=EVENT_UPDATED)
        self._attr_name = "All Expired Items"
        self._attr_unique_id = "simple_inventory_all_expired_items"
        self._attr_icon = "mdi:calendar-remove"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, "global_expired_items")},
            "name": "All Expired Items",
        }

    async def _async_refresh(self) -> None:
        expired_items, _ = partition_expiry(await self.hub.async_items_expiring_soon())
        for item in expired_items:
            item["inventory"] = inventory_display_name(
                self.hass, item["inventory_id"], default="Unknown Inventory"
            )

        self._attr_native_value = len(expired_items)
        self._attr_extra_state_attributes = {
            "expired_items": expired_items,
            "total_expired": len(expired_items),
            "oldest_expired": expired_items[0] if expired_items else None,
            "inventories_count": len({item["inventory_id"] for item in expired_items}),
        }
