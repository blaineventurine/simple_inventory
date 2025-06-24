"""Service handlers for Simple Inventory integration."""

import logging

from homeassistant.core import HomeAssistant, ServiceCall

from ..coordinator import SimpleInventoryCoordinator
from ..todo_manager import TodoManager
from .inventory_service import InventoryService
from .quantity_service import QuantityService

_LOGGER = logging.getLogger(__name__)


class ServiceHandler:
    """Main service handler that coordinates specialized service handlers."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: SimpleInventoryCoordinator,
        todo_manager: TodoManager,
    ):
        """Initialize the main service handler."""
        self.hass = hass
        self.coordinator = coordinator
        self.todo_manager = todo_manager
        self.inventory_service = InventoryService(hass, coordinator)
        self.quantity_service = QuantityService(hass, coordinator, todo_manager)

    async def async_add_item(self, call: ServiceCall) -> None:
        """Add an item to the inventory."""
        await self.inventory_service.async_add_item(call)

    async def async_remove_item(self, call: ServiceCall) -> None:
        """Remove an item from the inventory."""
        await self.inventory_service.async_remove_item(call)

    async def async_update_item(self, call: ServiceCall) -> None:
        """Update an existing item with new values."""
        await self.inventory_service.async_update_item(call)

    async def async_increment_item(self, call: ServiceCall) -> None:
        """Increment item quantity."""
        await self.quantity_service.async_increment_item(call)

    async def async_decrement_item(self, call: ServiceCall) -> None:
        """Decrement item quantity."""
        await self.quantity_service.async_decrement_item(call)


__all__ = ["ServiceHandler", "InventoryService", "QuantityService"]
