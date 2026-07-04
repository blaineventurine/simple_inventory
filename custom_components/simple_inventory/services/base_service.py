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
from .domain_data import get_coordinators

_LOGGER = logging.getLogger(__name__)


class BaseServiceHandler:
    """Base class for service handlers with common functionality."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the base service handler."""
        self.hass = hass

    # ------------------------------------------------------------------
    # Coordinator helpers
    # ------------------------------------------------------------------

    def _get_coordinator_optional(self, inventory_id: str) -> SimpleInventoryCoordinator | None:
        return get_coordinators(self.hass).get(inventory_id)

    def _require_coordinator(self, inventory_id: str) -> SimpleInventoryCoordinator | None:
        coordinator = self._get_coordinator_optional(inventory_id)
        if coordinator is None:
            _LOGGER.error(
                "No coordinator loaded for inventory '%s'; cannot process service call",
                inventory_id,
            )
        return coordinator

    # ------------------------------------------------------------------
    # Common logging / persistence helpers
    # ------------------------------------------------------------------

    async def _save_and_log_success(
        self,
        coordinator: SimpleInventoryCoordinator,
        inventory_id: str,
        operation: str,
        item_name: str,
    ) -> None:
        """Save data and log successful operation."""
        await coordinator.async_save_data(inventory_id)
        _LOGGER.debug("%s: %s in inventory: %s", operation, item_name, inventory_id)

    def _log_item_not_found(self, operation: str, item_name: str, inventory_id: str) -> None:
        """Log when an item is not found."""
        _LOGGER.warning(
            "%s failed - Item not found: %s in inventory: %s",
            operation,
            item_name,
            inventory_id,
        )

    def _log_operation_failed(self, operation: str, item_name: str, inventory_id: str) -> None:
        """Log when an operation fails."""
        _LOGGER.error(
            "%s failed for item: %s in inventory: %s",
            operation,
            item_name,
            inventory_id,
        )

    # ------------------------------------------------------------------
    # Misc helpers
    # ------------------------------------------------------------------

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

    def _get_inventory_name_barcode(
        self, call: ServiceCall
    ) -> tuple[str | None, str | None, str | None, str | None]:
        """Extract inventory_id, inventory_name, optional name, and optional barcode."""
        data = call.data
        return (
            data.get("inventory_id"),
            data.get("inventory_name"),
            data.get("name"),
            data.get("barcode"),
        )
