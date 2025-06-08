"""Todo list management for Simple Inventory."""
import logging
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class TodoManager:
    """Manage todo list integration."""

    def __init__(self, hass: HomeAssistant):
        """Initialize the todo manager."""
        self.hass = hass

    def _is_item_completed(self, item):
        """Check if a todo item is completed using various possible field names."""
        return (
            item.get("status") == "completed" or
            item.get("status") == "done" or
            item.get("completed", False) or
            item.get("done", False) or
            item.get("state") == "completed"
        )

    async def _get_incomplete_items(self, todo_list_entity: str):
        """Get incomplete items from a todo list."""
        try:
            # Try to get items using the service call
            response = await self.hass.services.async_call(
                "todo", "get_items",
                {"entity_id": todo_list_entity},
                blocking=True,
                return_response=True
            )

            if todo_list_entity in response:
                all_items = response[todo_list_entity].get("items", [])
                # Filter out completed items
                incomplete_items = [
                    item for item in all_items
                    if not self._is_item_completed(item)
                ]
                return incomplete_items

        except Exception as service_error:
            _LOGGER.warning(
                f"Could not use get_items service: {service_error}")
            # Fall back to state method
            todo_state = self.hass.states.get(todo_list_entity)
            if todo_state:
                all_items = todo_state.attributes.get("items", [])
                incomplete_items = [
                    item for item in all_items
                    if not self._is_item_completed(item)
                ]
                return incomplete_items

        return []

    async def check_and_add_item(self, item_name: str, item_data: dict):
        """Check if item should be added to todo list and add it."""
        if not (item_data.get("auto_add_enabled", False) and
                item_data["quantity"] <= item_data.get("threshold", 0) and
                item_data.get("todo_list")):
            return False

        try:
            todo_list_entity = item_data["todo_list"]

            # Get incomplete items from the todo list
            incomplete_items = await self._get_incomplete_items(todo_list_entity)

            # Check for duplicates among incomplete items only
            for item in incomplete_items:
                if item.get("summary", "").lower().strip() == item_name.lower().strip():
                    _LOGGER.info(
                        f"Item {item_name} already exists in todo list (incomplete)")
                    return False

            # Add the item (no incomplete duplicate found)
            await self.hass.services.async_call(
                "todo", "add_item",
                {
                    "item": item_name,
                    "entity_id": todo_list_entity
                }
            )

            _LOGGER.info(f"Added {item_name} to {todo_list_entity}")
            return True

        except Exception as e:
            _LOGGER.error(f"Failed to add {item_name} to todo list: {e}")
            return False
