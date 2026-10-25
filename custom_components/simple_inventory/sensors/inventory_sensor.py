"""Individual inventory sensor for Simple Inventory."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from ..const import CONF_DESCRIPTION, DOMAIN, round_quantity, updated_event
from ..coordinator import SimpleInventoryCoordinator
from ..hub import InventoryHub
from ._base import InventoryRefreshSensor


class InventorySensor(InventoryRefreshSensor):
    """Total quantity of one inventory, with summary attributes."""

    def __init__(
        self,
        hass: HomeAssistant,
        hub: InventoryHub,
        coordinator: SimpleInventoryCoordinator,
        inventory_name: str,
        icon: str,
        entry_id: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(hass, hub, cache_key=entry_id, update_event=updated_event(entry_id))
        self.coordinator = coordinator
        self._entry_id = entry_id
        self._attr_name = f"{inventory_name} Inventory"
        self._attr_unique_id = f"inventory_{entry_id}"
        self._attr_icon = icon
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": inventory_name,
        }

    async def _async_refresh(self) -> None:
        stats = await self.coordinator.async_get_inventory_statistics(self._entry_id)

        total_quantity = round_quantity(stats["total_quantity"])
        self._attr_native_value = total_quantity

        description = ""
        config_entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if config_entry:
            description = config_entry.data.get(CONF_DESCRIPTION, "")

        self._attr_extra_state_attributes = {
            "inventory_id": self._entry_id,
            "description": description,
            "total_items": stats["total_items"],
            "total_quantity": total_quantity,
            "below_threshold": stats["below_threshold"],
            "expiring_soon": len(stats["expiring_items"]),
        }
