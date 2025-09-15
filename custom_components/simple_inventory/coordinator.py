"""Data coordinator for Simple Inventory integration."""

import logging
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional, Unpack, cast

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .const import (
    DEFAULT_AUTO_ADD_ENABLED,
    DEFAULT_AUTO_ADD_TO_LIST_QUANTITY,
    DEFAULT_CATEGORY,
    DEFAULT_EXPIRY_ALERT_DAYS,
    DEFAULT_EXPIRY_DATE,
    DEFAULT_LOCATION,
    DEFAULT_QUANTITY,
    DEFAULT_TODO_LIST,
    DEFAULT_UNIT,
    DOMAIN,
    FIELD_AUTO_ADD_ENABLED,
    FIELD_AUTO_ADD_TO_LIST_QUANTITY,
    FIELD_CATEGORY,
    FIELD_EXPIRY_ALERT_DAYS,
    FIELD_EXPIRY_DATE,
    FIELD_LOCATION,
    FIELD_NAME,
    FIELD_QUANTITY,
    FIELD_TODO_LIST,
    FIELD_UNIT,
    INVENTORY_ITEMS,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .types import InventoryData, InventoryItem

_LOGGER = logging.getLogger(__name__)


class SimpleInventoryCoordinator:
    """Manage inventory data and storage."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the coordinator."""
        self.hass = hass
        self._store: Store[InventoryData] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: InventoryData = {
            "inventories": {},
            "config": {"expiry_alert_days": DEFAULT_EXPIRY_ALERT_DAYS},
        }
        self._listeners: list[Callable[[], None]] = []

    async def async_load_data(self) -> InventoryData:
        """Load data from storage and handle migrations if needed."""
        loaded_data = await self._store.async_load()

        if loaded_data is None:
            data: InventoryData = {"inventories": {}, "config": {}}
        else:
            data = loaded_data
            if "config" not in data:
                data["config"] = {}

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
                _LOGGER.debug(f"Fired update event for inventory: {inventory_id}")
            else:
                # Notify all inventories
                for inv_id in self._data["inventories"]:
                    self.hass.bus.async_fire(f"{DOMAIN}_updated_{inv_id}")
                    _LOGGER.debug(f"Fired update event for inventory: {inv_id}")

                # Also fire a general update event
                self.hass.bus.async_fire(f"{DOMAIN}_updated")

            # Notify listeners
            self.notify_listeners()
        except Exception as ex:
            _LOGGER.error(f"Failed to save inventory data: {ex}")
            raise

    def get_data(self) -> InventoryData:
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

    def get_item(self, inventory_id: str, name: str) -> InventoryItem | None:
        """Get a specific item from an inventory."""
        inventory = self.get_inventory(inventory_id)
        item = inventory["items"].get(name)
        return cast(InventoryItem, item) if item is not None else None

    def get_all_items(self, inventory_id: str) -> Dict[str, InventoryItem]:
        """Get all items from a specific inventory."""
        inventory = self.get_inventory(inventory_id)
        return cast(dict[str, InventoryItem], inventory["items"])

    def update_item(
        self,
        inventory_id: str,
        old_name: str,
        new_name: str,
        **kwargs: Unpack[InventoryItem],
    ) -> bool:
        """Update an existing item with new values."""
        inventory = self.get_inventory(inventory_id)

        if old_name not in inventory["items"]:
            _LOGGER.warning(
                f"Cannot update non-existent item '{
                    old_name}' in inventory '{inventory_id}'"
            )
            return False

        item_name = new_name if new_name is not None else old_name
        current_item = inventory["items"][old_name].copy()
        allowed_fields = {
            FIELD_AUTO_ADD_ENABLED,
            FIELD_AUTO_ADD_TO_LIST_QUANTITY,
            FIELD_CATEGORY,
            FIELD_EXPIRY_ALERT_DAYS,
            FIELD_EXPIRY_DATE,
            FIELD_QUANTITY,
            FIELD_TODO_LIST,
            FIELD_UNIT,
            FIELD_LOCATION,
        }

        for key, value in kwargs.items():
            _LOGGER.warning(f"updating '{key}' to '{value}'")
            if key in allowed_fields:
                if key in (
                    FIELD_QUANTITY,
                    FIELD_AUTO_ADD_TO_LIST_QUANTITY,
                    FIELD_EXPIRY_ALERT_DAYS,
                ):
                    current_item[key] = (
                        max(0, int(value))
                        if value is not None and isinstance(value, (int, str, bool))
                        else 0
                    )
                elif key == FIELD_AUTO_ADD_ENABLED:
                    current_item[key] = bool(value)
                else:
                    current_item[key] = str(value) if value is not None else ""

        final_auto_add_enabled = current_item.get(FIELD_AUTO_ADD_ENABLED, False)
        if final_auto_add_enabled:
            final_auto_add_quantity = current_item.get(FIELD_AUTO_ADD_TO_LIST_QUANTITY)
            final_todo_list = current_item.get(FIELD_TODO_LIST, "")
            auto_add_being_enabled = kwargs.get(FIELD_AUTO_ADD_ENABLED) is True

            if auto_add_being_enabled:
                if final_auto_add_quantity is None or final_auto_add_quantity < 0:
                    _LOGGER.error(
                        f"Cannot enable auto-add without valid quantity for item '{
                            old_name}' in inventory '{inventory_id}'"
                    )
                    return False

                if not final_todo_list or not final_todo_list.strip():
                    _LOGGER.error(
                        f"Cannot enable auto-add without todo list for item '{
                            old_name}' in inventory '{inventory_id}'"
                    )
                    return False

        if old_name != item_name:
            _LOGGER.info(
                f"Renaming item '{old_name}' to '{
                    item_name}' in inventory '{inventory_id}'"
            )
            del inventory["items"][old_name]
            inventory["items"][item_name] = current_item
        else:
            inventory["items"][item_name] = current_item

        return True

    def add_item(self, inventory_id: str, **kwargs: Unpack[InventoryItem]) -> bool:
        """Add or update an item in a specific inventory."""
        name = kwargs.get(FIELD_NAME)

        if not name or not name.strip():
            raise ValueError("Item name cannot be empty")

        name = str(name).strip()
        inventory = self.ensure_inventory_exists(inventory_id)
        quantity = kwargs.get(FIELD_QUANTITY, DEFAULT_QUANTITY)

        if name in inventory[INVENTORY_ITEMS]:
            _LOGGER.debug(
                f"Updating quantity of existing item '{
                    name}' in inventory '{inventory_id}'"
            )
            inventory[INVENTORY_ITEMS][name][FIELD_QUANTITY] += quantity
        else:
            _LOGGER.info(
                f"Adding new item '{
                    name}' to inventory '{inventory_id}'"
            )

            auto_add_quantity = kwargs.get(
                FIELD_AUTO_ADD_TO_LIST_QUANTITY,
                DEFAULT_AUTO_ADD_TO_LIST_QUANTITY,
            )
            if auto_add_quantity is not None:
                auto_add_quantity = max(0, int(auto_add_quantity))

            expiry_alert_days = kwargs.get(FIELD_EXPIRY_ALERT_DAYS, DEFAULT_EXPIRY_ALERT_DAYS)
            if expiry_alert_days is not None:
                expiry_alert_days = max(0, int(expiry_alert_days))

            new_item: InventoryItem = {
                FIELD_AUTO_ADD_ENABLED: kwargs.get(
                    FIELD_AUTO_ADD_ENABLED, DEFAULT_AUTO_ADD_ENABLED
                ),
                FIELD_AUTO_ADD_TO_LIST_QUANTITY: auto_add_quantity,
                FIELD_CATEGORY: kwargs.get(FIELD_CATEGORY, DEFAULT_CATEGORY),
                FIELD_EXPIRY_ALERT_DAYS: expiry_alert_days,
                FIELD_EXPIRY_DATE: kwargs.get(FIELD_EXPIRY_DATE, DEFAULT_EXPIRY_DATE),
                FIELD_QUANTITY: max(0, quantity),
                FIELD_TODO_LIST: kwargs.get(FIELD_TODO_LIST, DEFAULT_TODO_LIST),
                FIELD_UNIT: kwargs.get(FIELD_UNIT, DEFAULT_UNIT),
                FIELD_LOCATION: kwargs.get(FIELD_LOCATION, DEFAULT_LOCATION),
            }

            if new_item[FIELD_AUTO_ADD_ENABLED]:
                if (
                    new_item[FIELD_AUTO_ADD_TO_LIST_QUANTITY] is None
                    or new_item[FIELD_AUTO_ADD_TO_LIST_QUANTITY] < 0
                ):
                    _LOGGER.error(
                        f"Auto-add enabled but no valid quantity specified for new item '{
                            name}' in inventory '{inventory_id}'"
                    )
                    return False

                todo_list = new_item[FIELD_TODO_LIST]
                if not todo_list or not todo_list.strip():
                    _LOGGER.error(
                        f"Auto-add enabled but no todo list specified for new item '{
                            name}' in inventory '{inventory_id}'"
                    )
                    return False

            inventory[INVENTORY_ITEMS][name] = new_item

        return True

    def remove_item(self, inventory_id: str, name: str) -> bool:
        """Remove an item completely from a specific inventory."""
        if not name or not name.strip():
            _LOGGER.warning(
                f"Cannot remove item with empty name from inventory '{
                    inventory_id}'"
            )
            return False

        inventory = self.get_inventory(inventory_id)
        if name in inventory[INVENTORY_ITEMS]:
            _LOGGER.info(
                f"Removing item '{
                    name}' from inventory '{inventory_id}'"
            )
            del inventory[INVENTORY_ITEMS][name]
            return True

        _LOGGER.warning(
            f"Cannot remove non-existent item '{
                name}' from inventory '{inventory_id}'"
        )
        return False

    def increment_item(self, inventory_id: str, name: str, amount: int = 1) -> bool:
        """Increment item quantity in a specific inventory."""
        if not name or not name.strip() or amount < 0:
            _LOGGER.warning(
                f"Cannot increment item with invalid parameters: name='{
                    name}', amount={amount}"
            )
            return False

        inventory = self.get_inventory(inventory_id)
        if name in inventory[INVENTORY_ITEMS]:
            current_quantity = inventory[INVENTORY_ITEMS][name][FIELD_QUANTITY]
            new_quantity = current_quantity + amount
            _LOGGER.debug(
                f"Incrementing item '{name}' in inventory '{
                    inventory_id}' from {current_quantity} to {new_quantity}"
            )
            inventory[INVENTORY_ITEMS][name][FIELD_QUANTITY] = new_quantity
            return True

        _LOGGER.warning(
            f"Cannot increment non-existent item '{
                name}' in inventory '{inventory_id}'"
        )
        return False

    def decrement_item(self, inventory_id: str, name: str, amount: int = 1) -> bool:
        """Decrement item quantity in a specific inventory."""
        if not name or not name.strip() or amount < 0:
            _LOGGER.warning(
                f"Cannot decrement item with invalid parameters: name='{
                    name}', amount={amount}"
            )
            return False

        inventory = self.get_inventory(inventory_id)
        if name in inventory[INVENTORY_ITEMS]:
            current_quantity = inventory[INVENTORY_ITEMS][name][FIELD_QUANTITY]
            new_quantity = max(0, current_quantity - amount)
            _LOGGER.debug(
                f"Decrementing item '{name}' in inventory '{
                    inventory_id}' from {current_quantity} to {new_quantity}"
            )
            inventory[INVENTORY_ITEMS][name][FIELD_QUANTITY] = new_quantity
            return True

        _LOGGER.warning(
            f"Cannot decrement non-existent item '{
                name}' in inventory '{inventory_id}'"
        )
        return False

    def get_items_expiring_soon(self, inventory_id: str | None = None) -> list[dict[str, Any]]:
        """Get items expiring within their individual threshold periods."""
        current_datetime = datetime.now()
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
                item_threshold = item_data.get(FIELD_EXPIRY_ALERT_DAYS, DEFAULT_EXPIRY_ALERT_DAYS)
                quantity = item_data.get(FIELD_QUANTITY, DEFAULT_QUANTITY)

                if (
                    expiry_date_str
                    and expiry_date_str.strip()
                    and item_threshold is not None
                    and quantity > 0
                ):
                    try:
                        expiry_date = datetime.strptime(expiry_date_str, "%Y-%m-%d").date()
                        days_until_expiry = (expiry_date - current_datetime.date()).days
                        threshold_date = current_datetime.date() + timedelta(days=item_threshold)

                        if expiry_date <= threshold_date:
                            expiring_items.append(
                                {
                                    "inventory_id": inv_id,
                                    "name": item_name,
                                    "expiry_date": expiry_date_str,
                                    "days_until_expiry": days_until_expiry,
                                    "threshold": item_threshold,
                                    **item_data,
                                }
                            )
                    except ValueError:
                        _LOGGER.warning(
                            f"Invalid expiry date format for {
                                item_name}: {expiry_date_str}"
                        )

        expiring_items.sort(key=lambda x: x["days_until_expiry"])
        return expiring_items

    @callback
    def async_add_listener(self, listener_func: Callable[[], None]) -> Callable[[], None]:
        """Add a listener for data updates."""
        self._listeners.append(listener_func)

        def remove_listener() -> None:
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
        total_quantity = sum(item.get(FIELD_QUANTITY, DEFAULT_QUANTITY) for item in items.values())

        categories = {}
        for item in items.values():
            category = item.get(FIELD_CATEGORY, DEFAULT_CATEGORY)
            if category:
                if category not in categories:
                    categories[category] = 0
                categories[category] += 1

        locations = {}
        for item in items.values():
            location = item.get(FIELD_LOCATION, DEFAULT_LOCATION)
            if location:
                if location not in locations:
                    locations[location] = 0
                locations[location] += 1

        below_threshold = []
        for name, item in items.items():
            quantity = item.get(FIELD_QUANTITY, 0)
            threshold = item.get(
                FIELD_AUTO_ADD_TO_LIST_QUANTITY,
                DEFAULT_AUTO_ADD_TO_LIST_QUANTITY,
            )
            if threshold > 0 and quantity <= threshold:
                below_threshold.append(
                    {
                        "name": name,
                        "quantity": quantity,
                        "threshold": threshold,
                        "unit": item.get(FIELD_UNIT, DEFAULT_UNIT),
                        "category": item.get(FIELD_CATEGORY, DEFAULT_CATEGORY),
                    }
                )

        expiring_items = self.get_items_expiring_soon(inventory_id)

        return {
            "total_items": total_items,
            "total_quantity": total_quantity,
            "categories": categories,
            "locations": locations,
            "below_threshold": below_threshold,
            "expiring_items": expiring_items,
        }
