"""Global expiry notification sensor for Simple Inventory."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from ..const import DOMAIN, EVENT_UPDATED, expiry_icon, partition_expiry
from ..entries import inventory_display_name
from ..hub import InventoryHub
from ._base import InventoryRefreshSensor


class GlobalItemsExpiringSoonSensor(InventoryRefreshSensor):
    """Sensor to track items nearing expiry across all inventories."""

    def __init__(self, hass: HomeAssistant, hub: InventoryHub) -> None:
        """Initialize the global sensor."""
        # The general update event fires on every inventory change, including
        # inventories added after startup, so no per-inventory listeners are needed.
        super().__init__(hass, hub, cache_key=None, update_event=EVENT_UPDATED)
        self._attr_name = "All Items Expiring Soon"
        self._attr_unique_id = "simple_inventory_all_expiring_items"
        self._attr_icon = "mdi:calendar-alert"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, "global_expiry_tracker")},
            "name": "All Items Expiring Soon",
        }

    async def _async_refresh(self) -> None:
        all_items = await self.hub.async_items_expiring_soon()
        for item in all_items:
            item["inventory"] = inventory_display_name(
                self.hass, item["inventory_id"], default="Unknown Inventory"
            )
        expired_items, expiring_items = partition_expiry(all_items)

        self._attr_native_value = len(expiring_items)
        self._attr_extra_state_attributes = {
            "expiring_items": expiring_items,
            "expired_items": expired_items,
            "total_expiring": len(expiring_items),
            "total_expired": len(expired_items),
            "next_expiring": expiring_items[0] if expiring_items else None,
            "oldest_expired": expired_items[0] if expired_items else None,
            "inventories_count": len({item["inventory_id"] for item in all_items}),
        }
        self._attr_icon = expiry_icon(expiring_items)
