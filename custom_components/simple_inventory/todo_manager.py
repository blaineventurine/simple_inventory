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
        try:
            response = await self.hass.services.async_call(
                "todo",
                "get_items",
                {"entity_id": todo_list_entity},
                blocking=True,
                return_response=True,
            )

            if response and todo_list_entity in response:
                entity_data = response[todo_list_entity]
                if isinstance(entity_data, dict):
                    all_items = entity_data.get("items", [])
                    if isinstance(all_items, list):
                        return self._filter_incomplete_items(cast(list[dict[str, Any]], all_items))

        except Exception as service_error:
            _LOGGER.warning(f"Could not use get_items service: {service_error}")
            todo_state = self.hass.states.get(todo_list_entity)
            if todo_state and todo_state.attributes:
                all_items = todo_state.attributes.get("items", [])
                if isinstance(all_items, list):
                    return self._filter_incomplete_items(cast(list[dict[str, Any]], all_items))

        return []

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
        item_uid = str(item.get("uid"))

        if item_uid:
            _LOGGER.debug(f"Using UID: {item_uid}")
            return item_uid

        summary = str(item.get("summary", ""))
        _LOGGER.debug(f"Using summary: {summary}")
        return summary

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

    async def check_and_add_item(self, item_name: str, item_data: InventoryItem) -> bool:
        """Check if item should be added to todo list and add it."""
        auto_add_enabled = item_data.get(FIELD_AUTO_ADD_ENABLED, False)
        quantity = item_data[FIELD_QUANTITY]
        auto_add_quantity = item_data.get(
            FIELD_AUTO_ADD_TO_LIST_QUANTITY,
            DEFAULT_AUTO_ADD_TO_LIST_QUANTITY,
        )
        todo_list = item_data.get(FIELD_TODO_LIST)

        if not (auto_add_enabled and quantity <= auto_add_quantity and todo_list):
            return False

        try:
            matching_item = await self._find_matching_incomplete_item(todo_list, item_name)
            quantity_needed = str(auto_add_quantity - quantity + 1)
            new_name = f"{item_name} (x{quantity_needed})"

            if matching_item:
                await self._update_todo_item(todo_list, matching_item, new_name)
            else:
                await self.hass.services.async_call(
                    "todo",
                    "add_item",
                    {"item": new_name, "entity_id": todo_list},
                    blocking=True,
                )
            return True

        except Exception as e:
            _LOGGER.error(f"Failed to add {item_name} to todo list: {e}")
            return False

    async def check_and_remove_item(self, item_name: str, item_data: InventoryItem) -> bool:
        """Check if item should be removed from todo list and remove it."""
        auto_add_enabled = item_data.get(FIELD_AUTO_ADD_ENABLED, False)
        quantity = item_data[FIELD_QUANTITY]
        auto_add_quantity = item_data.get(
            FIELD_AUTO_ADD_TO_LIST_QUANTITY,
            DEFAULT_AUTO_ADD_TO_LIST_QUANTITY,
        )
        todo_list = item_data.get(FIELD_TODO_LIST)

        if not (auto_add_enabled and todo_list):
            return False

        try:
            matching_item = await self._find_matching_incomplete_item(todo_list, item_name)

            if not matching_item:
                return False

            quantity_needed = auto_add_quantity - quantity + 1

            if quantity_needed <= 0:
                await self.hass.services.async_call(
                    "todo",
                    "remove_item",
                    {
                        "item": self._build_item_params(matching_item),
                        "entity_id": todo_list,
                    },
                    blocking=True,
                )
            else:
                new_name = f"{item_name} (x{str(quantity_needed)})"
                await self._update_todo_item(todo_list, matching_item, new_name)

            return True

        except Exception as e:
            _LOGGER.error(f"Failed to remove {item_name} from todo list: {e}")
            return False
