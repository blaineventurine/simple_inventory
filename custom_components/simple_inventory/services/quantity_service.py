"""Quantity management service handler."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Literal, cast

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError

from ..const import (
    DOMAIN,
    FIELD_AMOUNT,
    FIELD_BATCH_ID,
    FIELD_EXPIRY_DATE,
    FIELD_LOCATION,
    FIELD_NAME,
    FIELD_PRICE,
    FIELD_PURCHASED_AT,
)
from ..coordinator import SimpleInventoryCoordinator
from ..coordinator._core import scan_lookup_result
from ..data import get_coordinators, get_hub
from ..entries import inventory_display_name
from ..todo_manager import TodoManager
from ..types import InventoryItem
from .base_service import BaseServiceHandler
from .resolvers import inventory_not_loaded_error, resolve_item_name

_LOGGER = logging.getLogger(__name__)

# Batch keys each quantity operation forwards to the coordinator untouched.
_BATCH_KEYS: dict[str, tuple[str, ...]] = {
    "increment": (FIELD_EXPIRY_DATE, FIELD_LOCATION, FIELD_PURCHASED_AT),
    "decrement": (FIELD_LOCATION, FIELD_BATCH_ID),
}
# A scan may increment or decrement, so it accepts both sets.
SCAN_BATCH_KEYS: tuple[str, ...] = (
    FIELD_EXPIRY_DATE,
    FIELD_LOCATION,
    FIELD_PURCHASED_AT,
    FIELD_BATCH_ID,
)


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
            [
                SimpleInventoryCoordinator,
                str,
                str | None,
                float,
                str | None,
                float | None,
                dict[str, Any],
            ],
            Awaitable[bool],
        ],
    ) -> None:
        _, _, name, barcode = self._get_inventory_name_barcode(call)
        coordinator, inventory_id = await self._coordinator_for_call(call)
        amount = float(call.data.get(FIELD_AMOUNT, 1))
        price: float | None = call.data.get(FIELD_PRICE)
        display_name = name or barcode or "unknown"

        if name:
            name = await resolve_item_name(coordinator, inventory_id, name)
            display_name = name

        extras = {key: call.data[key] for key in _BATCH_KEYS[operation] if key in call.data}
        if not await coordinator_method(
            coordinator, inventory_id, name, amount, barcode, price, extras
        ):
            self._log_item_not_found(f"{operation.capitalize()} item", display_name, inventory_id)
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="item_not_found",
                translation_placeholders={
                    "name": display_name,
                    "inventory": inventory_display_name(self.hass, inventory_id),
                },
            )

        resolved_name = name
        if not resolved_name and barcode:
            match = await coordinator.async_get_item_by_barcode(inventory_id, barcode)
            if match:
                resolved_name = match.get(FIELD_NAME)

        if resolved_name:
            item_data = await coordinator.async_get_item(inventory_id, resolved_name)
            if item_data:
                await self.todo_manager.async_sync(resolved_name, cast(InventoryItem, item_data))

        self._log_success(
            inventory_id, f"{operation.capitalize()}ed {display_name} by {amount}", display_name
        )

    async def async_increment_item(self, call: ServiceCall) -> None:
        await self._handle_quantity_change(
            call,
            "increment",
            lambda coordinator, inv_id, item_name, amt, bc, p, extra: (
                coordinator.async_increment_item(
                    inv_id, item_name, amt, barcode=bc, price=p, **extra
                )
            ),
        )

    async def async_decrement_item(self, call: ServiceCall) -> None:
        await self._handle_quantity_change(
            call,
            "decrement",
            lambda coordinator, inv_id, item_name, amt, bc, p, extra: (
                coordinator.async_decrement_item(
                    inv_id, item_name, amt, barcode=bc, price=p, **extra
                )
            ),
        )

    async def async_scan_barcode(
        self,
        barcode: str,
        action: str,
        amount: float = 1.0,
        inventory_id: str | None = None,
        price: float | None = None,
        **batch_fields: str,
    ) -> dict[str, Any]:
        """Scan a barcode, perform the action, and sync the item's todo entry.

        This is the single source of truth for all barcode scan operations,
        regardless of whether the call originates from a service call or WebSocket.
        """
        coordinators = get_coordinators(self.hass)
        hub = get_hub(self.hass)
        if hub is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="no_inventories_configured"
            )

        if inventory_id:
            coordinator = coordinators.get(inventory_id)
            if coordinator is None:
                raise inventory_not_loaded_error(self.hass, inventory_id)
            result = await coordinator.async_scan_barcode(
                barcode, action, amount, inventory_id, price=price, **batch_fields
            )
        else:
            item = await hub.async_barcode_item(barcode)
            item_inventory_id = str(item["inventory_id"])
            if action == "lookup":
                # Read-only, like lookup_by_barcode: the inventory need not be loaded.
                return scan_lookup_result(item, item_inventory_id)
            coordinator = coordinators.get(item_inventory_id)
            if coordinator is None:
                raise inventory_not_loaded_error(self.hass, item_inventory_id)
            result = await coordinator.async_scan_item(
                item, item_inventory_id, action, amount, price, **batch_fields
            )

        if result.get("success") and action in ("increment", "decrement"):
            item_name: str = result["item_name"]
            resolved_id: str = result["inventory_id"]
            item_data = await coordinator.async_get_item(resolved_id, item_name)
            if item_data:
                await self.todo_manager.async_sync(item_name, cast(InventoryItem, item_data))

        return result
