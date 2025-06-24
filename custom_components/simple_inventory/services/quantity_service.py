"""Quantity management service handler."""

import logging

from homeassistant.core import HomeAssistant, ServiceCall

from ..coordinator import SimpleInventoryCoordinator
from ..todo_manager import TodoManager
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

    async def async_increment_item(self, call: ServiceCall) -> None:
        """Increment item quantity."""
        inventory_id, name = self._get_inventory_and_name(call)
        amount = call.data.get("amount", 1)

        try:
            if self.coordinator.increment_item(inventory_id, name, amount):
                await self._save_and_log_success(
                    inventory_id, f"Incremented {name} by {amount}", name
                )
            else:
                self._log_item_not_found("Increment item", name, inventory_id)
        except Exception as e:
            _LOGGER.error(
                f"Failed to increment item {
                    name} in inventory {inventory_id}: {e}"
            )

    async def async_decrement_item(self, call: ServiceCall) -> None:
        """Decrement item quantity and check if it should be added to todo list."""
        inventory_id, name = self._get_inventory_and_name(call)
        amount = call.data.get("amount", 1)

        try:
            if self.coordinator.decrement_item(inventory_id, name, amount):
                item_data = self.coordinator.get_item(inventory_id, name)
                if item_data:
                    await self.todo_manager.check_and_add_item(name, item_data)

                await self._save_and_log_success(
                    inventory_id, f"Decremented {name} by {amount}", name
                )
            else:
                self._log_item_not_found("Decrement item", name, inventory_id)
        except Exception as e:
            _LOGGER.error(
                f"Failed to decrement item {
                    name} in inventory {inventory_id}: {e}"
            )
