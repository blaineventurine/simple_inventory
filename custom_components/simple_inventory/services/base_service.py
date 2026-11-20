"""Base service handler with common functionality."""

import logging
from typing import Any, cast

from homeassistant.core import HomeAssistant, ServiceCall

from ..const import FIELD_BARCODE, FIELD_NAME
from ..coordinator import SimpleInventoryCoordinator
from ..data import get_coordinators
from ..types import (
    AddItemServiceData,
    RemoveItemServiceData,
    UpdateItemServiceData,
)
from .resolvers import inventory_not_loaded_error, resolve_inventory_id

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

    async def _coordinator_for_call(
        self, call: ServiceCall
    ) -> tuple[SimpleInventoryCoordinator, str]:
        """Resolve the call's inventory and return its loaded coordinator.

        Raises ``inventory_not_loaded`` when no coordinator exists for it.
        """
        inventory_id = await resolve_inventory_id(
            self.hass, call.data.get("inventory_id"), call.data.get("inventory_name")
        )
        coordinator = self._require_coordinator(inventory_id)
        if coordinator is None:
            raise inventory_not_loaded_error(self.hass, inventory_id)
        return coordinator, inventory_id

    # ------------------------------------------------------------------
    # Common logging helpers
    # ------------------------------------------------------------------

    def _log_success(self, inventory_id: str, operation: str, item_name: str) -> None:
        """Log a successful operation (the coordinator already signalled the change)."""
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
        return data["inventory_id"], data[FIELD_NAME]

    def _get_inventory_name_barcode(
        self, call: ServiceCall
    ) -> tuple[str | None, str | None, str | None, str | None]:
        """Extract inventory_id, inventory_name, optional name, and optional barcode."""
        data = call.data
        return (
            data.get("inventory_id"),
            data.get("inventory_name"),
            data.get(FIELD_NAME),
            data.get(FIELD_BARCODE),
        )
