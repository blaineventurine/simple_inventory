"""Base service handler with common functionality."""

import logging
from typing import Any, cast

from homeassistant.core import HomeAssistant, ServiceCall

from ..coordinator import SimpleInventoryCoordinator
from ..types import (
    AddItemServiceData,
    RemoveItemServiceData,
    UpdateItemServiceData,
)

_LOGGER = logging.getLogger(__name__)


class BaseServiceHandler:
    """Base class for service handlers with common functionality."""

    def __init__(
        self, hass: HomeAssistant, coordinator: SimpleInventoryCoordinator
    ) -> None:
        """Initialize the base service handler."""
        self.hass = hass
        self.coordinator = coordinator

    async def _save_and_log_success(
        self, inventory_id: str, operation: str, item_name: str
    ) -> None:
        """Save data and log successful operation."""
        await self.coordinator.async_save_data(inventory_id)
        _LOGGER.info(f"{operation}: {item_name} in inventory: {inventory_id}")

    def _log_item_not_found(
        self, operation: str, item_name: str, inventory_id: str
    ) -> None:
        """Log when an item is not found."""
        _LOGGER.warning(
            f"{operation} failed - Item not found: {item_name} in inventory: {inventory_id}"
        )

    def _log_operation_failed(
        self, operation: str, item_name: str, inventory_id: str
    ) -> None:
        """Log when an operation fails."""
        _LOGGER.error(
            f"{operation} failed for item: {
                item_name} in inventory: {inventory_id}"
        )

    def _extract_item_kwargs(
        self,
        data: AddItemServiceData | UpdateItemServiceData,
        exclude_keys: list[str],
    ) -> dict[str, Any]:
        """Extract item data excluding specified keys."""
        return {k: v for k, v in data.items() if k not in exclude_keys}

    def _get_inventory_and_name(self, call: ServiceCall) -> tuple[str, str]:
        """Extract inventory_id and name from service call."""
        data: RemoveItemServiceData = cast(RemoveItemServiceData, call.data)
        return data["inventory_id"], data["name"]
