"""Data coordinator for Simple Inventory integration."""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .const import (
    FIELD_QUANTITY, FIELD_UNIT, FIELD_CATEGORY, FIELD_EXPIRY_DATE,
    FIELD_AUTO_ADD_ENABLED, FIELD_THRESHOLD, FIELD_TODO_LIST,
    DEFAULT_QUANTITY, DEFAULT_THRESHOLD, DEFAULT_UNIT, DEFAULT_CATEGORY,
    DEFAULT_EXPIRY_DATE, DEFAULT_TODO_LIST, DEFAULT_AUTO_ADD_ENABLED,
    INVENTORY_ITEMS, STORAGE_VERSION, STORAGE_KEY, DOMAIN
)

_LOGGER = logging.getLogger(__name__)


class SimpleInventoryCoordinator:
    """Manage inventory data and storage."""

    def __init__(self, hass: HomeAssistant):
        """Initialize the coordinator."""
        self.hass = hass
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data = {"inventories": {},
                      "config": {"expiry_threshold_days": 7}}
        self._listeners = []

    async def async_load_data(self) -> Dict[str, Any]:
        """Load data from storage and handle migrations if needed."""
        data = await self._store.async_load() or {"inventories": {}}

        # Migrate from old format if needed
        if "items" in data and "inventories" not in data:
            _LOGGER.info(
                "Migrating from old single inventory format to multi-inventory format")
            data = {
                "inventories": {
                    "default": {"items": data.get("items", {})}
                }
            }

        if "inventories" not in data:
            data["inventories"] = {}

        if "config" not in data:
            data["config"] = {"expiry_threshold_days": 7}
        elif "expiry_threshold_days" not in data["config"]:
            data["config"]["expiry_threshold_days"] = 7

        # Ensure all inventories have required structure
        for inventory_id, inventory_data in data["inventories"].items():
            if "items" not in inventory_data:
                inventory_data["items"] = {}

            # Migrate existing items to include any missing fields
            for item_name, item_data in inventory_data["items"].items():
                # Ensure all required fields exist with defaults
                defaults = {
                    FIELD_QUANTITY: DEFAULT_QUANTITY,
                    FIELD_UNIT: DEFAULT_UNIT,
                    FIELD_CATEGORY: DEFAULT_CATEGORY,
                    FIELD_EXPIRY_DATE: DEFAULT_EXPIRY_DATE,
                    FIELD_AUTO_ADD_ENABLED: DEFAULT_AUTO_ADD_ENABLED,
                    FIELD_THRESHOLD: DEFAULT_THRESHOLD,
                    FIELD_TODO_LIST: DEFAULT_TODO_LIST,
                }
                for key, default_value in defaults.items():
                    if key not in item_data:
                        item_data[key] = default_value

        self._data = data
        return data

    async def async_save_data(self, inventory_id: Optional[str] = None) -> None:
        """Save data to storage and notify listeners."""
        try:
            await self._store.async_save(self._data)
            _LOGGER.debug("Inventory data saved successfully")

            # Notify sensors to update - either specific inventory or all
            if inventory_id:
                self.hass.bus.async_fire(f"{DOMAIN}_updated_{inventory_id}")
                _LOGGER.debug(
                    f"Fired update event for inventory: {inventory_id}")
            else:
                # Notify all inventories
                for inv_id in self._data["inventories"]:
                    self.hass.bus.async_fire(f"{DOMAIN}_updated_{inv_id}")
                    _LOGGER.debug(
                        f"Fired update event for inventory: {inv_id}")

                # Also fire a general update event
                self.hass.bus.async_fire(f"{DOMAIN}_updated")

            # Notify listeners
            self.notify_listeners()
        except Exception as ex:
            _LOGGER.error(f"Failed to save inventory data: {ex}")
            raise

    def get_data(self) -> Dict[str, Any]:
        """Get all data."""
        return self._data

    def get_inventory(self, inventory_id: str) -> Dict[str, Any]:
        """Get a specific inventory."""
        return self._data["inventories"].get(inventory_id, {"items": {}})

    def ensure_inventory_exists(self, inventory_id: str) -> Dict[str, Any]:
        """Ensure inventory exists, create if not."""
        if inventory_id not in self._data["inventories"]:
            self._data["inventories"][inventory_id] = {"items": {}}
        return self._data["inventories"][inventory_id]

    def get_item(self, inventory_id: str, name: str) -> Optional[Dict[str, Any]]:
        """Get a specific item from an inventory."""
        inventory = self.get_inventory(inventory_id)
        return inventory["items"].get(name)

    def get_all_items(self, inventory_id: str) -> Dict[str, Dict[str, Any]]:
        """Get all items from a specific inventory."""
        inventory = self.get_inventory(inventory_id)
        return inventory["items"]

    def update_item(self, inventory_id: str, old_name: str, new_name: str, **kwargs) -> bool:
        """Update an existing item with new values."""
        inventory = self.get_inventory(inventory_id)

        if old_name not in inventory["items"]:
            _LOGGER.warning(
                f"Cannot update non-existent item '{old_name}' in inventory '{inventory_id}'")
            return False

        # Get the current item data
        current_item = inventory["items"][old_name].copy()

        # Update with new values (only update provided fields)
        for key, value in kwargs.items():
            if key in [FIELD_QUANTITY, FIELD_UNIT, FIELD_CATEGORY, FIELD_EXPIRY_DATE,
                       FIELD_AUTO_ADD_ENABLED, FIELD_THRESHOLD, FIELD_TODO_LIST]:
                current_item[key] = value

        # If name changed, remove old entry and add new one
        if old_name != new_name:
            _LOGGER.info(f"Renaming item '{old_name}' to '{
                         new_name}' in inventory '{inventory_id}'")
            del inventory["items"][old_name]
            inventory["items"][new_name] = current_item
        else:
            # Just update the existing entry
            inventory["items"][old_name] = current_item

        return True

    def add_item(self, inventory_id: str, name: str, quantity: int = DEFAULT_QUANTITY, **kwargs) -> bool:
        """Add or update an item in a specific inventory."""
        if not name or not name.strip():
            raise ValueError("Item name cannot be empty")

        inventory = self.ensure_inventory_exists(inventory_id)

        if name in inventory[INVENTORY_ITEMS]:
            # Update existing item quantity
            _LOGGER.debug(f"Updating quantity of existing item '{
                          name}' in inventory '{inventory_id}'")
            inventory[INVENTORY_ITEMS][name][FIELD_QUANTITY] += quantity
        else:
            # Add new item with all fields
            _LOGGER.info(f"Adding new item '{
                         name}' to inventory '{inventory_id}'")
            inventory[INVENTORY_ITEMS][name] = {
                FIELD_QUANTITY: max(0, quantity),
                FIELD_UNIT: kwargs.get(FIELD_UNIT, DEFAULT_UNIT),
                FIELD_CATEGORY: kwargs.get(FIELD_CATEGORY, DEFAULT_CATEGORY),
                FIELD_EXPIRY_DATE: kwargs.get(FIELD_EXPIRY_DATE, DEFAULT_EXPIRY_DATE),
                FIELD_AUTO_ADD_ENABLED: kwargs.get(FIELD_AUTO_ADD_ENABLED, DEFAULT_AUTO_ADD_ENABLED),
                FIELD_THRESHOLD: max(0, kwargs.get(FIELD_THRESHOLD, DEFAULT_THRESHOLD)),
                FIELD_TODO_LIST: kwargs.get(FIELD_TODO_LIST, DEFAULT_TODO_LIST),
            }

        return True

    def remove_item(self, inventory_id: str, name: str) -> bool:
        """Remove an item completely from a specific inventory."""
        if not name or not name.strip():
            _LOGGER.warning(
                f"Cannot remove item with empty name from inventory '{inventory_id}'")
            return False

        inventory = self.get_inventory(inventory_id)
        if name in inventory[INVENTORY_ITEMS]:
            _LOGGER.info(f"Removing item '{
                         name}' from inventory '{inventory_id}'")
            del inventory[INVENTORY_ITEMS][name]
            return True

        _LOGGER.warning(
            f"Cannot remove non-existent item '{name}' from inventory '{inventory_id}'")
        return False

    def update_item_quantity(self, inventory_id: str, name: str, new_quantity: int) -> bool:
        """Update item quantity in a specific inventory."""
        if not name or not name.strip():
            _LOGGER.warning(
                f"Cannot update quantity for item with empty name in inventory '{inventory_id}'")
            return False

        inventory = self.get_inventory(inventory_id)
        if name in inventory[INVENTORY_ITEMS]:
            _LOGGER.debug(f"Updating quantity of item '{name}' in inventory '{
                          inventory_id}' to {max(0, new_quantity)}")
            inventory[INVENTORY_ITEMS][name][FIELD_QUANTITY] = max(
                0, new_quantity)
            return True

        _LOGGER.warning(
            f"Cannot update quantity for non-existent item '{name}' in inventory '{inventory_id}'")
        return False

    def increment_item(self, inventory_id: str, name: str, amount: int = 1) -> bool:
        """Increment item quantity in a specific inventory."""
        if not name or not name.strip() or amount < 0:
            _LOGGER.warning(f"Cannot increment item with invalid parameters: name='{
                            name}', amount={amount}")
            return False

        inventory = self.get_inventory(inventory_id)
        if name in inventory[INVENTORY_ITEMS]:
            current_quantity = inventory[INVENTORY_ITEMS][name][FIELD_QUANTITY]
            new_quantity = current_quantity + amount
            _LOGGER.debug(f"Incrementing item '{name}' in inventory '{
                          inventory_id}' from {current_quantity} to {new_quantity}")
            inventory[INVENTORY_ITEMS][name][FIELD_QUANTITY] = new_quantity
            return True

        _LOGGER.warning(
            f"Cannot increment non-existent item '{name}' in inventory '{inventory_id}'")
        return False

    def decrement_item(self, inventory_id: str, name: str, amount: int = 1) -> bool:
        """Decrement item quantity in a specific inventory."""
        if not name or not name.strip() or amount < 0:
            _LOGGER.warning(f"Cannot decrement item with invalid parameters: name='{
                            name}', amount={amount}")
            return False

        inventory = self.get_inventory(inventory_id)
        if name in inventory[INVENTORY_ITEMS]:
            current_quantity = inventory[INVENTORY_ITEMS][name][FIELD_QUANTITY]
            new_quantity = max(0, current_quantity - amount)
            _LOGGER.debug(f"Decrementing item '{name}' in inventory '{
                          inventory_id}' from {current_quantity} to {new_quantity}")
            inventory[INVENTORY_ITEMS][name][FIELD_QUANTITY] = new_quantity
            return True

        _LOGGER.warning(
            f"Cannot decrement non-existent item '{name}' in inventory '{inventory_id}'")
        return False

    def update_item_settings(self, inventory_id: str, name: str, **kwargs) -> bool:
        """Update item settings in a specific inventory."""
        if not name or not name.strip():
            _LOGGER.warning(
                f"Cannot update settings for item with empty name in inventory '{inventory_id}'")
            return False

        inventory = self.get_inventory(inventory_id)
        if name in inventory[INVENTORY_ITEMS]:
            item = inventory[INVENTORY_ITEMS][name]
            updated_fields = []

            # Define allowed fields for settings update
            allowed_fields = {
                FIELD_AUTO_ADD_ENABLED, FIELD_THRESHOLD, FIELD_TODO_LIST,
                FIELD_UNIT, FIELD_CATEGORY, FIELD_EXPIRY_DATE, FIELD_QUANTITY
            }

            for key, value in kwargs.items():
                if key in allowed_fields:
                    old_value = item[key]
                    if key == FIELD_QUANTITY or key == FIELD_THRESHOLD:
                        item[key] = max(
                            0, int(value)) if value is not None else 0
                    elif key == FIELD_AUTO_ADD_ENABLED:
                        item[key] = bool(value)
                    else:
                        item[key] = str(value) if value is not None else ""

                    if item[key] != old_value:
                        updated_fields.append(key)

            if updated_fields:
                _LOGGER.debug(f"Updated settings for item '{name}' in inventory '{
                              inventory_id}': {', '.join(updated_fields)}")

            return True

        _LOGGER.warning(
            f"Cannot update settings for non-existent item '{name}' in inventory '{inventory_id}'")
        return False

    def expiry_threshold_days(self) -> int:
        """Get the current expiry threshold in days."""
        return self._data["config"]["expiry_threshold_days"]

    def set_expiry_threshold(self, threshold_days: int) -> None:
        """Set the expiry threshold in days."""
        old_threshold = self._data["config"]["expiry_threshold_days"]
        self._data["config"]["expiry_threshold_days"] = threshold_days

        _LOGGER.info(f"Expiry threshold changed from {
                     old_threshold} to {threshold_days} days")

        # Notify listeners about threshold change
        self.hass.bus.async_fire(f"{DOMAIN}_threshold_updated", {
                                 "new_threshold": threshold_days})

    def get_items_expiring_soon(self, inventory_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get items expiring within the threshold period."""
        threshold_days = self._data["config"]["expiry_threshold_days"]
        current_datetime = datetime.now()
        threshold_date = current_datetime.date() + timedelta(days=threshold_days)
        expiring_items = []

        # If inventory_id is provided, only check that inventory
        # Otherwise, check all inventories
        inventories_to_check = {}
        if inventory_id:
            inventory = self.get_inventory(inventory_id)
            inventories_to_check = {inventory_id: inventory}
        else:
            inventories_to_check = self._data["inventories"]

        for inv_id, inventory in inventories_to_check.items():
            for item_name, item_data in inventory.get("items", {}).items():
                expiry_date_str = item_data.get(FIELD_EXPIRY_DATE, "")
                if expiry_date_str and expiry_date_str.strip():
                    try:
                        # Assuming expiry_date is in YYYY-MM-DD format
                        expiry_date = datetime.strptime(
                            expiry_date_str, "%Y-%m-%d").date()
                        days_until_expiry = (
                            expiry_date - current_datetime.date()).days

                        if expiry_date <= threshold_date:
                            expiring_items.append({
                                "inventory_id": inv_id,
                                "name": item_name,
                                "expiry_date": expiry_date_str,
                                "days_until_expiry": days_until_expiry,
                                **item_data
                            })
                    except ValueError:
                        _LOGGER.warning(f"Invalid expiry date format for {
                                        item_name}: {expiry_date_str}")

        # Sort by expiry date (soonest first)
        expiring_items.sort(key=lambda x: x["days_until_expiry"])
        return expiring_items

    @callback
    def async_add_listener(self, listener_func) -> callable:
        """Add a listener for data updates."""
        self._listeners.append(listener_func)

        def remove_listener():
            """Remove the listener."""
            if listener_func in self._listeners:
                self._listeners.remove(listener_func)

        return remove_listener

    def notify_listeners(self) -> None:
        """Notify all listeners of an update."""
        for listener in self._listeners:
            listener()

    def get_inventory_statistics(self, inventory_id: str) -> Dict[str, Any]:
        """Get statistics for a specific inventory."""
        inventory = self.get_inventory(inventory_id)
        items = inventory.get("items", {})

        total_items = len(items)
        total_quantity = sum(item.get(FIELD_QUANTITY, 0)
                             for item in items.values())

        categories = {}
        for item in items.values():
            category = item.get(FIELD_CATEGORY, "")
            if category:
                if category not in categories:
                    categories[category] = 0
                categories[category] += 1

        # Get items below threshold
        below_threshold = []
        for name, item in items.items():
            quantity = item.get(FIELD_QUANTITY, 0)
            threshold = item.get(FIELD_THRESHOLD, 0)
            if threshold > 0 and quantity <= threshold:
                below_threshold.append({
                    "name": name,
                    "quantity": quantity,
                    "threshold": threshold,
                    "unit": item.get(FIELD_UNIT, ""),
                    "category": item.get(FIELD_CATEGORY, "")
                })

        # Get expiring items
        expiring_items = self.get_items_expiring_soon(inventory_id)

        return {
            "total_items": total_items,
            "total_quantity": total_quantity,
            "categories": categories,
            "below_threshold": below_threshold,
            "expiring_items": expiring_items,
        }
