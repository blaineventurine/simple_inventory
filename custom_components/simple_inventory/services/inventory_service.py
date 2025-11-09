"""Inventory management service handler."""

import logging
from typing import Any, cast

from homeassistant.core import HomeAssistant, ServiceCall

from ..coordinator import SimpleInventoryCoordinator
from ..todo_manager import TodoManager
from ..types import (
    AddItemServiceData,
    InventoryItem,
    RemoveItemServiceData,
    UpdateItemServiceData,
)
from .base_service import BaseServiceHandler

_LOGGER = logging.getLogger(__name__)


class InventoryService(BaseServiceHandler):
    """Handle inventory-specific operations (add, remove, update items)."""

    _UPDATEABLE_FIELDS = [
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

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: SimpleInventoryCoordinator,
        todo_manager: TodoManager,
    ):
        """Initialize inventory service with optional todo manager."""
        super().__init__(hass, coordinator)
        self.todo_manager = todo_manager

    async def _handle_todo_auto_add(self, item_name: str, item: InventoryItem) -> None:
        """Handle auto-add to todo list based on item configuration."""
        quantity = item.get("quantity", 0)
        auto_add_quantity = item.get("auto_add_to_list_quantity", 0)
        auto_add_enabled = item.get("auto_add_enabled", False)

        if auto_add_enabled and quantity <= auto_add_quantity:
            await self.todo_manager.check_and_add_item(item_name, item)
        else:
            await self.todo_manager.check_and_remove_item(item_name, item)

    def _extract_update_fields(self, data: UpdateItemServiceData) -> dict[str, Any]:
        """Extract updateable fields from service call data."""
        update_data: dict[str, Any] = {}
        for field in self._UPDATEABLE_FIELDS:
            if field in data:
                update_data[field] = data.get(field)
        return update_data

    async def async_add_item(self, call: ServiceCall) -> None:
        """Add an item to the inventory."""
        item_data: AddItemServiceData = cast(AddItemServiceData, call.data)
        inventory_id = item_data["inventory_id"]
        name = item_data["name"]
        item_kwargs = self._extract_item_kwargs(item_data, ["inventory_id"])

        try:
            self.coordinator.add_item(inventory_id, **item_kwargs)
            item = self.coordinator.get_item(inventory_id, name)

            if item:
                await self._handle_todo_auto_add(name, item)

            await self._save_and_log_success(inventory_id, "Added item", name)

        except Exception as e:
            _LOGGER.error(
                "Failed to add item %s to inventory %s: %s",
                name,
                inventory_id,
                e,
            )

    async def async_remove_item(self, call: ServiceCall) -> None:
        """Remove an item from the inventory."""
        data: RemoveItemServiceData = cast(RemoveItemServiceData, call.data)
        inventory_id = data["inventory_id"]
        name = data["name"]

        try:
            item = self.coordinator.get_item(inventory_id, name)

            if self.coordinator.remove_item(inventory_id, name):
                if item:
                    await self.todo_manager.check_and_remove_item(name, item)

                await self._save_and_log_success(inventory_id, "Removed item", name)
            else:
                self._log_item_not_found("Remove item", name, inventory_id)

        except Exception as e:
            _LOGGER.error(
                "Failed to remove item %s from inventory %s: %s",
                name,
                inventory_id,
                e,
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

        update_data = self._extract_update_fields(data)

        try:
            if not self.coordinator.update_item(inventory_id, old_name, new_name, **update_data):
                self._log_operation_failed("Update item", old_name, inventory_id)
                return

            updated_item = self.coordinator.get_item(inventory_id, new_name)
            if updated_item:
                await self._handle_todo_auto_add(new_name, updated_item)

            await self._save_and_log_success(
                inventory_id,
                f"Updated item: {old_name} -> {new_name}",
                new_name,
            )

        except Exception as e:
            _LOGGER.error(
                "Failed to update item %s in inventory %s: %s",
                old_name,
                inventory_id,
                e,
            )
