"""Expiry notification sensor for Simple Inventory."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from ..const import DOMAIN, expiry_icon, partition_expiry, updated_event
from ..hub import InventoryHub
from ._base import InventoryRefreshSensor


class ItemsExpiringSoonSensor(InventoryRefreshSensor):
    """Sensor to track items nearing expiry for a specific inventory."""

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
        self._attr_name = f"{inventory_name} Items Expiring Soon"
        self._attr_unique_id = f"simple_inventory_expiring_items_{inventory_id}"
        self._attr_icon = "mdi:calendar-alert"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, inventory_id)},
            "name": inventory_name,
        }

    async def _async_refresh(self) -> None:
        _, expiring_items = partition_expiry(
            await self.hub.async_items_expiring_soon(self.inventory_id)
        )
        for item in expiring_items:
            item["inventory"] = self.inventory_name

        self._attr_native_value = len(expiring_items)
        self._attr_extra_state_attributes = {
            "expiring_items": expiring_items,
            "inventory_id": self.inventory_id,
            "inventory_name": self.inventory_name,
            "total_expiring": len(expiring_items),
        }
        self._attr_icon = expiry_icon(expiring_items)
