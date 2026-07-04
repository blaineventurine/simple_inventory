"""Tests for fuzzy inventory/item name resolution."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import ServiceValidationError

from custom_components.simple_inventory.services.resolvers import (
    resolve_inventory_id,
    resolve_item_name,
)


def _entry(entry_id: str, name: str, entry_type: str = "inventory") -> MagicMock:
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.data = {"name": name, "entry_type": entry_type}
    return entry


def _hass_with_entries(entries: list[MagicMock]) -> MagicMock:
    hass = MagicMock()
    hass.config_entries.async_entries = MagicMock(return_value=entries)
    return hass


@pytest.mark.asyncio
async def test_resolve_inventory_id_passthrough_when_id_given() -> None:
    """A direct inventory_id bypasses lookup entirely (existing callers unaffected)."""
    hass = MagicMock()
    hass.config_entries.async_entries = MagicMock(
        side_effect=AssertionError("should not be called")
    )

    result = await resolve_inventory_id(hass, "inv_123", None)

    assert result == "inv_123"


@pytest.mark.asyncio
async def test_resolve_inventory_id_exact_match() -> None:
    hass = _hass_with_entries([_entry("inv_1", "Kitchen"), _entry("inv_2", "Chest Freezer")])

    result = await resolve_inventory_id(hass, None, "Chest Freezer")

    assert result == "inv_2"


@pytest.mark.asyncio
async def test_resolve_inventory_id_exact_match_case_insensitive() -> None:
    hass = _hass_with_entries([_entry("inv_1", "Disposable Goods")])

    result = await resolve_inventory_id(hass, None, "disposable goods")

    assert result == "inv_1"


@pytest.mark.asyncio
async def test_resolve_inventory_id_substring_match() -> None:
    hass = _hass_with_entries([_entry("inv_1", "Chest Freezer"), _entry("inv_2", "Dry Storage")])

    result = await resolve_inventory_id(hass, None, "freezer")

    assert result == "inv_1"


@pytest.mark.asyncio
async def test_resolve_inventory_id_fuzzy_match_typo() -> None:
    hass = _hass_with_entries([_entry("inv_1", "Disposable Goods")])

    result = await resolve_inventory_id(hass, None, "disposible goods")

    assert result == "inv_1"


@pytest.mark.asyncio
async def test_resolve_inventory_id_ambiguous_substring_raises() -> None:
    hass = _hass_with_entries([_entry("inv_1", "Garage Freezer"), _entry("inv_2", "Chest Freezer")])

    with pytest.raises(ServiceValidationError, match="multiple inventories"):
        await resolve_inventory_id(hass, None, "freezer")


@pytest.mark.asyncio
async def test_resolve_inventory_id_no_match_raises() -> None:
    hass = _hass_with_entries([_entry("inv_1", "Kitchen")])

    with pytest.raises(ServiceValidationError, match="No inventory"):
        await resolve_inventory_id(hass, None, "nonexistent zzz")


@pytest.mark.asyncio
async def test_resolve_inventory_id_excludes_global_entry() -> None:
    hass = _hass_with_entries(
        [_entry("global_1", "Simple Inventory", entry_type="global"), _entry("inv_1", "Kitchen")]
    )

    with pytest.raises(ServiceValidationError, match="No inventory"):
        await resolve_inventory_id(hass, None, "Simple Inventory")


@pytest.mark.asyncio
async def test_resolve_inventory_id_missing_both_raises() -> None:
    hass = MagicMock()

    with pytest.raises(ServiceValidationError, match="inventory_id.*inventory_name"):
        await resolve_inventory_id(hass, None, None)


@pytest.mark.asyncio
async def test_resolve_item_name_exact_case_insensitive() -> None:
    coordinator = MagicMock()
    coordinator.async_list_items = AsyncMock(return_value=[{"name": "Aluminum Foil"}])

    result = await resolve_item_name(coordinator, "inv_1", "aluminum foil")

    assert result == "Aluminum Foil"


@pytest.mark.asyncio
async def test_resolve_item_name_substring_match() -> None:
    coordinator = MagicMock()
    coordinator.async_list_items = AsyncMock(
        return_value=[{"name": "Heavy Duty Aluminum Foil"}, {"name": "Paper Towels"}]
    )

    result = await resolve_item_name(coordinator, "inv_1", "aluminum foil")

    assert result == "Heavy Duty Aluminum Foil"


@pytest.mark.asyncio
async def test_resolve_item_name_no_match_raises() -> None:
    coordinator = MagicMock()
    coordinator.async_list_items = AsyncMock(return_value=[{"name": "Paper Towels"}])

    with pytest.raises(ServiceValidationError, match="No item"):
        await resolve_item_name(coordinator, "inv_1", "aluminum foil")


@pytest.mark.asyncio
async def test_resolve_item_name_missing_name_raises() -> None:
    coordinator = MagicMock()

    with pytest.raises(ServiceValidationError, match="name"):
        await resolve_item_name(coordinator, "inv_1", "")


@pytest.mark.asyncio
async def test_resolve_inventory_id_whitespace_only_query_raises() -> None:
    """A whitespace-only name must never silently resolve to the only inventory."""
    hass = _hass_with_entries([_entry("inv_1", "Kitchen")])

    with pytest.raises(ServiceValidationError, match="No inventory"):
        await resolve_inventory_id(hass, None, "   ")


@pytest.mark.asyncio
async def test_resolve_inventory_id_exact_tier_wins_over_substring() -> None:
    """An exact match must win even when a substring match also exists."""
    hass = _hass_with_entries([_entry("inv_1", "Freezer"), _entry("inv_2", "Chest Freezer")])

    result = await resolve_inventory_id(hass, None, "Freezer")

    assert result == "inv_1"


@pytest.mark.asyncio
async def test_resolve_inventory_id_reverse_substring_match() -> None:
    """The configured name can be a substring of a longer spoken phrase."""
    hass = _hass_with_entries([_entry("inv_1", "Kitchen")])

    result = await resolve_inventory_id(hass, None, "kitchen inventory")

    assert result == "inv_1"


@pytest.mark.asyncio
async def test_resolve_item_name_ambiguous_raises() -> None:
    coordinator = MagicMock()
    coordinator.async_list_items = AsyncMock(
        return_value=[{"name": "Garage Freezer Bag"}, {"name": "Chest Freezer Bag"}]
    )

    with pytest.raises(ServiceValidationError, match="multiple items"):
        await resolve_item_name(coordinator, "inv_1", "freezer bag")


@pytest.mark.asyncio
async def test_resolve_item_name_exact_alias_match() -> None:
    coordinator = MagicMock()
    coordinator.async_list_items = AsyncMock(
        return_value=[{"name": "Oatmeal", "aliases": ["oats", "hot cereal"]}]
    )

    result = await resolve_item_name(coordinator, "inv_1", "oats")

    assert result == "Oatmeal"


@pytest.mark.asyncio
async def test_resolve_item_name_alias_case_insensitive() -> None:
    coordinator = MagicMock()
    coordinator.async_list_items = AsyncMock(
        return_value=[{"name": "Oatmeal", "aliases": ["Steel-Cut Oats"]}]
    )

    result = await resolve_item_name(coordinator, "inv_1", "steel-cut oats")

    assert result == "Oatmeal"


@pytest.mark.asyncio
async def test_resolve_item_name_alias_substring_match() -> None:
    coordinator = MagicMock()
    coordinator.async_list_items = AsyncMock(
        return_value=[
            {"name": "Oatmeal", "aliases": ["hot cereal"]},
            {"name": "Paper Towels", "aliases": []},
        ]
    )

    result = await resolve_item_name(coordinator, "inv_1", "cereal")

    assert result == "Oatmeal"


@pytest.mark.asyncio
async def test_resolve_item_name_alias_fuzzy_match_typo() -> None:
    coordinator = MagicMock()
    coordinator.async_list_items = AsyncMock(
        return_value=[{"name": "Oatmeal", "aliases": ["oats"]}]
    )

    result = await resolve_item_name(coordinator, "inv_1", "otas")

    assert result == "Oatmeal"


@pytest.mark.asyncio
async def test_resolve_item_name_alias_missing_field_does_not_crash() -> None:
    """Items from a coordinator/mock that predates aliases (no 'aliases' key at
    all) must still resolve by name -- resolve_item_name must not assume the
    key is always present."""
    coordinator = MagicMock()
    coordinator.async_list_items = AsyncMock(return_value=[{"name": "Paper Towels"}])

    result = await resolve_item_name(coordinator, "inv_1", "paper towels")

    assert result == "Paper Towels"


@pytest.mark.asyncio
async def test_resolve_item_name_alias_colliding_with_other_item_name_raises() -> None:
    """An alias that happens to match a different item's real name is a genuine
    ambiguity -- must raise, never silently pick one (the DB only prevents two
    items sharing the same alias, not an alias colliding with a real name)."""
    coordinator = MagicMock()
    coordinator.async_list_items = AsyncMock(
        return_value=[
            {"name": "Oatmeal", "aliases": ["Oats"]},
            {"name": "Oats", "aliases": []},
        ]
    )

    with pytest.raises(ServiceValidationError, match="multiple items"):
        await resolve_item_name(coordinator, "inv_1", "Oats")


@pytest.mark.asyncio
async def test_resolve_item_name_own_alias_and_name_both_matching_is_not_ambiguous() -> None:
    """A single item whose alias shares a substring with its own name (e.g. an
    alias that's a shortened form of the name) must resolve cleanly -- matching
    both the name and the alias at the same tier is not ambiguity, since both
    candidates point at the same item."""
    coordinator = MagicMock()
    coordinator.async_list_items = AsyncMock(
        return_value=[{"name": "Chicken Broth", "aliases": ["Broth Cube"]}]
    )

    result = await resolve_item_name(coordinator, "inv_1", "broth")

    assert result == "Chicken Broth"
