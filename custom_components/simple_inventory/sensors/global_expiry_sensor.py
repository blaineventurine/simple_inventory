import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, callback

from ..const import DOMAIN
from ..coordinator import SimpleInventoryCoordinator

_LOGGER = logging.getLogger(__name__)


class GlobalExpiryNotificationSensor(SensorEntity):
    """Sensor to track items nearing expiry across all inventories."""

    def __init__(
        self, hass: HomeAssistant, coordinator: SimpleInventoryCoordinator
    ) -> None:
        """Initialize the global sensor."""
        self.hass = hass
        self.coordinator = coordinator
        self._attr_name = "All Items Expiring Soon"
        self._attr_unique_id = "simple_inventory_all_expiring_items"
        self._attr_icon = "mdi:calendar-alert"
        self._attr_native_unit_of_measurement = "items"
        self._attr_device_class = None
        self._attr_extra_state_attributes = {}
        self._attr_device_info = {
            "identifiers": {(DOMAIN, "global_expiry_tracker")},
            "name": "All Items Expiring Soon",
        }
        self._update_data()

    async def async_added_to_hass(self) -> None:
        """Register callbacks for all inventory updates."""
        self.async_on_remove(
            self.hass.bus.async_listen(f"{DOMAIN}_updated", self._handle_update)
        )

        inventories = self.coordinator.get_data().get("inventories", {})
        for inventory_id in inventories:
            self.async_on_remove(
                self.hass.bus.async_listen(
                    f"{DOMAIN}_updated_{inventory_id}", self._handle_update
                )
            )

        if hasattr(self.coordinator, "async_add_listener"):
            self.async_on_remove(
                self.coordinator.async_add_listener(
                    self._handle_coordinator_update
                )
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
        """Update sensor data aggregating all inventories."""
        all_items = self.coordinator.get_items_expiring_soon()

        for item in all_items:
            item["inventory"] = self._get_inventory_name(item["inventory_id"])

        expired_items = [
            item for item in all_items if item["days_until_expiry"] < 0
        ]
        expiring_items = [
            item for item in all_items if item["days_until_expiry"] >= 0
        ]

        total_items = len(all_items)
        inventories_count = (
            len({item["inventory_id"] for item in all_items})
            if all_items
            else 0
        )

        self._attr_native_value = total_items
        self._attr_extra_state_attributes = {
            "expiring_items": expiring_items,
            "expired_items": expired_items,
            "total_expiring": len(expiring_items),
            "total_expired": len(expired_items),
            "next_expiring": expiring_items[0] if expiring_items else None,
            "oldest_expired": expired_items[0] if expired_items else None,
            "inventories_count": inventories_count,
        }

        if expired_items:
            self._attr_icon = "mdi:calendar-remove"
        elif expiring_items:
            most_urgent_days = (
                expiring_items[0]["days_until_expiry"] if expiring_items else 7
            )
            if most_urgent_days <= 1:
                self._attr_icon = "mdi:calendar-alert"
            elif most_urgent_days <= 3:
                self._attr_icon = "mdi:calendar-clock"
            else:
                self._attr_icon = "mdi:calendar-week"
        else:
            self._attr_icon = "mdi:calendar-check"

    def _get_inventory_name(self, inventory_id: str) -> str:
        """Get the friendly name of an inventory by its ID."""
        try:
            config_entries = self.hass.config_entries.async_entries(DOMAIN)
            for entry in config_entries:
                if entry.entry_id == inventory_id:
                    return entry.data.get("name", "Unknown Inventory")
        except Exception:
            pass

        return "Unknown Inventory"
