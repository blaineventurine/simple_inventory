"""Inventory management service handler."""

from __future__ import annotations

import logging
from typing import Any, cast

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util.json import JsonObjectType, JsonValueType

from ..const import (
    DOMAIN,
    FIELD_AUTO_ADD_ENABLED,
    FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED,
    FIELD_AUTO_ADD_TO_LIST_QUANTITY,
    FIELD_CATEGORY,
    FIELD_DESCRIPTION,
    FIELD_DESIRED_QUANTITY,
    FIELD_EXPIRY_ALERT_DAYS,
    FIELD_EXPIRY_DATE,
    FIELD_LOCATION,
    FIELD_PRICE,
    FIELD_QUANTITY,
    FIELD_TODO_LIST,
    FIELD_TODO_QUANTITY_PLACEMENT,
    FIELD_UNIT,
)
from ..storage.repository import InventoryRepository
from ..todo_manager import TodoManager
from ..types import (
    AddItemServiceData,
    GetAllItemsServiceData,
    GetItemsServiceData,
    InventoryItem,
    UpdateItemServiceData,
)
from .base_service import BaseServiceHandler
from .domain_data import get_coordinators, get_repository

_LOGGER = logging.getLogger(__name__)


class InventoryService(BaseServiceHandler):
    """Handle inventory-specific operations (add, remove, update items)."""

    _UPDATEABLE_FIELDS = [
        FIELD_AUTO_ADD_ENABLED,
        FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED,
        FIELD_AUTO_ADD_TO_LIST_QUANTITY,
        FIELD_CATEGORY,
        FIELD_DESCRIPTION,
        FIELD_DESIRED_QUANTITY,
        FIELD_EXPIRY_ALERT_DAYS,
        FIELD_EXPIRY_DATE,
        FIELD_LOCATION,
        FIELD_PRICE,
        FIELD_QUANTITY,
        FIELD_TODO_LIST,
        FIELD_TODO_QUANTITY_PLACEMENT,
        FIELD_UNIT,
    ]

    def __init__(
        self,
        hass: HomeAssistant,
        todo_manager: TodoManager,
    ) -> None:
        """Initialize inventory service with optional todo manager."""
        super().__init__(hass)
        self.todo_manager = todo_manager
        self._repository: InventoryRepository | None = get_repository(hass)

    # ---------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------

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

    # ---------------------------------------------------------------------
    # Service handlers (write operations)
    # ---------------------------------------------------------------------

    async def async_add_item(self, call: ServiceCall) -> None:
        item_data = cast(AddItemServiceData, call.data)
        inventory_id = item_data["inventory_id"]
        name = item_data["name"]

        coordinator = self._require_coordinator(inventory_id)
        if coordinator is None:
            return

        item_kwargs = self._extract_item_kwargs(item_data, ["inventory_id", "barcode"])
        barcode = item_data.get("barcode")

        try:
            item_id = await coordinator.async_add_item(inventory_id, barcode=barcode, **item_kwargs)
            if not item_id:
                self._log_operation_failed("Add item", name, inventory_id)
                return

            item = await coordinator.async_get_item(inventory_id, name)
            if item:
                await self._handle_todo_auto_add(name, cast(InventoryItem, item))

            await self._save_and_log_success(coordinator, inventory_id, "Added item", name)

        except HomeAssistantError:
            raise
        except Exception as exc:
            _LOGGER.error(
                "Failed to add item %s to inventory %s: %s",
                name,
                inventory_id,
                exc,
            )

    async def async_remove_item(self, call: ServiceCall) -> None:
        inventory_id, name, barcode = self._get_inventory_name_barcode(call)
        display_name = name or barcode or "unknown"

        coordinator = self._require_coordinator(inventory_id)
        if coordinator is None:
            return

        try:
            # Resolve name for todo cleanup before removal
            resolved_name = name
            if not resolved_name and barcode:
                matches = await coordinator.async_lookup_by_barcode(barcode)
                match = next((m for m in matches if m.get("inventory_id") == inventory_id), None)
                if match:
                    resolved_name = match.get("name")

            if resolved_name:
                item = await coordinator.async_get_item(inventory_id, resolved_name)
            else:
                item = None

            if await coordinator.async_remove_item(inventory_id, name, barcode=barcode):
                if item and resolved_name:
                    await self.todo_manager.check_and_remove_item(
                        resolved_name, cast(InventoryItem, item)
                    )

                await self._save_and_log_success(
                    coordinator, inventory_id, "Removed item", display_name
                )
            else:
                self._log_item_not_found("Remove item", display_name, inventory_id)

        except Exception as exc:
            _LOGGER.error(
                "Failed to remove item %s from inventory %s: %s",
                display_name,
                inventory_id,
                exc,
            )

    async def async_update_item(self, call: ServiceCall) -> None:
        data = cast(UpdateItemServiceData, call.data)
        inventory_id = data["inventory_id"]
        old_name = data["old_name"]
        new_name = data["name"]
        barcode = data.get("barcode")

        coordinator = self._require_coordinator(inventory_id)
        if coordinator is None:
            return

        existing_item = await coordinator.async_get_item(inventory_id, old_name)
        if not existing_item:
            self._log_item_not_found("Update item", old_name, inventory_id)
            return

        update_data = self._extract_update_fields(data)

        try:
            updated = await coordinator.async_update_item(
                inventory_id,
                old_name,
                new_name,
                barcode=barcode,
                **update_data,
            )
            if not updated:
                self._log_operation_failed("Update item", old_name, inventory_id)
                return

            updated_item = await coordinator.async_get_item(inventory_id, new_name)
            if updated_item:
                await self._handle_todo_auto_add(new_name, cast(InventoryItem, updated_item))

            await self._save_and_log_success(
                coordinator,
                inventory_id,
                f"Updated item: {old_name} -> {new_name}",
                new_name,
            )

        except HomeAssistantError:
            raise
        except Exception as exc:
            _LOGGER.error(
                "Failed to update item %s in inventory %s: %s",
                old_name,
                inventory_id,
                exc,
            )

    # ---------------------------------------------------------------------
    # Query helpers
    # ---------------------------------------------------------------------

    async def async_get_items(self, call: ServiceCall) -> JsonObjectType:
        """Return full list of items for an inventory."""
        data = cast(GetItemsServiceData, call.data)

        if data.get("inventory_id"):
            inventory_id = data["inventory_id"]
        elif data.get("inventory_name"):
            inventory_name = data["inventory_name"]
            matching_entry = next(
                (
                    entry
                    for entry in self.hass.config_entries.async_entries(DOMAIN)
                    if entry.data.get("name", "").lower() == inventory_name.lower()
                ),
                None,
            )
            if not matching_entry:
                raise ValueError(f"Inventory with name '{inventory_name}' not found")
            inventory_id = matching_entry.entry_id
        else:
            raise ValueError("Either 'inventory_id' or 'inventory_name' must be provided")

        coordinator = self._require_coordinator(inventory_id)
        if coordinator:
            items_list: list[dict[str, Any]] = await coordinator.async_list_items(inventory_id)
        else:
            repo = get_repository(self.hass)
            if repo is None:
                raise ValueError(
                    f"No coordinator or repository available for inventory '{inventory_id}'"
                )
            items_list = await repo.list_items_with_details(inventory_id)

        items_list.sort(key=lambda item: cast(str, item.get("name", "")).lower())
        return cast(JsonObjectType, {"items": cast(list[JsonValueType], items_list)})

    async def async_get_items_from_all_inventories(self, call: ServiceCall) -> JsonObjectType:
        """Return full list of items grouped by inventory."""
        _ = cast(GetAllItemsServiceData, call.data)

        repo = get_repository(self.hass)
        if repo is None:
            return cast(JsonObjectType, {"inventories": []})

        inventories_data: list[JsonObjectType] = []
        inventories = await repo.list_inventories()

        coordinators = get_coordinators(self.hass)

        for inventory in inventories:
            inventory_id = cast(str, inventory["id"])
            coordinator = coordinators.get(inventory_id)

            if coordinator:
                items_list = await coordinator.async_list_items(inventory_id)
            else:
                items_list = await repo.list_items_with_details(inventory_id)

            items_list.sort(key=lambda item: cast(str, item.get("name", "")).lower())

            inventories_data.append(
                cast(
                    JsonObjectType,
                    {
                        "inventory_id": inventory_id,
                        "inventory_name": inventory.get("name", inventory_id),
                        "description": inventory.get("description", ""),
                        "items": cast(list[JsonValueType], items_list),
                    },
                )
            )

        inventories_data.sort(key=lambda inv: cast(str, inv.get("inventory_name", "")).lower())
        return cast(JsonObjectType, {"inventories": cast(list[JsonValueType], inventories_data)})
