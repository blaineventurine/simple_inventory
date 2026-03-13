"""Quantity management service handler."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Literal, cast

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError

from ..coordinator import SimpleInventoryCoordinator
from ..todo_manager import TodoManager
from ..types import InventoryItem
from .base_service import BaseServiceHandler
from .domain_data import get_coordinators

_LOGGER = logging.getLogger(__name__)


class QuantityService(BaseServiceHandler):
    """Handle quantity operations (increment, decrement)."""

    def __init__(
        self,
        hass: HomeAssistant,
        todo_manager: TodoManager,
    ) -> None:
        """Initialize quantity service with todo manager."""
        super().__init__(hass)
        self.todo_manager = todo_manager

    # ------------------------------------------------------------------
    # Core handlers
    # ------------------------------------------------------------------

    async def _handle_quantity_change(
        self,
        call: ServiceCall,
        operation: Literal["increment", "decrement"],
        coordinator_method: Callable[
            [SimpleInventoryCoordinator, str, str | None, float, str | None, float | None],
            Awaitable[bool],
        ],
        todo_method: Callable[[str, InventoryItem], Awaitable[bool]],
    ) -> None:
        inventory_id, name, barcode = self._get_inventory_name_barcode(call)
        amount = float(call.data.get("amount", 1))
        price: float | None = call.data.get("price")
        display_name = name or barcode or "unknown"

        coordinator = self._require_coordinator(inventory_id)
        if coordinator is None:
            return

        try:
            if await coordinator_method(coordinator, inventory_id, name, amount, barcode, price):
                resolved_name = name
                if not resolved_name and barcode:
                    matches = await coordinator.async_lookup_by_barcode(barcode)
                    match = next(
                        (m for m in matches if m.get("inventory_id") == inventory_id), None
                    )
                    if match:
                        resolved_name = match.get("name")

                if resolved_name:
                    item_data = await coordinator.async_get_item(inventory_id, resolved_name)
                    if item_data:
                        await todo_method(resolved_name, cast(InventoryItem, item_data))

                await self._save_and_log_success(
                    coordinator,
                    inventory_id,
                    f"{operation.capitalize()}ed {display_name} by {amount}",
                    display_name,
                )
            else:
                self._log_item_not_found(
                    f"{operation.capitalize()} item",
                    display_name,
                    inventory_id,
                )

        except Exception as exc:
            _LOGGER.error(
                "Failed to %s item %s in inventory %s: %s",
                operation,
                display_name,
                inventory_id,
                exc,
            )

    async def async_increment_item(self, call: ServiceCall) -> None:
        await self._handle_quantity_change(
            call,
            "increment",
            lambda coordinator, inv_id, item_name, amt, bc, p: (
                coordinator.async_increment_item(inv_id, item_name, amt, barcode=bc, price=p)
            ),
            self.todo_manager.check_and_remove_item,
        )

    async def async_decrement_item(self, call: ServiceCall) -> None:
        await self._handle_quantity_change(
            call,
            "decrement",
            lambda coordinator, inv_id, item_name, amt, bc, p: (
                coordinator.async_decrement_item(inv_id, item_name, amt, barcode=bc, price=p)
            ),
            self.todo_manager.check_and_add_item,
        )

    async def async_scan_barcode(
        self,
        barcode: str,
        action: str,
        amount: float = 1.0,
        inventory_id: str | None = None,
        price: float | None = None,
    ) -> dict[str, Any]:
        """Scan a barcode, perform the action, and update the todo list.

        This is the single source of truth for all barcode scan operations,
        regardless of whether the call originates from a service call or WebSocket.
        """
        coordinators = get_coordinators(self.hass)
        if not coordinators:
            raise ServiceValidationError("No inventories configured")

        if inventory_id:
            coordinator = coordinators.get(inventory_id)
            if coordinator is None:
                raise ServiceValidationError(
                    f"No coordinator available for inventory '{inventory_id}'"
                )
        else:
            coordinator = next(iter(coordinators.values()))

        result = await coordinator.async_scan_barcode(
            barcode, action, amount, inventory_id, price=price
        )

        if result.get("success") and action in ("increment", "decrement"):
            item_name: str = result["item_name"]
            resolved_id: str = result["inventory_id"]
            item_data = await coordinator.async_get_item(resolved_id, item_name)
            if item_data:
                if action == "decrement":
                    await self.todo_manager.check_and_add_item(
                        item_name, cast(InventoryItem, item_data)
                    )
                else:
                    await self.todo_manager.check_and_remove_item(
                        item_name, cast(InventoryItem, item_data)
                    )

        return result

    async def async_update_todo_status(self, item_name: str, item_data: InventoryItem) -> None:
        """Update todo list status based on current quantity (manual sync hook)."""
        quantity = item_data.get("quantity", 0)
        auto_add_quantity = item_data.get("auto_add_to_list_quantity", 0)

        if quantity <= auto_add_quantity:
            await self.todo_manager.check_and_add_item(item_name, item_data)
        else:
            await self.todo_manager.check_and_remove_item(item_name, item_data)
