"""Individual inventory sensor for Simple Inventory."""
import logging
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, callback
from ..const import DOMAIN, INVENTORY_ITEMS

_LOGGER = logging.getLogger(__name__)


class InventorySensor(SensorEntity):
    """Representation of an Inventory sensor."""

    def __init__(self, hass: HomeAssistant, coordinator, inventory_name: str, icon: str, entry_id: str):
        """Initialize the sensor."""
        self.hass = hass
        self.coordinator = coordinator
        self._entry_id = entry_id
        self._attr_name = f"{inventory_name} Inventory"
        self._attr_unique_id = f"inventory_{entry_id}"
        self._attr_icon = icon
        self._attr_native_unit_of_measurement = "items"
        self._attr_extra_state_attributes = {}
        self._update_data()

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        # Listen for specific inventory updates
        self.async_on_remove(
            self.hass.bus.async_listen(
                f"{DOMAIN}_updated_{self._entry_id}", self._handle_update)
        )

        # Also listen for general updates
        self.async_on_remove(
            self.hass.bus.async_listen(
                f"{DOMAIN}_updated", self._handle_update)
        )

        # Add as coordinator listener for direct updates
        self.async_on_remove(
            self.coordinator.async_add_listener(
                self._handle_coordinator_update)
        )

    @callback
    def _handle_update(self, _event):
        """Handle inventory updates."""
        self._update_data()
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self):
        """Handle coordinator updates."""
        self._update_data()
        self.async_write_ha_state()

    def _update_data(self):
        """Update sensor data."""
        items = self.coordinator.get_all_items(self._entry_id)

        # Count total items
        total_count = sum(item["quantity"] for item in items.values())
        self._attr_native_value = total_count

        # Get inventory statistics
        stats = self.coordinator.get_inventory_statistics(self._entry_id)

        # Add all items and statistics as attributes
        self._attr_extra_state_attributes = {
            "inventory_id": self._entry_id,
            "items": [{
                "name": name,
                **details
            } for name, details in items.items()],
            "total_items": stats["total_items"],
            "total_quantity": stats["total_quantity"],
            "categories": stats["categories"],
            "below_threshold": stats["below_threshold"],
            "expiring_soon": len(stats["expiring_items"]),
        }
