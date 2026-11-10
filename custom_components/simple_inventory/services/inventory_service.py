"""Inventory management service handler."""

from __future__ import annotations

import logging
from typing import Any, cast

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util.json import JsonObjectType, JsonValueType

from ..const import (
    DOMAIN,
    FIELD_ALIASES,
    FIELD_AMOUNT,
    FIELD_BARCODE,
    FIELD_BATCH_ID,
    FIELD_EXPIRY_DATE,
    FIELD_FROM_LOCATION,
    FIELD_ITEMS,
    FIELD_LOCATION,
    FIELD_NAME,
    FIELD_PURCHASED_AT,
    FIELD_QUANTITY,
    FIELD_TO_LOCATION,
    FIELD_UNIT_PRICE,
)
from ..coordinator import SimpleInventoryCoordinator
from ..data import get_hub, get_repository
from ..entries import inventory_display_name
from ..item_fields import UPDATABLE_ITEM_FIELDS
from ..storage.repository import InventoryRepository
from ..todo_manager import TodoManager
from ..types import (
    AddItemServiceData,
    GetItemsServiceData,
    InventoryItem,
    UpdateItemServiceData,
)
from .base_service import BaseServiceHandler
from .resolvers import inventory_not_loaded_error, resolve_inventory_id, resolve_item_name

_LOGGER = logging.getLogger(__name__)


_BATCH_UPDATE_KEYS = (
    FIELD_QUANTITY,
    FIELD_EXPIRY_DATE,
    FIELD_LOCATION,
    FIELD_UNIT_PRICE,
    FIELD_PURCHASED_AT,
)
_TRANSFER_KEYS = (FIELD_AMOUNT, FIELD_FROM_LOCATION, FIELD_BATCH_ID)


