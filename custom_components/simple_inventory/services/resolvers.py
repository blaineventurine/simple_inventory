"""Fuzzy inventory/item name resolution for voice and AI assistant callers."""

from __future__ import annotations

import difflib
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from ..const import DOMAIN

if TYPE_CHECKING:
    from ..coordinator import SimpleInventoryCoordinator

_FUZZY_CUTOFF = 0.6


def _tiered_match(query: str, options: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Tiered match `query` against `options` = [(display_name, value), ...]."""
    query_lower = query.strip().lower()
    if not query_lower:
        return []

    def lowered(name: str) -> str:
        return name.strip().lower()

    exact = [(name, value) for name, value in options if lowered(name) == query_lower]
    if exact:
        return exact

    substring = [
        (name, value)
        for name, value in options
        if query_lower in lowered(name) or lowered(name) in query_lower
    ]
    if substring:
        return substring

    names_lower = [lowered(name) for name, _ in options]
    close = set(difflib.get_close_matches(query_lower, names_lower, n=5, cutoff=_FUZZY_CUTOFF))
    return [(name, value) for name, value in options if lowered(name) in close]


def _resolve_one(query: str, options: list[tuple[str, str]], singular: str, plural: str) -> str:
    matches = _tiered_match(query, options)
    if not matches:
        raise ServiceValidationError(f"No {singular} named '{query}' found")
    if len({value for _, value in matches}) > 1:
        names = ", ".join(sorted({display for display, _ in matches}))
        raise ServiceValidationError(
            f"'{query}' matches multiple {plural}: {names}. Please be more specific."
        )
    return matches[0][1]


async def resolve_inventory_id(
    hass: HomeAssistant, inventory_id: str | None, inventory_name: str | None
) -> str:
    """Return a concrete inventory_id from either a direct id or a fuzzy name."""
    if inventory_id:
        return inventory_id

    if not inventory_name:
        raise ServiceValidationError("Either 'inventory_id' or 'inventory_name' is required")

    options = [
        (str(entry.data.get("name", "")), entry.entry_id)
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.data.get("entry_type") != "global" and entry.data.get("name")
    ]
    return _resolve_one(inventory_name, options, "inventory", "inventories")


def inventory_display_name(hass: HomeAssistant, inventory_id: str) -> str:
    """Best-effort human-readable inventory name for error messages."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.entry_id == inventory_id:
            name = entry.data.get("name")
            if name:
                return str(name)
    return inventory_id


async def resolve_item_name(
    coordinator: "SimpleInventoryCoordinator", inventory_id: str, name: str
) -> str:
    """Return the canonical stored item name for an existing item."""
    if not name:
        raise ServiceValidationError("An item name is required")

    items = await coordinator.async_list_items(inventory_id)
    options: list[tuple[str, str]] = []
    for item in items:
        item_name = str(item.get("name", ""))
        if not item_name:
            continue
        options.append((item_name, item_name))
        for alias in item.get("aliases", []):
            options.append((str(alias), item_name))
    return _resolve_one(name, options, "item", "items")
