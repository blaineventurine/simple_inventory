"""Inventory management service handler."""

import logging
from typing import Any, cast

from homeassistant.core import ServiceCall

from ..const import DOMAIN
from ..types import (
    AddItemServiceData,
    GetAllItemsServiceData,
    GetItemsServiceData,
    RemoveItemServiceData,
    UpdateItemServiceData,
)
from .base_service import BaseServiceHandler

_LOGGER = logging.getLogger(__name__)


class InventoryService(BaseServiceHandler):
    """Handle inventory-specific operations (add, remove, update items)."""

    async def async_add_item(self, call: ServiceCall) -> None:
        """Add an item to the inventory."""
        item_data: AddItemServiceData = cast(AddItemServiceData, call.data)
        inventory_id = item_data["inventory_id"]
        name = item_data["name"]

        item_kwargs = self._extract_item_kwargs(item_data, ["inventory_id"])

        try:
            self.coordinator.add_item(inventory_id, **item_kwargs)
            await self._save_and_log_success(inventory_id, "Added item", name)
        except Exception as e:
            _LOGGER.error(f"Failed to add item {name} to inventory {inventory_id}: {e}")

    async def async_remove_item(self, call: ServiceCall) -> None:
        """Remove an item from the inventory."""
        data: RemoveItemServiceData = cast(RemoveItemServiceData, call.data)
        inventory_id = data["inventory_id"]
        name = data["name"]

        try:
            if self.coordinator.remove_item(inventory_id, name):
                await self._save_and_log_success(inventory_id, "Removed item", name)
            else:
                self._log_item_not_found("Remove item", name, inventory_id)
        except Exception as e:
            _LOGGER.error(
                f"Failed to remove item {
                    name} from inventory {inventory_id}: {e}"
            )

    async def async_update_item(self, call: ServiceCall) -> None:
        """Update an existing item with new values."""
        data: UpdateItemServiceData = cast(UpdateItemServiceData, call.data)
        inventory_id = data["inventory_id"]
        old_name = data["old_name"]
        new_name = data["name"]

        if not self.coordinator.get_item(inventory_id, old_name):
            self._log_item_not_found("Update item", old_name, inventory_id)
            return

        update_data: dict[str, Any] = {}

        optional_fields = [
            "quantity",
            "unit",
            "category",
            "expiry_date",
            "auto_add_enabled",
            "auto_add_to_list_quantity",
            "expiry_alert_days",
            "todo_list",
            "location",
        ]
        for field in optional_fields:
            if field in data:
                update_data[field] = data.get(field)

        try:
            if self.coordinator.update_item(inventory_id, old_name, new_name, **update_data):
                await self._save_and_log_success(
                    inventory_id,
                    f"Updated item: {old_name} -> {new_name}",
                    new_name,
                )
            else:
                self._log_operation_failed("Update item", old_name, inventory_id)
        except Exception as e:
            _LOGGER.error(
                f"Failed to update item {
                    old_name} in inventory {inventory_id}: {e}"
            )

    async def async_get_items(self, call: ServiceCall) -> dict[str, list[dict[str, Any]]]:
        """Return full list of items for an inventory.

        Can be called with either inventory_id or inventory_name.
        Response shape:
        { "items": [{"name": str, ...item fields...}, ...] }
        """
        data = cast(GetItemsServiceData, call.data)
        
        # Resolve inventory_id from either inventory_id or inventory_name
        if "inventory_id" in data and data["inventory_id"]:
            inventory_id = data["inventory_id"]
        elif "inventory_name" in data and data["inventory_name"]:
            # Look up inventory by name
            inventory_name = data["inventory_name"]
            all_entries = self.hass.config_entries.async_entries(DOMAIN)
            
            # Find entry matching the name (case-insensitive)
            matching_entry = None
            for entry in all_entries:
                entry_name = entry.data.get("name", "").lower()
                if entry_name == inventory_name.lower():
                    matching_entry = entry
                    break
            
            if not matching_entry:
                raise ValueError(f"Inventory with name '{inventory_name}' not found")
            
            inventory_id = matching_entry.entry_id
        else:
            raise ValueError("Either 'inventory_id' or 'inventory_name' must be provided")

        items_map = self.coordinator.get_all_items(inventory_id)
        items_list = [{"name": name, **details} for name, details in items_map.items()]

        # Sorting for stable output
        items_list.sort(key=lambda item: item.get("name", "").lower())

        return {"items": items_list}

    async def async_get_items_from_all_inventories(
        self, call: ServiceCall
    ) -> dict[str, list[dict[str, Any]]]:
        """Return full list of items grouped by inventory."""
        _ = cast(GetAllItemsServiceData, call.data)  # ensures schema adherence, unused

        inventories_data: list[dict[str, Any]] = []
        all_entries = self.hass.config_entries.async_entries(DOMAIN)
        entry_lookup = {entry.entry_id: entry for entry in all_entries}

        inventories = self.coordinator.get_data().get("inventories", {})

        for inventory_id in inventories:
            items_map = self.coordinator.get_all_items(inventory_id)
            items_list = [{"name": name, **details} for name, details in items_map.items()]
            items_list.sort(key=lambda item: item.get("name", "").lower())

            entry = entry_lookup.get(inventory_id)
            inventory_name = ""
            description = ""

            if entry:
                inventory_name = entry.data.get("name") or entry.title or inventory_id
                description = entry.data.get("description", "")
            else:
                inventory_name = inventory_id

            inventories_data.append(
                {
                    "inventory_id": inventory_id,
                    "inventory_name": inventory_name,
                    "description": description,
                    "items": items_list,
                }
            )

        inventories_data.sort(key=lambda inv: inv.get("inventory_name", "").lower())

        return {"inventories": inventories_data}
