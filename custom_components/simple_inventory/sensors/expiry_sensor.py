"""Expiry notification sensor for Simple Inventory."""
import logging
import datetime
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, callback
from ..const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class ExpiryNotificationSensor(SensorEntity):
    """Sensor to track items nearing expiry for a specific inventory."""

    def __init__(self, hass: HomeAssistant, coordinator, inventory_id: str, inventory_name: str):
        """Initialize the sensor."""
        self.hass = hass
        self.coordinator = coordinator
        self.inventory_id = inventory_id
        self.inventory_name = inventory_name
        self._attr_name = f"{inventory_name} Items Expiring Soon"
        self._attr_unique_id = f"simple_inventory_expiring_items_{
            inventory_id}"
        self._attr_icon = "mdi:calendar-alert"
        self._attr_native_unit_of_measurement = "items"
        self._update_data()

    async def async_added_to_hass(self) -> None:
        """Register callbacks for inventory updates."""
        # Listen for updates to this specific inventory
        self.async_on_remove(
            self.hass.bus.async_listen(
                f"{DOMAIN}_updated_{self.inventory_id}", self._handle_update)
        )

        # Listen for general inventory updates
        self.async_on_remove(
            self.hass.bus.async_listen(
                f"{DOMAIN}_updated", self._handle_update)
        )

        # Add as coordinator listener for direct updates
        if hasattr(self.coordinator, "async_add_listener"):
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
        """Update sensor data for this specific inventory."""
        today = datetime.datetime.now().date()

        expiring_items = []
        expired_items = []

        # Only process this inventory's data
        inventories = self.coordinator.get_data().get("inventories", {})
        inventory_data = inventories.get(self.inventory_id, {})

        for item_name, item_data in inventory_data.get("items", {}).items():
            expiry_date_str = item_data.get("expiry_date")
            if expiry_date_str and expiry_date_str.strip():
                try:
                    expiry_date = datetime.datetime.strptime(
                        expiry_date_str, "%Y-%m-%d").date()
                    days_left = (expiry_date - today).days
                    item_threshold = item_data.get("threshold", 7)

                    item_info = {
                        "name": item_name,
                        "inventory": self.inventory_name,
                        "inventory_id": self.inventory_id,
                        "expiry_date": expiry_date_str,
                        "days_left": days_left,
                        "quantity": item_data.get("quantity", 0),
                        "unit": item_data.get("unit", ""),
                        "category": item_data.get("category", ""),
                        "threshold": item_threshold
                    }

                    if days_left < 0:
                        expired_items.append(item_info)
                    elif days_left <= item_threshold:
                        expiring_items.append(item_info)

                except ValueError:
                    _LOGGER.warning(f"Invalid date format for item {
                                    item_name}: {expiry_date_str}")

        # Update sensor state
        total_items = len(expired_items) + len(expiring_items)
        self._attr_native_value = total_items
        self._attr_extra_state_attributes = {
            "expiring_items": expiring_items,
            "expired_items": expired_items,
            "inventory_id": self.inventory_id,
            "inventory_name": self.inventory_name,
            "total_expiring": len(expiring_items),
            "total_expired": len(expired_items),
        }

        # Update icon based on urgency
        if expired_items:
            self._attr_icon = "mdi:calendar-remove"
        elif expiring_items:
            self._attr_icon = "mdi:calendar-alert"
        else:
            self._attr_icon = "mdi:calendar-check"


class GlobalExpiryNotificationSensor(SensorEntity):
    """Sensor to track items nearing expiry across all inventories."""

    def __init__(self, hass: HomeAssistant, coordinator):
        """Initialize the global sensor."""
        self.hass = hass
        self.coordinator = coordinator
        self._attr_name = "All Items Expiring Soon"
        self._attr_unique_id = "simple_inventory_all_expiring_items"
        self._attr_icon = "mdi:calendar-alert"
        self._attr_native_unit_of_measurement = "items"
        self._attr_device_class = None
        self._attr_extra_state_attributes = {}
        self._update_data()

    async def async_added_to_hass(self) -> None:
        """Register callbacks for all inventory updates."""
        # Listen for any inventory updates
        self.async_on_remove(
            self.hass.bus.async_listen(
                f"{DOMAIN}_updated", self._handle_update)
        )

        # Also listen for specific inventory updates
        inventories = self.coordinator.get_data().get("inventories", {})
        for inventory_id in inventories:
            self.async_on_remove(
                self.hass.bus.async_listen(
                    f"{DOMAIN}_updated_{inventory_id}", self._handle_update)
            )

        # Add as coordinator listener for direct updates
        if hasattr(self.coordinator, "async_add_listener"):
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
        """Update sensor data aggregating all inventories."""
        today = datetime.datetime.now().date()

        expiring_items = []
        expired_items = []
        inventories = self.coordinator.get_data().get("inventories", {})

        for inventory_id, inventory_data in inventories.items():
            inventory_name = self._get_inventory_name(inventory_id)

            for item_name, item_data in inventory_data.get("items", {}).items():
                expiry_date_str = item_data.get("expiry_date")
                if expiry_date_str and expiry_date_str.strip():
                    try:
                        expiry_date = datetime.datetime.strptime(
                            expiry_date_str, "%Y-%m-%d").date()
                        days_left = (expiry_date - today).days
                        item_threshold = item_data.get("threshold", 7)

                        item_info = {
                            "name": item_name,
                            "inventory": inventory_name,
                            "inventory_id": inventory_id,
                            "expiry_date": expiry_date_str,
                            "days_left": days_left,
                            "quantity": item_data.get("quantity", 0),
                            "unit": item_data.get("unit", ""),
                            "category": item_data.get("category", ""),
                            "threshold": item_threshold
                        }

                        if days_left < 0:
                            expired_items.append(item_info)
                        elif days_left <= item_threshold:
                            expiring_items.append(item_info)

                    except ValueError:
                        _LOGGER.warning(f"Invalid date format for item {
                                        item_name}: {expiry_date_str}")
                        pass

        expiring_items.sort(key=lambda x: x["days_left"])
        expired_items.sort(key=lambda x: x["days_left"])

        total_items = len(expired_items) + len(expiring_items)

        self._attr_native_value = total_items
        self._attr_extra_state_attributes = {
            "expiring_items": expiring_items,
            "expired_items": expired_items,
            "total_expiring": len(expiring_items),
            "total_expired": len(expired_items),
            "next_expiring": expiring_items[0] if expiring_items else None,
            "oldest_expired": expired_items[0] if expired_items else None,
            "inventories_count": len(inventories),
        }

        if expired_items:
            self._attr_icon = "mdi:calendar-remove"
        elif expiring_items:
            most_urgent_days = expiring_items[0]["days_left"] if expiring_items else 7
            if most_urgent_days <= 1:
                self._attr_icon = "mdi:calendar-alert"
            elif most_urgent_days <= 3:
                self._attr_icon = "mdi:calendar-clock"
            else:
                self._attr_icon = "mdi:calendar-week"
        else:
            self._attr_icon = "mdi:calendar-check"

    def _get_inventory_name(self, inventory_id):
        """Get the friendly name of an inventory by its ID."""
        try:
            config_entries = self.hass.config_entries.async_entries(DOMAIN)
            for entry in config_entries:
                if entry.entry_id == inventory_id:
                    return entry.data.get("name", "Unknown Inventory")
        except Exception:
            pass

        return "Unknown Inventory"
