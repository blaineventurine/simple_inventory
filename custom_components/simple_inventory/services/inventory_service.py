"""Inventory management service handler."""

import logging

from homeassistant.core import ServiceCall

from .base_service import BaseServiceHandler

_LOGGER = logging.getLogger(__name__)


class InventoryService(BaseServiceHandler):
    """Handle inventory-specific operations (add, remove, update items)."""

    async def async_add_item(self, call: ServiceCall) -> None:
        """Add an item to the inventory."""
        item_data = call.data
        inventory_id = item_data["inventory_id"]
        name = item_data["name"]

        item_kwargs = self._extract_item_kwargs(
            item_data, ["name", "inventory_id"]
        )

        try:
            self.coordinator.add_item(inventory_id, name, **item_kwargs)
            await self._save_and_log_success(inventory_id, "Added item", name)
        except Exception as e:
            _LOGGER.error(
                f"Failed to add item {
                    name} to inventory {inventory_id}: {e}"
            )

    async def async_remove_item(self, call: ServiceCall) -> None:
        """Remove an item from the inventory."""
        inventory_id, name = self._get_inventory_and_name(call)

        try:
            if self.coordinator.remove_item(inventory_id, name):
                await self._save_and_log_success(
                    inventory_id, "Removed item", name
                )
            else:
                self._log_item_not_found("Remove item", name, inventory_id)
        except Exception as e:
            _LOGGER.error(
                f"Failed to remove item {
                    name} from inventory {inventory_id}: {e}"
            )

    async def async_update_item(self, call: ServiceCall) -> None:
        """Update an existing item with new values."""
        data = call.data
        inventory_id = data["inventory_id"]
        old_name = data["old_name"]
        new_name = data["name"]

        if not self.coordinator.get_item(inventory_id, old_name):
            self._log_item_not_found("Update item", old_name, inventory_id)
            return

        update_data = {}

        optional_fields = [
            "quantity",
            "unit",
            "category",
            "expiry_date",
            "auto_add_enabled",
            "auto_add_to_list_quantity",
            "expiry_alert_days",
            "todo_list",
        ]
        for field in optional_fields:
            if field in data:
                update_data[field] = data[field]

        try:
            if self.coordinator.update_item(
                inventory_id, old_name, new_name, **update_data
            ):
                await self._save_and_log_success(
                    inventory_id,
                    f"Updated item: {
                        old_name} -> {new_name}",
                    new_name,
                )
            else:
                self._log_operation_failed(
                    "Update item", old_name, inventory_id
                )
        except Exception as e:
            _LOGGER.error(
                f"Failed to update item {
                    old_name} in inventory {inventory_id}: {e}"
            )
