"""Quantity management service handler."""

import logging
from typing import Callable, Literal

from homeassistant.core import HomeAssistant, ServiceCall

from ..coordinator import SimpleInventoryCoordinator
from ..todo_manager import TodoManager
from ..types import InventoryItem
from .base_service import BaseServiceHandler

_LOGGER = logging.getLogger(__name__)


class QuantityService(BaseServiceHandler):
    """Handle quantity operations (increment, decrement)."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: SimpleInventoryCoordinator,
        todo_manager: TodoManager,
    ):
        """Initialize quantity service with todo manager."""
        super().__init__(hass, coordinator)
        self.todo_manager = todo_manager

    async def _handle_quantity_change(
        self,
        call: ServiceCall,
        operation: Literal["increment", "decrement"],
        coordinator_method: Callable,
        todo_method: Callable,
    ) -> None:
        """Handle quantity change operations with todo list integration."""
        inventory_id, name = self._get_inventory_and_name(call)
        amount = call.data.get("amount", 1)

        try:
            if coordinator_method(inventory_id, name, amount):
                item_data = self.coordinator.get_item(inventory_id, name)
                if item_data:
                    await todo_method(name, item_data)

                await self._save_and_log_success(
                    inventory_id, f"{operation.capitalize()}ed {name} by {amount}", name
                )
            else:
                self._log_item_not_found(f"{operation.capitalize()} item", name, inventory_id)

        except Exception as e:
            _LOGGER.error(
                "Failed to %s item %s in inventory %s: %s", operation, name, inventory_id, e
            )

    async def async_increment_item(self, call: ServiceCall) -> None:
        """Increment item quantity."""
        await self._handle_quantity_change(
            call,
            "increment",
            self.coordinator.increment_item,
            self.todo_manager.check_and_remove_item,
        )

    async def async_decrement_item(self, call: ServiceCall) -> None:
        """Decrement item quantity and check if it should be added to todo list."""
        await self._handle_quantity_change(
            call,
            "decrement",
            self.coordinator.decrement_item,
            self.todo_manager.check_and_add_item,
        )

    async def async_update_todo_status(self, item_name: str, item_data: InventoryItem) -> None:
        """Update todo list status based on current quantity.

        This can be called after editing an item to ensure todo list is in sync.
        """
        if not item_data:
            return

        quantity = item_data.get("quantity", 0)
        auto_add_quantity = item_data.get("auto_add_to_list_quantity", 0)

        if quantity <= auto_add_quantity:
            await self.todo_manager.check_and_add_item(item_name, item_data)
        else:
            await self.todo_manager.check_and_remove_item(item_name, item_data)
