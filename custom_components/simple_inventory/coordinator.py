"""Data coordinator for Simple Inventory integration."""
import logging
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    FIELD_QUANTITY, FIELD_UNIT, FIELD_CATEGORY, FIELD_EXPIRY_DATE,
    FIELD_AUTO_ADD_ENABLED, FIELD_THRESHOLD, FIELD_TODO_LIST,
    DEFAULT_QUANTITY, DEFAULT_THRESHOLD, DEFAULT_UNIT, DEFAULT_CATEGORY,
    DEFAULT_EXPIRY_DATE, DEFAULT_TODO_LIST, DEFAULT_AUTO_ADD_ENABLED,
    INVENTORY_ITEMS, ERROR_ITEM_NOT_FOUND, STORAGE_VERSION, STORAGE_KEY, DOMAIN
)

_LOGGER = logging.getLogger(__name__)


class SimpleInventoryCoordinator:
    """Manage inventory data and storage."""

    def __init__(self, hass: HomeAssistant):
        """Initialize the coordinator."""
        self.hass = hass
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data = {"inventories": {}}

    async def async_load_data(self):
        """Load data from storage."""
        data = await self._store.async_load() or {"inventories": {}}

        # Migrate from old format if needed
        if "items" in data and "inventories" not in data:
            # Migrate from old single inventory format to new multi-inventory format
            data = {
                "inventories": {
                    "default": {"items": data.get("items", {})}
                }
            }

        if "inventories" not in data:
            data["inventories"] = {}

        # Ensure all inventories have required structure
        for inventory_id, inventory_data in data["inventories"].items():
            if "items" not in inventory_data:
                inventory_data["items"] = {}

            # Migrate existing items to include any missing fields
            for item_name, item_data in inventory_data["items"].items():
                # Ensure all required fields exist with defaults
                defaults = {
                    "quantity": 0,
                    "unit": "",
                    "category": "",
                    "expiry_date": "",
                    "auto_add_enabled": False,
                    "threshold": 0,
                    "todo_list": "",
                }
                for key, default_value in defaults.items():
                    if key not in item_data:
                        item_data[key] = default_value

        self._data = data
        return data

    async def async_save_data(self, inventory_id=None):
        """Save data to storage."""
        await self._store.async_save(self._data)

        # Notify sensors to update - either specific inventory or all
        if inventory_id:
            self.hass.bus.async_fire(f"{DOMAIN}_updated_{inventory_id}")
        else:
            # Notify all inventories
            for inv_id in self._data["inventories"]:
                self.hass.bus.async_fire(f"{DOMAIN}_updated_{inv_id}")

    def get_data(self):
        """Get all data."""
        return self._data

    def get_inventory(self, inventory_id):
        """Get a specific inventory."""
        return self._data["inventories"].get(inventory_id, {"items": {}})

    def ensure_inventory_exists(self, inventory_id):
        """Ensure inventory exists, create if not."""
        if inventory_id not in self._data["inventories"]:
            self._data["inventories"][inventory_id] = {"items": {}}
        return self._data["inventories"][inventory_id]

    def get_item(self, inventory_id, name):
        """Get a specific item from an inventory."""
        inventory = self.get_inventory(inventory_id)
        return inventory["items"].get(name)

    def get_all_items(self, inventory_id):
        """Get all items from a specific inventory."""
        inventory = self.get_inventory(inventory_id)
        return inventory["items"]

    def update_item(self, inventory_id, old_name, new_name, **kwargs):
        """Update an existing item with new values."""
        inventory = self.get_inventory(inventory_id)

        if old_name not in inventory["items"]:
            return False

        # Get the current item data
        current_item = inventory["items"][old_name].copy()

        # Update with new values (only update provided fields)
        for key, value in kwargs.items():
            if key in ["quantity", "unit", "category", "expiry_date", "auto_add_enabled", "threshold", "todo_list"]:
                current_item[key] = value

        # If name changed, remove old entry and add new one
        if old_name != new_name:
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
            inventory[INVENTORY_ITEMS][name][FIELD_QUANTITY] += quantity
        else:
            # Add new item with all fields
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
            return False
        inventory = self.get_inventory(inventory_id)
        if name in inventory[INVENTORY_ITEMS]:
            del inventory[INVENTORY_ITEMS][name]
            return True
        return False

    def update_item_quantity(self, inventory_id: str, name: str, new_quantity: int) -> bool:
        """Update item quantity in a specific inventory."""
        if not name or not name.strip():
            return False
        inventory = self.get_inventory(inventory_id)
        if name in inventory[INVENTORY_ITEMS]:
            inventory[INVENTORY_ITEMS][name][FIELD_QUANTITY] = max(
                0, new_quantity)
            return True
        return False

    def increment_item(self, inventory_id: str, name: str, amount: int = 1) -> bool:
        """Increment item quantity in a specific inventory."""
        if not name or not name.strip() or amount < 0:
            return False
        inventory = self.get_inventory(inventory_id)
        if name in inventory[INVENTORY_ITEMS]:
            current_quantity = inventory[INVENTORY_ITEMS][name][FIELD_QUANTITY]
            inventory[INVENTORY_ITEMS][name][FIELD_QUANTITY] = current_quantity + amount
            return True
        return False

    def decrement_item(self, inventory_id: str, name: str, amount: int = 1) -> bool:
        """Decrement item quantity in a specific inventory."""
        if not name or not name.strip() or amount < 0:
            return False
        inventory = self.get_inventory(inventory_id)
        if name in inventory[INVENTORY_ITEMS]:
            current_quantity = inventory[INVENTORY_ITEMS][name][FIELD_QUANTITY]
            new_quantity = max(0, current_quantity - amount)
            inventory[INVENTORY_ITEMS][name][FIELD_QUANTITY] = new_quantity
            return True
        return False

    def update_item_settings(self, inventory_id: str, name: str, **kwargs) -> bool:
        """Update item settings in a specific inventory."""
        if not name or not name.strip():
            return False

        inventory = self.get_inventory(inventory_id)
        if name in inventory[INVENTORY_ITEMS]:
            item = inventory[INVENTORY_ITEMS][name]

            # Define allowed fields for settings update
            allowed_fields = {
                FIELD_AUTO_ADD_ENABLED, FIELD_THRESHOLD, FIELD_TODO_LIST,
                FIELD_UNIT, FIELD_CATEGORY, FIELD_EXPIRY_DATE, FIELD_QUANTITY
            }

            for key, value in kwargs.items():
                if key in allowed_fields:
                    if key == FIELD_QUANTITY or key == FIELD_THRESHOLD:
                        item[key] = max(
                            0, int(value)) if value is not None else 0
                    elif key == FIELD_AUTO_ADD_ENABLED:
                        item[key] = bool(value)
                    else:
                        item[key] = str(value) if value is not None else ""
            return True
        return False
