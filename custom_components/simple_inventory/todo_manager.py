"""Todo list management for Simple Inventory."""

import logging
from collections.abc import Mapping
from typing import Any, cast

from homeassistant.components.todo import TodoListEntityFeature
from homeassistant.core import HomeAssistant

from .const import (
    DEFAULT_AUTO_ADD_TO_LIST_QUANTITY,
    DOMAIN,
    EVENT_ITEM_ADDED_TO_LIST,
    EVENT_ITEM_REMOVED_FROM_LIST,
    FIELD_AUTO_ADD_ENABLED,
    FIELD_AUTO_ADD_TO_LIST_QUANTITY,
    FIELD_DESCRIPTION,
    FIELD_DESIRED_QUANTITY,
    FIELD_NAME,
    FIELD_QUANTITY,
    FIELD_TODO_LIST,
    FIELD_TODO_QUANTITY_PLACEMENT,
    is_below_threshold,
    match_key,
)
from .types import InventoryItem

_LOGGER = logging.getLogger(__name__)

# Entries carry the amount to buy as "(x<n>)", after the name or in the description.
_MARK_OPEN = "(x"


def quantity_mark(quantity_needed: float) -> str:
    """The ``(x<n>)`` marker for an entry's summary or description."""
    return f"{_MARK_OPEN}{quantity_needed:g})"


def restock_state(item: Mapping[str, Any]) -> tuple[float, bool]:
    """Return (amount the todo entry shows, whether the item counts as restocked).

    With a desired quantity the entry shows that target and the item is restocked once it
    is reached. Otherwise it shows the legacy shortfall ``threshold - quantity + 1`` and the
    item is restocked once that is no longer positive. The shown amount intentionally
    differs from ``const.compute_quantity_needed`` (the statistics' delta).
    """
    quantity = float(item.get(FIELD_QUANTITY, 0))
    desired = float(item.get(FIELD_DESIRED_QUANTITY, 0))
    if desired > 0:
        return desired, quantity >= desired
    threshold = float(item.get(FIELD_AUTO_ADD_TO_LIST_QUANTITY, DEFAULT_AUTO_ADD_TO_LIST_QUANTITY))
    needed = threshold - quantity + 1
    return needed, needed <= 0


def supports_description(hass: HomeAssistant, todo_list_entity: str) -> bool:
    """Whether the todo entity accepts item descriptions."""
    state = hass.states.get(todo_list_entity)
    if not state:
        return False

    supported = int(state.attributes.get("supported_features", 0))
    return bool(supported & TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM)


def _is_managed(item_data: Mapping[str, Any]) -> bool:
    """Auto-add is enabled and a todo list is configured: the entry is ours to manage."""
    return bool(item_data.get(FIELD_AUTO_ADD_ENABLED, False) and item_data.get(FIELD_TODO_LIST))


def _entry_orphaned(previous: Mapping[str, Any], item_name: str, item: Mapping[str, Any]) -> bool:
    """An edit renamed the item, changed its list or disabled auto-add."""
    return (
        match_key(str(previous.get(FIELD_NAME, ""))) != match_key(item_name)
        or previous.get(FIELD_TODO_LIST) != item.get(FIELD_TODO_LIST)
        or not item.get(FIELD_AUTO_ADD_ENABLED, False)
    )


class _TodoListUnreadable(Exception):
    """``todo.get_items`` failed for a list, so its entries are unknown."""


