"""Sensor platform for Simple Inventory."""
import logging
import datetime
from datetime import timedelta

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the inventory sensor."""
    coordinator = hass.data[DOMAIN]["coordinator"]
    inventory_name = config_entry.data.get("name", "Inventory")
    icon = config_entry.data.get("icon", "mdi:package-variant")
    entry_id = config_entry.entry_id

    async_add_entities(
        [InventorySensor(hass, coordinator, inventory_name, icon, entry_id)])

    # Add the expiry notification sensor (only once)
    all_entries = hass.config_entries.async_entries(DOMAIN)
    if entry_id == all_entries[0].entry_id:
        # Get threshold from options or use default
        threshold_days = config_entry.options.get("expiry_threshold", 7)
        async_add_entities([ExpiryNotificationSensor(
            hass, coordinator, threshold_days)])


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
        self.async_on_remove(
            self.hass.bus.async_listen(
                f"{DOMAIN}_updated_{self._entry_id}", self._handle_update)
        )

    @callback
    def _handle_update(self, _event):
        """Handle inventory updates."""
        self._update_data()
        self.async_write_ha_state()

    def _update_data(self):
        """Update sensor data."""
        items = self.coordinator.get_all_items(self._entry_id)

        # Count total items
        total_count = sum(item["quantity"] for item in items.values())
        self._attr_native_value = total_count

        # Add all items as attributes
        self._attr_extra_state_attributes = {
            "inventory_id": self._entry_id,
            "items": [{
                "name": name,
                **details
            } for name, details in items.items()]
        }


class ExpiryNotificationSensor(SensorEntity):
    """Sensor to track items nearing expiry across all inventories."""

    def __init__(self, hass: HomeAssistant, coordinator, days_threshold=7):
        """Initialize the sensor."""
        self.hass = hass
        self.coordinator = coordinator
        self._days_threshold = days_threshold
        self._attr_name = "Items Expiring Soon"
        self._attr_unique_id = "simple_inventory_expiring_items"
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

    @callback
    def _handle_update(self, _event):
        """Handle inventory updates."""
        self._update_data()
        self.async_write_ha_state()

    def _update_data(self):
        """Update sensor data."""
        today = datetime.datetime.now().date()

        expiring_items = []
        expired_items = []

        # Get all inventories
        inventories = self.coordinator.get_data().get("inventories", {})

        # Check each inventory for expiring items
        for inventory_id, inventory_data in inventories.items():
            # Get inventory name by finding the corresponding sensor entity
            inventory_name = self._get_inventory_name(inventory_id)

            for item_name, item_data in inventory_data.get("items", {}).items():
                expiry_date_str = item_data.get("expiry_date")
                if expiry_date_str and expiry_date_str.strip():
                    try:
                        expiry_date = datetime.datetime.strptime(
                            expiry_date_str, "%Y-%m-%d").date()
                        days_left = (expiry_date - today).days

                        item_info = {
                            "name": item_name,
                            "inventory": inventory_name,
                            "inventory_id": inventory_id,
                            "expiry_date": expiry_date_str,
                            "days_left": days_left,
                            "quantity": item_data.get("quantity", 0),
                            "unit": item_data.get("unit", ""),
                            "category": item_data.get("category", "")
                        }

                        if days_left < 0:
                            # Item is expired
                            expired_items.append(item_info)
                        elif days_left <= self._days_threshold:
                            # Item is expiring soon
                            expiring_items.append(item_info)

                    except ValueError:
                        # Invalid date format, skip this item
                        _LOGGER.warning(f"Invalid date format for item {
                                        item_name}: {expiry_date_str}")
                        pass

        # Sort items by days left (most urgent first)
        expiring_items.sort(key=lambda x: x["days_left"])
        expired_items.sort(key=lambda x: x["days_left"])

        # Combine expired and expiring items for total count
        total_items = len(expired_items) + len(expiring_items)

        # Update state and attributes
        self._attr_native_value = total_items
        self._attr_extra_state_attributes = {
            "expiring_items": expiring_items,
            "expired_items": expired_items,
            "threshold_days": self._days_threshold,
            "total_expiring": len(expiring_items),
            "total_expired": len(expired_items),
            "next_expiring": expiring_items[0] if expiring_items else None,
            "oldest_expired": expired_items[0] if expired_items else None,
        }

        # Update icon based on urgency
        if expired_items:
            self._attr_icon = "mdi:calendar-remove"
        elif expiring_items:
            # Change icon based on urgency
            most_urgent_days = expiring_items[0]["days_left"] if expiring_items else self._days_threshold
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
        # Search through all sensor entities to find the one with matching inventory_id
        for entity_id in self.hass.states.async_entity_ids("sensor"):
            if entity_id.startswith("sensor.") and entity_id.endswith("_inventory"):
                state = self.hass.states.get(entity_id)
                if state and state.attributes:
                    if state.attributes.get("inventory_id") == inventory_id:
                        return state.attributes.get("friendly_name", entity_id)

        # Fallback: try to get from config entries
        try:
            config_entries = self.hass.config_entries.async_entries(DOMAIN)
            for entry in config_entries:
                if entry.entry_id == inventory_id:
                    return entry.data.get("name", "Unknown Inventory")
        except Exception:
            pass

        return "Unknown Inventory"
