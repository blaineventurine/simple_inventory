"""Fuzzy inventory/item name resolution for voice and AI assistant callers."""

from __future__ import annotations

import difflib
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from ..const import CONF_NAME, DOMAIN, FIELD_ALIASES, FIELD_NAME, match_key
from ..entries import inventory_display_name, inventory_entries

if TYPE_CHECKING:
    from ..coordinator import SimpleInventoryCoordinator

_FUZZY_CUTOFF = 0.6


def _tiered_match(
    query: str, options: list[tuple[str, str]], fuzzy: bool = True
) -> list[tuple[str, str]]:
    """Tiered match `query` against `options` = [(display_name, value), ...].

    Exact (case-insensitive) matches win; with ``fuzzy`` the substring and
    difflib tiers are tried next.
    """
    query_lower = match_key(query)
    if not query_lower:
        return []

    exact = [(name, value) for name, value in options if match_key(name) == query_lower]
    if exact or not fuzzy:
        return exact

    substring = [
        (name, value)
        for name, value in options
        if query_lower in match_key(name) or match_key(name) in query_lower
    ]
    if substring:
        return substring

    names_lower = [match_key(name) for name, _ in options]
    close = set(difflib.get_close_matches(query_lower, names_lower, n=5, cutoff=_FUZZY_CUTOFF))
    return [(name, value) for name, value in options if match_key(name) in close]


def _unique_match(
    query: str, options: list[tuple[str, str]], fuzzy: bool = True
) -> tuple[str | None, str]:
    """Return ``(value, "")`` for a unique match, else ``(None, ambiguous_names)``.

    ``ambiguous_names`` is empty when nothing matched at all.
    """
    matches = _tiered_match(query, options, fuzzy)
    if len({value for _, value in matches}) == 1:
        return matches[0][1], ""
    return None, ", ".join(sorted({display for display, _ in matches}))


def match_names(query: str, names: list[str]) -> list[str]:
    """Stored ``names`` matching ``query`` with the item-name tolerance, sorted.

    An exact (case-insensitive) match is the only result when there is one.
    """
    return sorted({name for name, _ in _tiered_match(query, [(name, name) for name in names])})


def _inventory_options(hass: HomeAssistant) -> list[tuple[str, str]]:
    """(name, entry_id) of every named, non-global inventory."""
    return [(str(entry.data[CONF_NAME]), entry.entry_id) for entry in inventory_entries(hass)]


def exact_inventory_id(hass: HomeAssistant, inventory_name: str) -> str | None:
    """Entry id of the inventory named exactly (case-insensitively) ``inventory_name``."""
    resolved, _ = _unique_match(inventory_name, _inventory_options(hass), fuzzy=False)
    return resolved


def inventory_not_loaded_error(
    hass: HomeAssistant, inventory_id: str, inventory: str | None = None
) -> ServiceValidationError:
    """The ``inventory_not_loaded`` error for ``inventory_id``.

    ``inventory`` overrides the displayed name (default: the entry's display name).
    """
    if inventory is None:
        inventory = inventory_display_name(hass, inventory_id)
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="inventory_not_loaded",
        translation_placeholders={"inventory": inventory},
    )


async def resolve_inventory_id(
    hass: HomeAssistant, inventory_id: str | None, inventory_name: str | None
) -> str:
    """Return a concrete inventory_id from either a direct id or a fuzzy name."""
    if inventory_id:
        return inventory_id

    if not inventory_name:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="inventory_identifier_required"
        )

    resolved, ambiguous = _unique_match(inventory_name, _inventory_options(hass))
    if resolved is not None:
        return resolved
    if ambiguous:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="ambiguous_inventory",
            translation_placeholders={"name": inventory_name, "matches": ambiguous},
        )
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="inventory_not_found",
        translation_placeholders={"name": inventory_name},
    )


async def resolve_item_name(
    coordinator: "SimpleInventoryCoordinator",
    inventory_id: str,
    name: str,
    *,
    fuzzy: bool = True,
) -> str:
    """Return the canonical stored item name for an existing item.

    ``fuzzy=False`` accepts only an exact (case-insensitive) name or alias; use it
    for destructive operations so a stale name never hits a similarly named item.
    """
    inventory = inventory_display_name(coordinator.hass, inventory_id)
    if not name:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="empty_item_name",
            translation_placeholders={"inventory": inventory},
        )

    items = await coordinator.async_list_items(inventory_id)
    options: list[tuple[str, str]] = []
    for item in items:
        item_name = str(item.get(FIELD_NAME, ""))
        if not item_name:
            continue
        options.append((item_name, item_name))
        for alias in item.get(FIELD_ALIASES, []):
            options.append((str(alias), item_name))
    # Name the distinct items: matching strings collapse to one entry when an alias equals
    # another item's name ("Oats"), which hid that two items matched.
    names = sorted({item_name for _, item_name in _tiered_match(name, options, fuzzy)})
    if len(names) == 1:
        return names[0]
    if names:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="ambiguous_item",
            translation_placeholders={
                "name": name,
                "inventory": inventory,
                "matches": ", ".join(names),
            },
        )
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="item_not_found",
        translation_placeholders={"name": name, "inventory": inventory},
    )
