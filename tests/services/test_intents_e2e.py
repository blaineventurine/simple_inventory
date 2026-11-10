"""Find-item and low-stock list intents, through the real service stack."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent, translation

from custom_components.simple_inventory.const import DOMAIN
from custom_components.simple_inventory.intents import (
    INTENT_FIND_ITEM,
    INTENT_LOW_STOCK_COUNT_QUERY,
    INTENT_LOW_STOCK_LIST_QUERY,
    async_register_intents,
)

from ..harness import TodoStack

LOW = {"auto_add_enabled": True, "auto_add_to_list_quantity": 2, "todo_list": "todo.grocery"}


@pytest.fixture
async def stack(todo_stack: TodoStack, enable_custom_integrations: None) -> TodoStack:
    """Kitchen and Garage, with batteries in both and butter in the kitchen."""
    hass = todo_stack.hass
    await translation.async_load_integrations(hass, {DOMAIN})
    hass.config.components.add(DOMAIN)
    async_register_intents(hass)
    await todo_stack.add_inventory("garage", "Garage")
    items: list[tuple[str, dict[str, Any]]] = [
        (
            "kitchen",
            {"name": "AA batteries", "quantity": 8, "aliases": "double A", "location": "Drawer"},
        ),
        ("garage", {"name": "AA batteries", "quantity": 4, "location": "Shelf B"}),
        ("garage", {"name": "9V batteries", "quantity": 2}),
        ("kitchen", {"name": "Butter", "quantity": 1, **LOW}),
        ("kitchen", {"name": "Peanut butter", "quantity": 3}),
        ("kitchen", {"name": "Toy car", "quantity": 1, "description": "batteries included"}),
        ("garage", {"name": "Oil", "quantity": 0, **LOW}),
    ]
    for inventory_id, item in items:
        await todo_stack.call("add_item", inventory_id=inventory_id, **item)
    return todo_stack


async def _speech(hass: HomeAssistant, intent_type: str, language: str = "en", **slots: str) -> str:
    response = await intent.async_handle(
        hass,
        "test",
        intent_type,
        {name: {"value": value} for name, value in slots.items()},
        language=language,
    )
    return str(response.speech["plain"]["speech"])


async def test_find_lists_every_name_match_across_inventories(stack: TodoStack) -> None:
    speech = await _speech(stack.hass, INTENT_FIND_ITEM, item="batteries")
    assert speech == (
        "I found 3 matches for batteries: 2 9V batteries in Garage, "
        "4 AA batteries in Garage (Shelf B), and 8 AA batteries in Kitchen (Drawer)."
    )


async def test_find_prefers_an_exact_name(stack: TodoStack) -> None:
    speech = await _speech(stack.hass, INTENT_FIND_ITEM, item="butter")
    assert speech == "Kitchen has 1 Butter."


async def test_find_matches_an_alias(stack: TodoStack) -> None:
    speech = await _speech(stack.hass, INTENT_FIND_ITEM, item="double a")
    assert speech == "Kitchen has 8 AA batteries, in Drawer."


async def test_find_scoped_to_a_named_inventory(stack: TodoStack) -> None:
    speech = await _speech(stack.hass, INTENT_FIND_ITEM, item="batteries", inventory="garage")
    assert speech == (
        "I found 2 matches for batteries: "
        "2 9V batteries in Garage and 4 AA batteries in Garage (Shelf B)."
    )


async def test_find_splits_a_named_inventory_off_the_item(stack: TodoStack) -> None:
    """hassil puts "do we have milk in the kitchen" all in the item: split it back off."""
    hass = stack.hass
    assert (
        await _speech(hass, INTENT_FIND_ITEM, item="AA batteries in the garage")
        == "Garage has 4 AA batteries, in Shelf B."
    )
    assert (
        await _speech(hass, INTENT_FIND_ITEM, item="unicorns in Kitchen")
        == "I couldn't find unicorns in Kitchen."
    )
    # Only an exact inventory name splits: "in the box" stays part of the item.
    assert (
        await _speech(hass, INTENT_FIND_ITEM, item="toy car in the box")
        == "I couldn't find toy car in the box in any inventory."
    )


async def test_find_reports_nothing_found(stack: TodoStack) -> None:
    assert (
        await _speech(stack.hass, INTENT_FIND_ITEM, item="unicorns")
        == "I couldn't find unicorns in any inventory."
    )
    assert (
        await _speech(stack.hass, INTENT_FIND_ITEM, item="unicorns", inventory="kitchen")
        == "I couldn't find unicorns in Kitchen."
    )


async def test_low_stock_list_names_items(stack: TodoStack) -> None:
    speech = await _speech(stack.hass, INTENT_LOW_STOCK_LIST_QUERY)
    assert speech == "2 items are low on stock: Butter and Oil (out of stock)."


async def test_low_stock_list_scoped(stack: TodoStack) -> None:
    speech = await _speech(stack.hass, INTENT_LOW_STOCK_LIST_QUERY, inventory="kitchen")
    assert speech == "1 item is low on stock in Kitchen: Butter."


async def test_low_stock_count_mentions_out_of_stock(stack: TodoStack) -> None:
    speech = await _speech(stack.hass, INTENT_LOW_STOCK_COUNT_QUERY)
    assert speech == "2 items are low on stock, 1 of them out of stock."


async def test_answers_in_the_conversation_language(stack: TodoStack) -> None:
    hass = stack.hass
    assert (
        await _speech(hass, INTENT_LOW_STOCK_LIST_QUERY, "es")
        == "2 artículos tienen poco stock: Butter y Oil (agotado)."
    )
    assert (
        await _speech(hass, INTENT_LOW_STOCK_COUNT_QUERY, "sl")
        == "2 artikla imata nizko zalogo, od tega 1 brez zaloge."
    )
    assert await _speech(hass, INTENT_FIND_ITEM, "fr", item="batteries") == (
        "J'ai trouvé 3 résultats pour batteries : 2 9V batteries dans Garage, "
        "4 AA batteries dans Garage (Shelf B) et 8 AA batteries dans Kitchen (Drawer)."
    )


async def test_regional_and_unsupported_languages(stack: TodoStack) -> None:
    hass = stack.hass
    assert (
        await _speech(hass, INTENT_LOW_STOCK_LIST_QUERY, "fr-CA", inventory="kitchen")
        == "1 article est presque épuisé dans Kitchen: Butter."
    )
    assert (
        await _speech(hass, INTENT_LOW_STOCK_LIST_QUERY, "de", inventory="kitchen")
        == "1 item is low on stock in Kitchen: Butter."
    )


async def test_refusals_from_service_errors_are_translated(stack: TodoStack) -> None:
    speech = await _speech(stack.hass, INTENT_FIND_ITEM, "es", item="butter", inventory="attic")
    assert speech == 'No se encontró ningún inventario llamado "attic"'


async def test_find_splits_the_inventory_off_in_other_languages(stack: TodoStack) -> None:
    speech = await _speech(stack.hass, INTENT_FIND_ITEM, "es", item="AA batteries en el Garage")
    assert speech == "Garage tiene 4 AA batteries, en Shelf B."
