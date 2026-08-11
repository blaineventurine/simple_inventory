"""Todo list management for Simple Inventory."""

import logging
from typing import Any, cast

from homeassistant.components.todo import TodoListEntityFeature
from homeassistant.core import HomeAssistant

from .const import (
    DEFAULT_AUTO_ADD_TO_LIST_QUANTITY,
    EVENT_ITEM_ADDED_TO_LIST,
    EVENT_ITEM_REMOVED_FROM_LIST,
    FIELD_AUTO_ADD_ENABLED,
    FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED,
    FIELD_AUTO_ADD_TO_LIST_QUANTITY,
    FIELD_DESCRIPTION,
    FIELD_DESIRED_QUANTITY,
    FIELD_QUANTITY,
    FIELD_TODO_LIST,
    FIELD_TODO_QUANTITY_PLACEMENT,
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
        auto_add_enabled = bool(item_data.get(FIELD_AUTO_ADD_ENABLED, False))
        todo_list = item_data.get(FIELD_TODO_LIST)

        if not (auto_add_enabled and todo_list):
            return False

        if require_quantity_check:
            quantity = float(item_data.get(FIELD_QUANTITY, 0))
            auto_add_quantity = float(
                item_data.get(FIELD_AUTO_ADD_TO_LIST_QUANTITY, DEFAULT_AUTO_ADD_TO_LIST_QUANTITY)
            )
            return quantity <= auto_add_quantity

        return True

    def _calculate_quantity_needed(
        self, quantity: float, auto_add_quantity: float, desired_quantity: float = 0
    ) -> float:
        """Calculate quantity needed for todo list item.

        When desired_quantity is set, use it directly as the display amount.
        Otherwise fall back to the legacy formula.
        """
        if desired_quantity > 0:
            return desired_quantity
        return auto_add_quantity - quantity + 1

    def _build_todo_item_name(self, item_name: str, quantity_needed: float) -> str:
        """Build todo item name with quantity."""
        return f"{item_name} (x{quantity_needed:g})"

    def _supports_description(self, todo_list_entity: str) -> bool:
        if todo_list_entity == "todo.shopping_list":
            return False

        state = self.hass.states.get(todo_list_entity)
        if not state:
            return True

        supported = int(state.attributes.get("supported_features", 0))
        return bool(supported & TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM)

    def _resolve_item_description(self, item_data: InventoryItem) -> str:
        description = str(item_data.get(FIELD_DESCRIPTION, "") or "").strip()

        # If auto-append flag exists on the item, the coordinator will already supply
        # the normalized description (including inventory ID when enabled).
        if item_data.get(FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED):
            return description

        return description

    def _build_description_with_quantity(
        self, description: str | None, quantity_needed: float
    ) -> str:
        """Append quantity indicator to description text."""
        qty_str = f"(x{quantity_needed:g})"
        if description:
            return f"{description} {qty_str}"
        return qty_str

    def _resolve_placement(self, item_data: InventoryItem, todo_list: str) -> str:
        """Resolve the effective placement, falling back if needed."""
        placement = item_data.get(FIELD_TODO_QUANTITY_PLACEMENT, "name")
        if placement == "description" and not self._supports_description(todo_list):
            return "name"
        return placement

    async def _add_todo_item(
        self, todo_list: str, item_name: str, description: str | None = None
    ) -> None:
        """Add a new item to the todo list."""
        service_data: dict[str, Any] = {
            "item": item_name,
            "entity_id": todo_list,
        }

        if description is not None:
            service_data["description"] = description

        await self.hass.services.async_call("todo", "add_item", service_data, blocking=True)

    async def _update_todo_item(
        self,
        todo_list: str,
        item: dict[str, Any],
        new_name: str,
        description: str | None = None,
    ) -> None:
        """Update a todo item with a new name (and description if supported)."""
        service_data: dict[str, Any] = {
            "item": self._build_item_params(item),
            "rename": new_name,
            "entity_id": todo_list,
        }
        if description is not None:
            service_data["description"] = description

        await self.hass.services.async_call("todo", "update_item", service_data, blocking=True)

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
        if not self._should_process_auto_add(item_data, require_quantity_check=True):
            return False

        quantity = float(item_data.get(FIELD_QUANTITY, 0))
        auto_add_quantity = float(
            item_data.get(FIELD_AUTO_ADD_TO_LIST_QUANTITY, DEFAULT_AUTO_ADD_TO_LIST_QUANTITY)
        )
        desired_quantity = float(item_data.get(FIELD_DESIRED_QUANTITY, 0))
        todo_list = item_data.get(FIELD_TODO_LIST)

        if not todo_list:
            return False

        placement = self._resolve_placement(item_data, todo_list)
        supports_description = self._supports_description(todo_list)
        base_description = (
            self._resolve_item_description(item_data) if supports_description else None
        )

        try:
            matching_item = await self._find_matching_incomplete_item(todo_list, item_name)

            # Fixed quantity mode: don't add if already at/above desired,
            # and don't update if already on the list
            if desired_quantity > 0:
                if quantity >= desired_quantity:
                    return False
                if matching_item:
                    return True

            quantity_needed = self._calculate_quantity_needed(
                quantity, auto_add_quantity, desired_quantity
            )

            if quantity_needed <= 0:
                return False

            if placement == "name":
                new_name = self._build_todo_item_name(item_name, quantity_needed)
                description = base_description
            elif placement == "description":
                new_name = item_name
                description = self._build_description_with_quantity(
                    base_description, quantity_needed
                )
            else:  # "none"
                new_name = item_name
                description = base_description

            if matching_item:
                await self._update_todo_item(todo_list, matching_item, new_name, description)
                self.hass.bus.async_fire(
                    EVENT_ITEM_ADDED_TO_LIST,
                    {
                        "item_name": item_name,
                        "inventory_id": item_data.get("inventory_id", ""),
                        "quantity": quantity,
                        "todo_list": todo_list,
                        "quantity_needed": quantity_needed,
                    },
                )
            else:
                await self._add_todo_item(todo_list, new_name, description)
                self.hass.bus.async_fire(
                    EVENT_ITEM_ADDED_TO_LIST,
                    {
                        "item_name": item_name,
                        "inventory_id": item_data.get("inventory_id", ""),
                        "quantity": quantity,
                        "todo_list": todo_list,
                        "quantity_needed": quantity_needed,
                    },
                )

            return True

        except Exception as e:
            _LOGGER.error("Failed to add %s to todo list: %s", item_name, e)
            return False

    async def check_and_remove_item(self, item_name: str, item_data: InventoryItem) -> bool:
        if not self._should_process_auto_add(item_data, require_quantity_check=False):
            return False

        quantity = float(item_data.get(FIELD_QUANTITY, 0))
        auto_add_quantity = float(
            item_data.get(FIELD_AUTO_ADD_TO_LIST_QUANTITY, DEFAULT_AUTO_ADD_TO_LIST_QUANTITY)
        )
        desired_quantity = float(item_data.get(FIELD_DESIRED_QUANTITY, 0))
        todo_list = item_data.get(FIELD_TODO_LIST)

        if not todo_list:
            return False

        placement = self._resolve_placement(item_data, todo_list)
        supports_description = self._supports_description(todo_list)
        base_description = (
            self._resolve_item_description(item_data) if supports_description else None
        )

        try:
            matching_item = await self._find_matching_incomplete_item(todo_list, item_name)

            if not matching_item:
                return False

            # Fixed quantity mode: remove when desired quantity is reached,
            # otherwise leave unchanged
            if desired_quantity > 0:
                if quantity >= desired_quantity:
                    await self._remove_todo_item(todo_list, matching_item)
                    self.hass.bus.async_fire(
                        EVENT_ITEM_REMOVED_FROM_LIST,
                        {
                            "item_name": item_name,
                            "inventory_id": item_data.get("inventory_id", ""),
                            "quantity": quantity,
                            "todo_list": todo_list,
                        },
                    )
                    return True
                return False

            quantity_needed = self._calculate_quantity_needed(
                quantity, auto_add_quantity, desired_quantity
            )

            if quantity_needed <= 0:
                await self._remove_todo_item(todo_list, matching_item)
                self.hass.bus.async_fire(
                    EVENT_ITEM_REMOVED_FROM_LIST,
                    {
                        "item_name": item_name,
                        "inventory_id": item_data.get("inventory_id", ""),
                        "quantity": quantity,
                        "todo_list": todo_list,
                    },
                )
            else:
                if placement == "name":
                    new_name = self._build_todo_item_name(item_name, quantity_needed)
                    description = base_description
                elif placement == "description":
                    new_name = item_name
                    description = self._build_description_with_quantity(
                        base_description, quantity_needed
                    )
                else:  # "none"
                    new_name = item_name
                    description = base_description
                await self._update_todo_item(todo_list, matching_item, new_name, description)
                self.hass.bus.async_fire(
                    EVENT_ITEM_ADDED_TO_LIST,
                    {
                        "item_name": item_name,
                        "inventory_id": item_data.get("inventory_id", ""),
                        "quantity": quantity,
                        "todo_list": todo_list,
                        "quantity_needed": quantity_needed,
                    },
                )

            return True

        except Exception as e:
            _LOGGER.error("Failed to remove %s from todo list: %s", item_name, e)
            return False