class InventoryService(BaseServiceHandler):
    """Handle inventory-specific operations (add, remove, update items)."""

    _UPDATEABLE_FIELDS = UPDATABLE_ITEM_FIELDS

    def __init__(
        self,
        hass: HomeAssistant,
        todo_manager: TodoManager,
    ) -> None:
        """Initialize inventory service with optional todo manager."""
        super().__init__(hass)
        self.todo_manager = todo_manager
        self._repository: InventoryRepository | None = get_repository(hass)

    def _extract_update_fields(self, data: UpdateItemServiceData) -> dict[str, Any]:
        """Extract updateable fields from service call data."""
        update_data: dict[str, Any] = {}
        for field in self._UPDATEABLE_FIELDS:
            if field in data:
                update_data[field] = data.get(field)
        return update_data

    # ---------------------------------------------------------------------
    # Service handlers (write operations)
    # ---------------------------------------------------------------------

    async def async_add_item(self, call: ServiceCall) -> None:
        item_data = cast(AddItemServiceData, call.data)
        inventory_id = await resolve_inventory_id(
            self.hass, item_data.get("inventory_id"), item_data.get("inventory_name")
        )
        name = item_data[FIELD_NAME]

        coordinator = self._require_coordinator(inventory_id)
        if coordinator is None:
            raise inventory_not_loaded_error(self.hass, inventory_id)

        item_kwargs = self._extract_item_kwargs(
            item_data, ["inventory_id", "inventory_name", "barcode", "aliases"]
        )
        barcode = item_data.get(FIELD_BARCODE)
        aliases = item_data.get(FIELD_ALIASES)

        item_id = await coordinator.async_add_item(
            inventory_id, barcode=barcode, aliases=aliases, **item_kwargs
        )
        if not item_id:
            self._log_operation_failed("Add item", name, inventory_id)
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_auto_add_config",
                translation_placeholders={
                    "name": name,
                    "inventory": inventory_display_name(self.hass, inventory_id),
                },
            )

        item = await coordinator.async_get_item(inventory_id, name.strip())
        if item:
            await self.todo_manager.async_sync(str(item[FIELD_NAME]), cast(InventoryItem, item))

        self._log_success(inventory_id, "Added item", name)

    async def async_remove_item(self, call: ServiceCall) -> None:
        inventory_id_raw, inventory_name, name, barcode = self._get_inventory_name_barcode(call)
        inventory_id = await resolve_inventory_id(self.hass, inventory_id_raw, inventory_name)
        display_name = name or barcode or "unknown"

        coordinator = self._require_coordinator(inventory_id)
        if coordinator is None:
            raise inventory_not_loaded_error(self.hass, inventory_id)

        if name:
            # Destructive: exact name or alias only, never a fuzzy neighbour.
            name = await resolve_item_name(coordinator, inventory_id, name, fuzzy=False)
            display_name = name

        # Resolve the item before removal so its todo entry can be cleaned up.
        resolved_name = name
        if not resolved_name and barcode:
            match = await coordinator.async_get_item_by_barcode(inventory_id, barcode)
            if match:
                resolved_name = match.get(FIELD_NAME)

        item = (
            await coordinator.async_get_item(inventory_id, resolved_name) if resolved_name else None
        )

        if not await coordinator.async_remove_item(inventory_id, name, barcode=barcode):
            self._log_item_not_found("Remove item", display_name, inventory_id)
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="item_not_found",
                translation_placeholders={
                    "name": display_name,
                    "inventory": inventory_display_name(self.hass, inventory_id),
                },
            )

        if item:
            await self.todo_manager.remove_item_entry(
                str(item[FIELD_NAME]), cast(InventoryItem, item)
            )

        self._log_success(inventory_id, "Removed item", display_name)

    async def async_update_item(self, call: ServiceCall) -> None:
        data = cast(UpdateItemServiceData, call.data)
        inventory_id = await resolve_inventory_id(
            self.hass, data.get("inventory_id"), data.get("inventory_name")
        )
        old_name = data["old_name"]
        new_name = data[FIELD_NAME]
        barcode = data.get(FIELD_BARCODE)
        aliases = data.get(FIELD_ALIASES)

        coordinator = self._require_coordinator(inventory_id)
        if coordinator is None:
            raise inventory_not_loaded_error(self.hass, inventory_id)

        old_name = await resolve_item_name(coordinator, inventory_id, old_name)

        existing_item = await coordinator.async_get_item(inventory_id, old_name)
        if not existing_item:
            self._log_item_not_found("Update item", old_name, inventory_id)
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="item_not_found",
                translation_placeholders={
                    "name": old_name,
                    "inventory": inventory_display_name(self.hass, inventory_id),
                },
            )

        update_data = self._extract_update_fields(data)

        updated = await coordinator.async_update_item(
            inventory_id,
            old_name,
            new_name,
            barcode=barcode,
            aliases=aliases,
            **update_data,
        )
        if not updated:
            self._log_operation_failed("Update item", old_name, inventory_id)
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="update_item_failed",
                translation_placeholders={
                    "name": old_name,
                    "inventory": inventory_display_name(self.hass, inventory_id),
                },
            )

        updated_item = cast(
            InventoryItem | None, await coordinator.async_get_item(inventory_id, new_name.strip())
        )
        existing = cast(InventoryItem, existing_item)
        if updated_item:
            await self.todo_manager.async_sync(
                str(updated_item[FIELD_NAME]), updated_item, previous=existing
            )
        else:
            await self.todo_manager.remove_item_entry(str(existing.get(FIELD_NAME, "")), existing)

        self._log_success(inventory_id, f"Updated item: {old_name} -> {new_name}", new_name)

    async def async_update_batch(self, call: ServiceCall) -> None:
        """Edit one batch, then re-sync the item's todo entry."""
        coordinator, inventory_id = await self._coordinator_for_call(call)
        fields = {k: call.data[k] for k in _BATCH_UPDATE_KEYS if k in call.data}
        name = await coordinator.async_update_batch(
            inventory_id, call.data[FIELD_BATCH_ID], **fields
        )
        await self._sync_after_batch_change(coordinator, inventory_id, name)

    async def async_remove_batch(self, call: ServiceCall) -> None:
        """Delete one batch, then re-sync the item's todo entry."""
        coordinator, inventory_id = await self._coordinator_for_call(call)
        name = await coordinator.async_remove_batch(inventory_id, call.data[FIELD_BATCH_ID])
        await self._sync_after_batch_change(coordinator, inventory_id, name)

    async def async_transfer_item(self, call: ServiceCall) -> None:
        """Move stock between locations; no todo sync, the item's total is unchanged."""
        coordinator, inventory_id = await self._coordinator_for_call(call)
        name = call.data.get(FIELD_NAME)
        if name:
            name = await resolve_item_name(coordinator, inventory_id, name)
        extras = {key: call.data[key] for key in _TRANSFER_KEYS if key in call.data}
        await coordinator.async_transfer_item(
            inventory_id,
            name,
            barcode=call.data.get(FIELD_BARCODE),
            to_location=call.data[FIELD_TO_LOCATION],
            **extras,
        )

    async def _sync_after_batch_change(
        self, coordinator: SimpleInventoryCoordinator, inventory_id: str, name: str
    ) -> None:
        item = await coordinator.async_get_item(inventory_id, name)
        if item:
            await self.todo_manager.async_sync(name, cast(InventoryItem, item))

    # ---------------------------------------------------------------------
    # Query helpers
    # ---------------------------------------------------------------------

    async def async_get_items(self, call: ServiceCall) -> JsonObjectType:
        """Return full list of items for an inventory."""
        data = cast(GetItemsServiceData, call.data)

        inventory_id = await resolve_inventory_id(
            self.hass, data.get("inventory_id"), data.get("inventory_name")
        )

        coordinator = self._require_coordinator(inventory_id)
        if coordinator:
            items_list: list[dict[str, Any]] = await coordinator.async_list_items(inventory_id)
        else:
            repo = get_repository(self.hass)
            if repo is None:
                raise inventory_not_loaded_error(self.hass, inventory_id)
            items_list = await repo.list_items_with_details(inventory_id)

        items_list.sort(key=lambda item: cast(str, item.get(FIELD_NAME, "")).lower())
        return cast(JsonObjectType, {FIELD_ITEMS: cast(list[JsonValueType], items_list)})

    async def async_get_items_from_all_inventories(self, call: ServiceCall) -> JsonObjectType:
        """Return full list of items grouped by inventory."""
        hub = get_hub(self.hass)
        inventories = [] if hub is None else await hub.async_items_by_inventory()
        return cast(JsonObjectType, {"inventories": cast(list[JsonValueType], inventories)})
