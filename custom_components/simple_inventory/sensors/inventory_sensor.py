"""Individual inventory sensor for Simple Inventory."""

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, callback

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
        self._attr_extra_state_attributes = {}
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": inventory_name,
        }
        self._update_data()

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        self.async_on_remove(
            self.hass.bus.async_listen(
                f"{DOMAIN}_updated_{self._entry_id}", self._handle_update
            )
        )

        self.async_on_remove(
            self.hass.bus.async_listen(f"{DOMAIN}_updated", self._handle_update)
        )

        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

    @callback
    def _handle_update(self, _event) -> None:
        """Handle inventory updates."""
        self._update_data()
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle coordinator updates."""
        self._update_data()
        self.async_write_ha_state()

    def _update_data(self) -> None:
        """update sensor data."""
        items = self.coordinator.get_all_items(self._entry_id)
        stats = self.coordinator.get_inventory_statistics(self._entry_id)
        self._attr_native_value = stats["total_quantity"]

        description = ""
        try:
            config_entry = self.hass.config_entries.async_get_entry(
                self._entry_id
            )
            if config_entry:
                description = config_entry.data.get("description", "")
        except Exception:
            pass  # Fallback to empty description if config entry not found

        self._attr_extra_state_attributes = {
            "inventory_id": self._entry_id,
            "description": description,
            "items": [
                {"name": name, **details} for name, details in items.items()
            ],
            "total_items": stats["total_items"],
            "total_quantity": stats["total_quantity"],
            "categories": stats["categories"],
            "below_threshold": stats["below_threshold"],
            "expiring_soon": len(stats["expiring_items"]),
        }
