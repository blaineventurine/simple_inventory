"""Todo list management for Simple Inventory."""

import logging
from typing import Any, cast

from homeassistant.core import HomeAssistant

from .const import (
    DEFAULT_AUTO_ADD_TO_LIST_QUANTITY,
    FIELD_AUTO_ADD_ENABLED,
    FIELD_AUTO_ADD_TO_LIST_QUANTITY,
    FIELD_QUANTITY,
    FIELD_TODO_LIST,
)
from .types import InventoryItem

_LOGGER = logging.getLogger(__name__)


class TodoManager:
    """Manage todo list integration."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the todo manager."""
        self.hass = hass

    def _is_item_completed(self, item: dict[str, Any]) -> bool:
        """Check if a todo item is completed."""
        status = item.get("status", "")
        if not status:
            return False
        return str(status).lower() == "completed"

    def _filter_incomplete_items(self, all_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Filter and convert items to incomplete TodoItems."""
        return [item for item in all_items if not self._is_item_completed(item)]

    def _name_matches(self, item_summary: str, item_name: str) -> bool:
        """Check if todo item name matches inventory item name."""
        item_summary_clean = item_summary.lower().strip()
        item_name_clean = item_name.lower().strip()
        if item_summary_clean == item_name_clean:
            return True
        if item_summary_clean.startswith(f"{item_name_clean} (x"):
            return True
        return False

    async def _get_incomplete_items(self, todo_list_entity: str) -> list[dict[str, Any]]:
        """Get incomplete items from a todo list."""
        items = await self._get_items_from_service(todo_list_entity)
        if items is not None:
            return items

        items = self._get_items_from_state(todo_list_entity)
        return items if items is not None else []

    async def _get_items_from_service(self, todo_list_entity: str) -> list[dict[str, Any]] | None:
        """Get items from todo list using service call."""
        try:
            response = await self.hass.services.async_call(
                "todo",
                "get_items",
                {"entity_id": todo_list_entity},
                blocking=True,
                return_response=True,
            )

            return self._parse_service_response(response, todo_list_entity)

        except Exception as service_error:
            _LOGGER.warning("Could not use get_items service: %s", service_error)
            return None

    def _parse_service_response(
        self, response: Any, todo_list_entity: str
    ) -> list[dict[str, Any]] | None:
        """Parse service response to extract items."""
        if not response or todo_list_entity not in response:
            return None

        entity_data = response[todo_list_entity]
        if not isinstance(entity_data, dict):
            return None

        all_items = entity_data.get("items", [])
        if not isinstance(all_items, list):
            return None

        return self._filter_incomplete_items(cast(list[dict[str, Any]], all_items))

    def _get_items_from_state(self, todo_list_entity: str) -> list[dict[str, Any]] | None:
        """Get items from todo list state attributes."""
        todo_state = self.hass.states.get(todo_list_entity)
        if not todo_state or not todo_state.attributes:
            return None

        all_items = todo_state.attributes.get("items", [])
        if not isinstance(all_items, list):
            return None

        return self._filter_incomplete_items(cast(list[dict[str, Any]], all_items))

    async def _find_matching_incomplete_item(
        self, todo_list: str, item_name: str
    ) -> dict[str, Any] | None:
        """Find a matching incomplete item in the todo list."""
        incomplete_items = await self._get_incomplete_items(todo_list)

        for item in incomplete_items:
            if self._name_matches(item.get("summary", ""), item_name):
                return item
        return None

    def _build_item_params(self, item: dict[str, Any]) -> str:
        """Build the item parameter for service calls, preferring UID."""
        item_uid = item.get("uid")

        if item_uid is not None:
            _LOGGER.debug("Using UID: %s", item_uid)
            return str(item_uid)

        summary = str(item.get("summary", ""))
        _LOGGER.debug("Using summary: %s", summary)
        return summary

    def _should_process_auto_add(
        self,
        item_data: InventoryItem,
        require_quantity_check: bool = True,
    ) -> bool:
        """Check if auto-add should be processed for an item."""
        auto_add_enabled = item_data.get(FIELD_AUTO_ADD_ENABLED, False)
        todo_list = item_data.get(FIELD_TODO_LIST)

        if not (auto_add_enabled and todo_list):
            return False

        if require_quantity_check:
            quantity = item_data[FIELD_QUANTITY]
            auto_add_quantity = item_data.get(
                FIELD_AUTO_ADD_TO_LIST_QUANTITY,
                DEFAULT_AUTO_ADD_TO_LIST_QUANTITY,
            )
            return quantity <= auto_add_quantity

        return True

    def _calculate_quantity_needed(self, quantity: int, auto_add_quantity: int) -> int:
        """Calculate quantity needed for todo list item."""
        return auto_add_quantity - quantity + 1

    def _build_todo_item_name(self, item_name: str, quantity_needed: int) -> str:
        """Build todo item name with quantity."""
        return f"{item_name} (x{quantity_needed})"

    async def _add_todo_item(self, todo_list: str, item_name: str) -> None:
        """Add a new item to the todo list."""
        await self.hass.services.async_call(
            "todo",
            "add_item",
            {"item": item_name, "entity_id": todo_list},
            blocking=True,
        )

    async def _update_todo_item(self, todo_list: str, item: dict[str, Any], new_name: str) -> None:
        """Update a todo item with a new name."""
        await self.hass.services.async_call(
            "todo",
            "update_item",
            {
                "item": self._build_item_params(item),
                "rename": new_name,
                "entity_id": todo_list,
            },
            blocking=True,
        )

    async def _remove_todo_item(self, todo_list: str, item: dict[str, Any]) -> None:
        """Remove an item from the todo list."""
        await self.hass.services.async_call(
            "todo",
            "remove_item",
            {
                "item": self._build_item_params(item),
                "entity_id": todo_list,
            },
            blocking=True,
        )

    async def check_and_add_item(self, item_name: str, item_data: InventoryItem) -> bool:
        """Check if item should be added to todo list and add it."""
        if not self._should_process_auto_add(item_data, require_quantity_check=True):
            return False

        quantity = item_data[FIELD_QUANTITY]
        auto_add_quantity = item_data.get(
            FIELD_AUTO_ADD_TO_LIST_QUANTITY,
            DEFAULT_AUTO_ADD_TO_LIST_QUANTITY,
        )
        todo_list = item_data.get(FIELD_TODO_LIST)

        if not todo_list:
            return False

        try:
            matching_item = await self._find_matching_incomplete_item(todo_list, item_name)
            quantity_needed = self._calculate_quantity_needed(quantity, auto_add_quantity)
            new_name = self._build_todo_item_name(item_name, quantity_needed)

            if matching_item:
                await self._update_todo_item(todo_list, matching_item, new_name)
            else:
                await self._add_todo_item(todo_list, new_name)

            return True

        except Exception as e:
            _LOGGER.error("Failed to add %s to todo list: %s", item_name, e)
            return False

    async def check_and_remove_item(self, item_name: str, item_data: InventoryItem) -> bool:
        """Check if item should be removed from todo list and remove it."""
        if not self._should_process_auto_add(item_data, require_quantity_check=False):
            return False

        quantity = item_data[FIELD_QUANTITY]
        auto_add_quantity = item_data.get(
            FIELD_AUTO_ADD_TO_LIST_QUANTITY,
            DEFAULT_AUTO_ADD_TO_LIST_QUANTITY,
        )
        todo_list = item_data.get(FIELD_TODO_LIST)

        if not todo_list:
            return False

        try:
            matching_item = await self._find_matching_incomplete_item(todo_list, item_name)

            if not matching_item:
                return False

            quantity_needed = self._calculate_quantity_needed(quantity, auto_add_quantity)

            if quantity_needed <= 0:
                await self._remove_todo_item(todo_list, matching_item)
            else:
                new_name = self._build_todo_item_name(item_name, quantity_needed)
                await self._update_todo_item(todo_list, matching_item, new_name)

            return True

        except Exception as e:
            _LOGGER.error("Failed to remove %s from todo list: %s", item_name, e)
            return False