def _skip_unreadable(todo_list: str, item_name: str, *, retried: bool) -> bool:
    """Log the one warning for a sync skipped because *todo_list* could not be read.

    A skipped add or refresh is redone by the item's next change. A skipped removal (the
    item was removed, renamed, moved to another list or had auto-add disabled) is not:
    nothing looks at the old entry again.
    """
    if retried:
        _LOGGER.warning(
            "Todo list %s could not be read; not syncing %s (retried on the item's next change)",
            todo_list,
            item_name,
        )
    else:
        _LOGGER.warning(
            "Todo list %s could not be read; the entry for %s was not removed and will not be"
            " retried (remove it from the list by hand)",
            todo_list,
            item_name,
        )
    return False


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
        item_summary_clean = match_key(item_summary)
        item_name_clean = match_key(item_name)
        if item_summary_clean == item_name_clean:
            return True
        if item_summary_clean.startswith(f"{item_name_clean} {_MARK_OPEN}"):
            return True
        return False

    async def _get_incomplete_items(self, todo_list_entity: str) -> list[dict[str, Any]] | None:
        """Incomplete items of a todo list; ``None`` when the list cannot be read.

        ``None`` is not an empty list: a sync based on it would add a duplicate entry (or
        miss the one to remove), so callers skip the sync instead.
        """
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
            # The skipped sync logs the one warning; this only adds the cause.
            _LOGGER.debug("todo.get_items failed for %s: %s", todo_list_entity, service_error)
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

    def _foreign_inventory_tags(self, inventory_id: str) -> list[str]:
        """Description tags (``(<entry_id>)``) identifying entries of other inventories."""
        if not inventory_id:
            return []
        return [
            f"({entry.entry_id})"
            for entry in self.hass.config_entries.async_entries(DOMAIN)
            if entry.entry_id != inventory_id
        ]

    async def _find_matching_incomplete_item(
        self, todo_list: str, item_name: str, inventory_id: str = ""
    ) -> dict[str, Any] | None:
        """Find the incomplete entry on `todo_list` that belongs to this item.

        Entries tagged with this inventory's ID win; entries tagged with another
        inventory's ID (``auto_add_id_to_description_enabled``) never match, so
        same-named items from different inventories keep separate entries.
        """
        incomplete_items = await self._get_incomplete_items(todo_list)
        if incomplete_items is None:
            raise _TodoListUnreadable(todo_list)
        own_tag = f"({inventory_id})" if inventory_id else ""
        foreign_tags = self._foreign_inventory_tags(inventory_id)

        fallback: dict[str, Any] | None = None
        for item in incomplete_items:
            if not self._name_matches(str(item.get("summary", "")), item_name):
                continue
            description = str(item.get("description") or "")
            if own_tag and own_tag in description:
                return item
            if any(tag in description for tag in foreign_tags):
                continue
            if fallback is None:
                fallback = item
        return fallback

    def _build_item_params(self, item: dict[str, Any]) -> str:
        """Build the item parameter for service calls, preferring UID."""
        item_uid = item.get("uid")

        if item_uid is not None:
            _LOGGER.debug("Using UID: %s", item_uid)
            return str(item_uid)

        summary = str(item.get("summary", ""))
        _LOGGER.debug("Using summary: %s", summary)
        return summary

    def _build_todo_item_name(self, item_name: str, quantity_needed: float) -> str:
        """Build todo item name with quantity."""
        return f"{item_name} {quantity_mark(quantity_needed)}"

    def _resolve_item_description(self, item_data: InventoryItem) -> str:
        """Stored item description (already carries the inventory-ID tag when enabled)."""
        return str(item_data.get(FIELD_DESCRIPTION, "") or "").strip()

    def _build_description_with_quantity(
        self, description: str | None, quantity_needed: float
    ) -> str:
        """Append quantity indicator to description text."""
        qty_str = quantity_mark(quantity_needed)
        if description:
            return f"{description} {qty_str}"
        return qty_str

    def _resolve_placement(self, item_data: InventoryItem, todo_list: str) -> str:
        """Resolve the effective placement, falling back if needed."""
        placement = item_data.get(FIELD_TODO_QUANTITY_PLACEMENT, "name")
        if placement == "description" and not supports_description(self.hass, todo_list):
            return "name"
        return placement

    def _build_entry(
        self,
        item_name: str,
        item_data: InventoryItem,
        todo_list: str,
        quantity_needed: float,
    ) -> tuple[str, str | None]:
        """Return (summary, description) for the entry.

        The description is None (left untouched on the todo list) unless the
        placement is "description" or the item has a description of its own, so a
        refresh never wipes notes the user typed on the todo entry.
        """
        placement = self._resolve_placement(item_data, todo_list)
        base_description = (
            self._resolve_item_description(item_data)
            if supports_description(self.hass, todo_list)
            else ""
        )

        if placement == "description":
            return item_name, self._build_description_with_quantity(
                base_description, quantity_needed
            )

        summary = (
            self._build_todo_item_name(item_name, quantity_needed)
            if placement == "name"
            else item_name
        )
        return summary, base_description or None

    @staticmethod
    def _entry_is_current(entry: dict[str, Any], summary: str, description: str | None) -> bool:
        if str(entry.get("summary", "")) != summary:
            return False
        return description is None or str(entry.get("description") or "") == description

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

    async def _sync_entry(
        self,
        todo_list: str,
        matching_item: dict[str, Any] | None,
        item_name: str,
        item_data: InventoryItem,
        quantity_needed: float,
    ) -> None:
        """Create or refresh the entry; no call or event when it is already current."""
        summary, description = self._build_entry(item_name, item_data, todo_list, quantity_needed)
        if matching_item:
            if self._entry_is_current(matching_item, summary, description):
                return
            await self._update_todo_item(todo_list, matching_item, summary, description)
        else:
            await self._add_todo_item(todo_list, summary, description)

        self.hass.bus.async_fire(
            EVENT_ITEM_ADDED_TO_LIST,
            {
                "item_name": item_name,
                "inventory_id": item_data.get("inventory_id", ""),
                FIELD_QUANTITY: float(item_data.get(FIELD_QUANTITY, 0)),
                FIELD_TODO_LIST: todo_list,
                "quantity_needed": quantity_needed,
            },
        )

    async def _remove_entry(
        self,
        todo_list: str,
        matching_item: dict[str, Any],
        item_name: str,
        item_data: InventoryItem,
    ) -> None:
        await self._remove_todo_item(todo_list, matching_item)
        self.hass.bus.async_fire(
            EVENT_ITEM_REMOVED_FROM_LIST,
            {
                "item_name": item_name,
                "inventory_id": item_data.get("inventory_id", ""),
                FIELD_QUANTITY: float(item_data.get(FIELD_QUANTITY, 0)),
                FIELD_TODO_LIST: todo_list,
            },
        )

    async def async_sync(
        self,
        item_name: str,
        item_data: InventoryItem,
        *,
        previous: InventoryItem | None = None,
    ) -> bool:
        """Bring the item's todo entry in line with its current state.

        A restocked item's entry is removed. Otherwise, at or below its threshold the item
        is put on its list (or its entry refreshed); above it, an existing entry is
        refreshed. ``previous`` is the item before an edit: when the edit orphaned its old
        entry (rename, other list, auto-add disabled), that entry is removed first.
        """
        if previous is not None and _entry_orphaned(previous, item_name, item_data):
            await self.remove_item_entry(str(previous.get(FIELD_NAME, "")), previous)
        _, restocked = restock_state(item_data)
        if restocked or not is_below_threshold(item_data):
            return await self._remove_or_refresh(item_name, item_data)
        return await self._add_or_refresh(item_name, item_data)

    async def _add_or_refresh(self, item_name: str, item_data: InventoryItem) -> bool:
        """Put the item on its todo list (or refresh its entry) when below threshold."""
        if not (_is_managed(item_data) and is_below_threshold(item_data)):
            return False

        todo_list = str(item_data.get(FIELD_TODO_LIST))
        if self.hass.states.get(todo_list) is None:
            _LOGGER.warning(
                "Todo list %s does not exist; not adding %s to it", todo_list, item_name
            )
            return False

        quantity_needed, restocked = restock_state(item_data)
        if restocked:
            return False

        try:
            matching_item = await self._find_matching_incomplete_item(
                todo_list, item_name, str(item_data.get("inventory_id", ""))
            )
            await self._sync_entry(todo_list, matching_item, item_name, item_data, quantity_needed)
            return True

        except _TodoListUnreadable:
            return _skip_unreadable(todo_list, item_name, retried=True)
        except Exception as e:
            _LOGGER.error("Failed to add %s to todo list: %s", item_name, e)
            return False

    async def _remove_or_refresh(self, item_name: str, item_data: InventoryItem) -> bool:
        """Remove the item's entry once restocked, otherwise refresh its quantity text."""
        if not _is_managed(item_data):
            return False

        todo_list = str(item_data.get(FIELD_TODO_LIST))
        quantity_needed, restocked = restock_state(item_data)

        try:
            matching_item = await self._find_matching_incomplete_item(
                todo_list, item_name, str(item_data.get("inventory_id", ""))
            )
            if not matching_item:
                return False

            if restocked:
                await self._remove_entry(todo_list, matching_item, item_name, item_data)
            else:
                await self._sync_entry(
                    todo_list, matching_item, item_name, item_data, quantity_needed
                )
            return True

        except _TodoListUnreadable:
            return _skip_unreadable(todo_list, item_name, retried=True)
        except Exception as e:
            _LOGGER.error("Failed to remove %s from todo list: %s", item_name, e)
            return False

    async def remove_item_entry(self, item_name: str, item_data: InventoryItem) -> bool:
        """Remove the item's entry regardless of quantity (item deleted, renamed, moved).

        Only entries this integration manages are touched: the item must have
        auto-add enabled and a todo list configured.
        """
        if not _is_managed(item_data):
            return False

        todo_list = str(item_data.get(FIELD_TODO_LIST))
        try:
            matching_item = await self._find_matching_incomplete_item(
                todo_list, item_name, str(item_data.get("inventory_id", ""))
            )
            if not matching_item:
                return False
            await self._remove_entry(todo_list, matching_item, item_name, item_data)
            return True

        except _TodoListUnreadable:
            return _skip_unreadable(todo_list, item_name, retried=False)
        except Exception as e:
            _LOGGER.error("Failed to remove %s from todo list: %s", item_name, e)
            return False
