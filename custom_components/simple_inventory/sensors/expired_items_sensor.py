"""Expired items sensor for Simple Inventory."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from ..const import DOMAIN, partition_expiry, updated_event
from ..hub import InventoryHub
from ._base import InventoryRefreshSensor


class ExpiredItemsSensor(InventoryRefreshSensor):
    """Sensor to track expired items for a specific inventory."""

    def __init__(
        self,
        hass: HomeAssistant,
        hub: InventoryHub,
        inventory_id: str,
        inventory_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(
            hass,
            hub,
            cache_key=inventory_id,
            update_event=updated_event(inventory_id),
        )
        self.inventory_id = inventory_id
        self.inventory_name = inventory_name
        self._attr_name = f"{inventory_name} Expired Items"
        self._attr_unique_id = f"simple_inventory_expired_items_{inventory_id}"
        self._attr_icon = "mdi:calendar-remove"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, inventory_id)},
            "name": inventory_name,
        }

    async def _async_refresh(self) -> None:
        expired_items, _ = partition_expiry(
            await self.hub.async_items_expiring_soon(self.inventory_id)
        )
        for item in expired_items:
            item["inventory"] = self.inventory_name

        self._attr_native_value = len(expired_items)
        self._attr_extra_state_attributes = {
            "expired_items": expired_items,
            "total_expired": len(expired_items),
            "inventory_id": self.inventory_id,
            "inventory_name": self.inventory_name,
        }
