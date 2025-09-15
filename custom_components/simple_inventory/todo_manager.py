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
        status = item.get("status")

        if isinstance(status, str):
            return status.lower() in ["completed", "complete", "done"]

        return (
            item.get("completed", False)
            or item.get("done", False)
            or item.get("state") == "completed"
        )

    def _filter_incomplete_items(self, all_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Filter and convert items to incomplete TodoItems."""
        return [item for item in all_items if not self._is_item_completed(item)]

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

    async def check_and_add_item(self, item_name: str, item_data: InventoryItem) -> bool:
        """Check if item should be added to todo list and add it."""
        _LOGGER.debug(f"Checking if {item_name} is valid...")
        if not (
            item_data.get(FIELD_AUTO_ADD_ENABLED, False)
            and item_data[FIELD_QUANTITY]
            <= item_data.get(
                FIELD_AUTO_ADD_TO_LIST_QUANTITY,
                DEFAULT_AUTO_ADD_TO_LIST_QUANTITY,
            )
            and item_data.get(FIELD_TODO_LIST)
        ):
            return False
        _LOGGER.debug(f"Checking if {item_name} should be added to todo list...")
        try:
            todo_list_entity = item_data["todo_list"]
            incomplete_items = await self._get_incomplete_items(todo_list_entity)

            for item in incomplete_items:
                item_summary = item.get("summary", "")
                _LOGGER.debug(f"Checking item: {item_summary} against {item_name}")
                if item_summary.lower().strip() == item_name.lower().strip():

                    _LOGGER.info(
                        f"Item {
                            item_name} already exists in todo list (incomplete)"
                    )
                    return False

            await self.hass.services.async_call(
                "todo",
                "add_item",
                {"item": item_name, "entity_id": todo_list_entity},
            )

            _LOGGER.info(f"Added {item_name} to {todo_list_entity}")
            return True

        except Exception as e:
            _LOGGER.error(f"Failed to add {item_name} to todo list: {e}")
            return False
