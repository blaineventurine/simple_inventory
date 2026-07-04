"""Tests for Simple Inventory's native voice/AI intents."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol
from homeassistant.core import Context, HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import intent

from custom_components.simple_inventory.const import DOMAIN
from custom_components.simple_inventory.intents import (
    INTENT_ADD_ITEM,
    INTENT_EXPIRY_COUNT_QUERY,
    INTENT_EXPIRY_LIST_QUERY,
    INTENT_LOW_STOCK_COUNT_QUERY,
    INTENT_QUERY_ITEM,
    INTENT_REMOVE_ITEM,
    INTENT_SET_ITEM_QUANTITY,
    AddItemIntent,
    ExpiryCountIntent,
    ExpiryListIntent,
    LowStockCountIntent,
    QueryItemIntent,
    RemoveItemIntent,
    SetItemQuantityIntent,
    async_register_intents,
    async_unregister_intents,
)


@pytest.fixture
def registered_services(hass: HomeAssistant) -> dict[str, list[dict]]:
    """Register fake decrement/increment/get_items/update_item services and capture their calls."""
    calls: dict[str, list[dict]] = {
        "decrement_item": [],
        "increment_item": [],
        "get_items": [],
        "update_item": [],
    }

    async def _decrement(call: ServiceCall) -> None:
        calls["decrement_item"].append(dict(call.data))

    async def _increment(call: ServiceCall) -> None:
        calls["increment_item"].append(dict(call.data))

    async def _get_items(call: ServiceCall) -> dict:
        calls["get_items"].append(dict(call.data))
        return {"items": [{"name": "Aluminum Foil", "quantity": 3}]}

    async def _update_item(call: ServiceCall) -> None:
        calls["update_item"].append(dict(call.data))

    hass.services.async_register(DOMAIN, "decrement_item", _decrement)
    hass.services.async_register(DOMAIN, "increment_item", _increment)
    hass.services.async_register(
        DOMAIN, "get_items", _get_items, supports_response=SupportsResponse.OPTIONAL
    )
    hass.services.async_register(DOMAIN, "update_item", _update_item)
    return calls


@pytest.fixture
def inventory_with_coordinator(hass: HomeAssistant) -> Generator[MagicMock, None, None]:
    """Register a 'Disposable Goods' config entry + coordinator with one item.

    QueryItemIntent resolves inventory/item names via resolvers.py directly
    (not the get_items service), so it needs a config entry (for
    resolve_inventory_id) and a coordinator registered in hass.data (for
    resolve_item_name / async_get_item), mirroring the pattern already used
    by tests/services/test_inventory_service.py's *_by_inventory_name tests.
    """
    entry = MagicMock()
    entry.entry_id = "inv_1"
    entry.data = {"name": "Disposable Goods", "entry_type": "inventory"}

    coordinator = MagicMock()
    coordinator.async_list_items = AsyncMock(
        return_value=[{"name": "Aluminum Foil", "quantity": 3}]
    )

    async def _get_item(inventory_id: str, name: str) -> dict | None:
        if name == "Aluminum Foil":
            return {"name": "Aluminum Foil", "quantity": 3}
        return None

    coordinator.async_get_item = AsyncMock(side_effect=_get_item)

    hass.data.setdefault(DOMAIN, {})["coordinators"] = {"inv_1": coordinator}

    with patch.object(hass.config_entries, "async_entries", return_value=[entry]):
        yield coordinator


def _make_intent(hass: HomeAssistant, intent_type: str, slots: dict) -> intent.Intent:
    return intent.Intent(
        hass,
        platform="test",
        intent_type=intent_type,
        slots=slots,
        text_input="test input",
        context=Context(),
        language="en",
    )


@pytest.mark.asyncio
async def test_remove_item_intent_calls_decrement_with_default_quantity(
    hass: HomeAssistant, registered_services: dict[str, list[dict]]
) -> None:
    intent_obj = _make_intent(
        hass,
        INTENT_REMOVE_ITEM,
        {"item": {"value": "Aluminum Foil"}, "inventory": {"value": "Disposable Goods"}},
    )

    response = await RemoveItemIntent().async_handle(intent_obj)

    assert registered_services["decrement_item"] == [
        {"inventory_name": "Disposable Goods", "name": "Aluminum Foil", "amount": 1.0}
    ]
    speech = response.speech["plain"]["speech"]
    assert "Removed 1 Aluminum Foil from Disposable Goods" in speech
    assert "3 left" in speech


@pytest.mark.asyncio
async def test_remove_item_intent_explicit_quantity(
    hass: HomeAssistant, registered_services: dict[str, list[dict]]
) -> None:
    intent_obj = _make_intent(
        hass,
        INTENT_REMOVE_ITEM,
        {
            "item": {"value": "Aluminum Foil"},
            "inventory": {"value": "Disposable Goods"},
            "quantity": {"value": 2},
        },
    )

    await RemoveItemIntent().async_handle(intent_obj)

    assert registered_services["decrement_item"] == [
        {"inventory_name": "Disposable Goods", "name": "Aluminum Foil", "amount": 2.0}
    ]


@pytest.mark.asyncio
async def test_remove_item_intent_string_quantity_coerces(
    hass: HomeAssistant, registered_services: dict[str, list[dict]]
) -> None:
    """LLM tool calls commonly send numeric args as strings; must coerce cleanly."""
    intent_obj = _make_intent(
        hass,
        INTENT_REMOVE_ITEM,
        {
            "item": {"value": "Aluminum Foil"},
            "inventory": {"value": "Disposable Goods"},
            "quantity": {"value": "2"},
        },
    )

    await RemoveItemIntent().async_handle(intent_obj)

    assert registered_services["decrement_item"] == [
        {"inventory_name": "Disposable Goods", "name": "Aluminum Foil", "amount": 2.0}
    ]


@pytest.mark.asyncio
async def test_remove_item_intent_success_speech_survives_quantity_lookup_failure(
    hass: HomeAssistant,
) -> None:
    """A successful mutation must still report success even if the best-effort
    follow-up quantity lookup fails (e.g. get_items' exact-only name match
    misses a name that the fuzzy decrement resolver accepted)."""

    async def _decrement(call: ServiceCall) -> None:
        return None

    async def _get_items_fails(call: ServiceCall) -> dict:
        raise ValueError("Inventory with name 'Disposable Goods' not found")

    hass.services.async_register(DOMAIN, "decrement_item", _decrement)
    hass.services.async_register(
        DOMAIN, "get_items", _get_items_fails, supports_response=SupportsResponse.OPTIONAL
    )

    intent_obj = _make_intent(
        hass,
        INTENT_REMOVE_ITEM,
        {"item": {"value": "Aluminum Foil"}, "inventory": {"value": "Disposable Goods"}},
    )

    response = await RemoveItemIntent().async_handle(intent_obj)

    speech = response.speech["plain"]["speech"]
    assert speech == "Removed 1 Aluminum Foil from Disposable Goods."


def test_remove_item_intent_rejects_missing_item_slot() -> None:
    with pytest.raises(vol.Invalid):
        RemoveItemIntent().async_validate_slots({"inventory": {"value": "Disposable Goods"}})


def test_remove_item_intent_rejects_empty_item_slot() -> None:
    with pytest.raises(vol.Invalid):
        RemoveItemIntent().async_validate_slots(
            {"item": {"value": ""}, "inventory": {"value": "Disposable Goods"}}
        )


def test_remove_item_intent_rejects_negative_quantity() -> None:
    with pytest.raises(vol.Invalid):
        RemoveItemIntent().async_validate_slots(
            {
                "item": {"value": "Aluminum Foil"},
                "inventory": {"value": "Disposable Goods"},
                "quantity": {"value": -1},
            }
        )


@pytest.mark.asyncio
async def test_add_item_intent_calls_increment(
    hass: HomeAssistant, registered_services: dict[str, list[dict]]
) -> None:
    intent_obj = _make_intent(
        hass,
        INTENT_ADD_ITEM,
        {"item": {"value": "Aluminum Foil"}, "inventory": {"value": "Disposable Goods"}},
    )

    response = await AddItemIntent().async_handle(intent_obj)

    assert registered_services["increment_item"] == [
        {"inventory_name": "Disposable Goods", "name": "Aluminum Foil", "amount": 1.0}
    ]
    speech = response.speech["plain"]["speech"]
    assert "Added 1 Aluminum Foil to Disposable Goods" in speech
    assert "Now at 3" in speech


@pytest.mark.asyncio
async def test_query_item_intent_reports_quantity(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    intent_obj = _make_intent(
        hass,
        INTENT_QUERY_ITEM,
        {"item": {"value": "Aluminum Foil"}, "inventory": {"value": "Disposable Goods"}},
    )

    response = await QueryItemIntent().async_handle(intent_obj)

    speech = response.speech["plain"]["speech"]
    assert "Disposable Goods has 3 Aluminum Foil" in speech


@pytest.mark.asyncio
async def test_query_item_intent_fuzzy_inventory_and_item_names(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    """Query must accept the same non-exact spoken names remove/add accept."""
    intent_obj = _make_intent(
        hass,
        INTENT_QUERY_ITEM,
        {"item": {"value": "aluminum foil"}, "inventory": {"value": "disposable goods"}},
    )

    response = await QueryItemIntent().async_handle(intent_obj)

    speech = response.speech["plain"]["speech"]
    assert "has 3" in speech


@pytest.mark.asyncio
async def test_query_item_intent_item_not_present_raises_intent_handle_error(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    intent_obj = _make_intent(
        hass,
        INTENT_QUERY_ITEM,
        {"item": {"value": "Paper Towels"}, "inventory": {"value": "Disposable Goods"}},
    )

    with pytest.raises(intent.IntentHandleError, match="Paper Towels"):
        await QueryItemIntent().async_handle(intent_obj)


@pytest.mark.asyncio
async def test_query_item_intent_unknown_inventory_raises_intent_handle_error(
    hass: HomeAssistant,
) -> None:
    """An unresolvable inventory must produce clean intent-level speech, not a crash."""
    with patch.object(hass.config_entries, "async_entries", return_value=[]):
        intent_obj = _make_intent(
            hass,
            INTENT_QUERY_ITEM,
            {"item": {"value": "Aluminum Foil"}, "inventory": {"value": "Nonexistent Inventory"}},
        )

        with pytest.raises(intent.IntentHandleError, match="Nonexistent Inventory"):
            await QueryItemIntent().async_handle(intent_obj)


@pytest.mark.asyncio
async def test_remove_item_intent_service_error_becomes_intent_handle_error(
    hass: HomeAssistant,
) -> None:
    async def _decrement(call: ServiceCall) -> None:
        raise ServiceValidationError("No item named 'foo' found in inventory 'bar'")

    hass.services.async_register(DOMAIN, "decrement_item", _decrement)

    intent_obj = _make_intent(
        hass, INTENT_REMOVE_ITEM, {"item": {"value": "foo"}, "inventory": {"value": "bar"}}
    )

    with pytest.raises(intent.IntentHandleError, match="No item named 'foo'"):
        await RemoveItemIntent().async_handle(intent_obj)


def test_async_unregister_intents_removes_all_seven(hass: HomeAssistant) -> None:
    async_register_intents(hass)
    async_unregister_intents(hass)

    registered_types = {handler.intent_type for handler in intent.async_get(hass)}
    assert INTENT_REMOVE_ITEM not in registered_types
    assert INTENT_ADD_ITEM not in registered_types
    assert INTENT_QUERY_ITEM not in registered_types
    assert INTENT_EXPIRY_COUNT_QUERY not in registered_types
    assert INTENT_LOW_STOCK_COUNT_QUERY not in registered_types
    assert INTENT_EXPIRY_LIST_QUERY not in registered_types
    assert INTENT_SET_ITEM_QUANTITY not in registered_types


def test_intent_handlers_have_llm_facing_descriptions() -> None:
    """Descriptions double as the LLM tool description (via HA's AssistAPI); must be set."""
    for handler_cls in (
        RemoveItemIntent,
        AddItemIntent,
        QueryItemIntent,
        ExpiryCountIntent,
        LowStockCountIntent,
        ExpiryListIntent,
        SetItemQuantityIntent,
    ):
        assert handler_cls.description
        assert len(handler_cls.description) > 20


@pytest.mark.asyncio
async def test_remove_item_intent_fractional_remaining_speech(hass: HomeAssistant) -> None:
    """Fractional quantities must render without a spurious trailing zero (e.g. "0.5" not "0.50")."""

    async def _decrement(call: ServiceCall) -> None:
        return None

    async def _get_items(call: ServiceCall) -> dict:
        return {"items": [{"name": "Aluminum Foil", "quantity": 0.5}]}

    hass.services.async_register(DOMAIN, "decrement_item", _decrement)
    hass.services.async_register(
        DOMAIN, "get_items", _get_items, supports_response=SupportsResponse.OPTIONAL
    )

    intent_obj = _make_intent(
        hass,
        INTENT_REMOVE_ITEM,
        {
            "item": {"value": "Aluminum Foil"},
            "inventory": {"value": "Disposable Goods"},
            "quantity": {"value": 2.5},
        },
    )

    response = await RemoveItemIntent().async_handle(intent_obj)

    speech = response.speech["plain"]["speech"]
    assert speech == "Removed 2.5 Aluminum Foil from Disposable Goods. 0.5 left."


@pytest.mark.asyncio
async def test_remove_item_intent_quantity_lookup_item_missing_from_response(
    hass: HomeAssistant,
) -> None:
    """Trailer is omitted (not a crash) when the exact-match get_items response doesn't
    include the item name that the fuzzy decrement resolver accepted."""

    async def _decrement(call: ServiceCall) -> None:
        return None

    async def _get_items(call: ServiceCall) -> dict:
        return {"items": [{"name": "Something Else", "quantity": 5}]}

    hass.services.async_register(DOMAIN, "decrement_item", _decrement)
    hass.services.async_register(
        DOMAIN, "get_items", _get_items, supports_response=SupportsResponse.OPTIONAL
    )

    intent_obj = _make_intent(
        hass,
        INTENT_REMOVE_ITEM,
        {"item": {"value": "Aluminum Foil"}, "inventory": {"value": "Disposable Goods"}},
    )

    response = await RemoveItemIntent().async_handle(intent_obj)

    speech = response.speech["plain"]["speech"]
    assert speech == "Removed 1 Aluminum Foil from Disposable Goods."


@pytest.mark.asyncio
async def test_remove_item_intent_depleted_reports_none_left(hass: HomeAssistant) -> None:
    async def _decrement(call: ServiceCall) -> None:
        return None

    async def _get_items(call: ServiceCall) -> dict:
        return {"items": [{"name": "Aluminum Foil", "quantity": 0}]}

    hass.services.async_register(DOMAIN, "decrement_item", _decrement)
    hass.services.async_register(
        DOMAIN, "get_items", _get_items, supports_response=SupportsResponse.OPTIONAL
    )

    intent_obj = _make_intent(
        hass,
        INTENT_REMOVE_ITEM,
        {"item": {"value": "Aluminum Foil"}, "inventory": {"value": "Disposable Goods"}},
    )

    response = await RemoveItemIntent().async_handle(intent_obj)

    speech = response.speech["plain"]["speech"]
    assert speech == "Removed 1 Aluminum Foil from Disposable Goods. None left."


@pytest.mark.asyncio
async def test_add_item_intent_success_speech_survives_quantity_lookup_failure(
    hass: HomeAssistant,
) -> None:
    """A successful add must still report success even if the best-effort follow-up
    quantity lookup fails."""

    async def _increment(call: ServiceCall) -> None:
        return None

    async def _get_items_fails(call: ServiceCall) -> dict:
        raise ValueError("Inventory with name 'Disposable Goods' not found")

    hass.services.async_register(DOMAIN, "increment_item", _increment)
    hass.services.async_register(
        DOMAIN, "get_items", _get_items_fails, supports_response=SupportsResponse.OPTIONAL
    )

    intent_obj = _make_intent(
        hass,
        INTENT_ADD_ITEM,
        {"item": {"value": "Aluminum Foil"}, "inventory": {"value": "Disposable Goods"}},
    )

    response = await AddItemIntent().async_handle(intent_obj)

    speech = response.speech["plain"]["speech"]
    assert speech == "Added 1 Aluminum Foil to Disposable Goods."


@pytest.mark.asyncio
async def test_query_item_intent_resolved_inventory_without_loaded_coordinator(
    hass: HomeAssistant,
) -> None:
    """An inventory that resolves by name but has no loaded coordinator (e.g. mid-reload)
    must produce clean intent-level speech, not a crash."""
    entry = MagicMock()
    entry.entry_id = "inv_1"
    entry.data = {"name": "Disposable Goods", "entry_type": "inventory"}

    with patch.object(hass.config_entries, "async_entries", return_value=[entry]):
        intent_obj = _make_intent(
            hass,
            INTENT_QUERY_ITEM,
            {"item": {"value": "Aluminum Foil"}, "inventory": {"value": "Disposable Goods"}},
        )

        with pytest.raises(intent.IntentHandleError, match="not currently loaded"):
            await QueryItemIntent().async_handle(intent_obj)


@pytest.mark.asyncio
async def test_query_item_intent_item_disappears_before_get_reports_not_found(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    """If the item vanishes between the list-based resolve and the point lookup (e.g.
    concurrent removal), the query must report 'not found' rather than crash."""
    inventory_with_coordinator.async_get_item = AsyncMock(return_value=None)

    intent_obj = _make_intent(
        hass,
        INTENT_QUERY_ITEM,
        {"item": {"value": "Aluminum Foil"}, "inventory": {"value": "Disposable Goods"}},
    )

    response = await QueryItemIntent().async_handle(intent_obj)

    speech = response.speech["plain"]["speech"]
    assert speech == "I couldn't find Aluminum Foil in Disposable Goods."


@pytest.mark.asyncio
async def test_expiry_count_intent_counts_expired_items(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    inventory_with_coordinator.async_get_items_expiring_soon = AsyncMock(
        return_value=[
            {"name": "Old Milk", "days_until_expiry": -3},
            {"name": "Stale Bread", "days_until_expiry": -1},
            {"name": "Fresh Eggs", "days_until_expiry": 2},
        ]
    )
    intent_obj = _make_intent(
        hass,
        INTENT_EXPIRY_COUNT_QUERY,
        {"status": {"value": "expired"}, "inventory": {"value": "Disposable Goods"}},
    )
    response = await ExpiryCountIntent().async_handle(intent_obj)
    speech = response.speech["plain"]["speech"]
    assert speech == "2 items are expired in Disposable Goods."
    inventory_with_coordinator.async_get_items_expiring_soon.assert_awaited_once_with("inv_1")


@pytest.mark.asyncio
async def test_expiry_count_intent_counts_expiring_soon_items(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    inventory_with_coordinator.async_get_items_expiring_soon = AsyncMock(
        return_value=[
            {"name": "Old Milk", "days_until_expiry": -3},
            {"name": "Fresh Eggs", "days_until_expiry": 2},
            {"name": "Yogurt", "days_until_expiry": 0},
        ]
    )
    intent_obj = _make_intent(
        hass,
        INTENT_EXPIRY_COUNT_QUERY,
        {"status": {"value": "expiring_soon"}, "inventory": {"value": "Disposable Goods"}},
    )
    response = await ExpiryCountIntent().async_handle(intent_obj)
    speech = response.speech["plain"]["speech"]
    assert speech == "2 items are expiring soon in Disposable Goods."
    inventory_with_coordinator.async_get_items_expiring_soon.assert_awaited_once_with("inv_1")


@pytest.mark.asyncio
async def test_expiry_count_intent_singular_wording(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    inventory_with_coordinator.async_get_items_expiring_soon = AsyncMock(
        return_value=[{"name": "Old Milk", "days_until_expiry": -3}]
    )
    intent_obj = _make_intent(
        hass,
        INTENT_EXPIRY_COUNT_QUERY,
        {"status": {"value": "expired"}, "inventory": {"value": "Disposable Goods"}},
    )
    response = await ExpiryCountIntent().async_handle(intent_obj)
    speech = response.speech["plain"]["speech"]
    assert speech == "1 item is expired in Disposable Goods."
    inventory_with_coordinator.async_get_items_expiring_soon.assert_awaited_once_with("inv_1")


@pytest.mark.asyncio
async def test_expiry_count_intent_zero_count(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    inventory_with_coordinator.async_get_items_expiring_soon = AsyncMock(return_value=[])
    intent_obj = _make_intent(
        hass,
        INTENT_EXPIRY_COUNT_QUERY,
        {"status": {"value": "expired"}, "inventory": {"value": "Disposable Goods"}},
    )
    response = await ExpiryCountIntent().async_handle(intent_obj)
    speech = response.speech["plain"]["speech"]
    assert speech == "0 items are expired in Disposable Goods."
    inventory_with_coordinator.async_get_items_expiring_soon.assert_awaited_once_with("inv_1")


@pytest.mark.asyncio
async def test_expiry_count_intent_unscoped_omits_inventory_phrase(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    """No `inventory` slot at all -> queries across all inventories (inventory_id=None)
    and the response doesn't mention any inventory by name."""
    inventory_with_coordinator.async_get_items_expiring_soon = AsyncMock(
        return_value=[{"name": "Old Milk", "days_until_expiry": -3}]
    )
    intent_obj = _make_intent(hass, INTENT_EXPIRY_COUNT_QUERY, {"status": {"value": "expired"}})
    response = await ExpiryCountIntent().async_handle(intent_obj)
    speech = response.speech["plain"]["speech"]
    assert speech == "1 item is expired."
    inventory_with_coordinator.async_get_items_expiring_soon.assert_awaited_once_with(None)


@pytest.mark.asyncio
async def test_expiry_count_intent_unknown_inventory_raises_intent_handle_error(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    """A coordinator IS loaded (for a different inventory), but the named
    inventory doesn't resolve -- must fail via resolve_inventory_id, not the
    separate no-coordinators-at-all check."""
    intent_obj = _make_intent(
        hass,
        INTENT_EXPIRY_COUNT_QUERY,
        {"status": {"value": "expired"}, "inventory": {"value": "Nonexistent Place"}},
    )
    with pytest.raises(intent.IntentHandleError):
        await ExpiryCountIntent().async_handle(intent_obj)


@pytest.mark.asyncio
async def test_expiry_count_intent_no_coordinators_raises_intent_handle_error(
    hass: HomeAssistant,
) -> None:
    intent_obj = _make_intent(hass, INTENT_EXPIRY_COUNT_QUERY, {"status": {"value": "expired"}})
    with pytest.raises(intent.IntentHandleError):
        await ExpiryCountIntent().async_handle(intent_obj)


def test_async_register_intents_registers_all_seven(hass: HomeAssistant) -> None:
    async_register_intents(hass)
    try:
        registered_types = {i.intent_type for i in intent.async_get(hass)}
        assert INTENT_REMOVE_ITEM in registered_types
        assert INTENT_ADD_ITEM in registered_types
        assert INTENT_QUERY_ITEM in registered_types
        assert INTENT_EXPIRY_COUNT_QUERY in registered_types
        assert INTENT_LOW_STOCK_COUNT_QUERY in registered_types
        assert INTENT_EXPIRY_LIST_QUERY in registered_types
        assert INTENT_SET_ITEM_QUANTITY in registered_types
    finally:
        async_unregister_intents(hass)


@pytest.mark.asyncio
async def test_low_stock_count_intent_counts_items(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    inventory_with_coordinator.async_get_low_stock_items = AsyncMock(
        return_value=[
            {"name": "Bacon", "inventory_id": "inv_1"},
            {"name": "Rice", "inventory_id": "inv_1"},
        ]
    )
    intent_obj = _make_intent(
        hass, INTENT_LOW_STOCK_COUNT_QUERY, {"inventory": {"value": "Disposable Goods"}}
    )
    response = await LowStockCountIntent().async_handle(intent_obj)
    speech = response.speech["plain"]["speech"]
    assert speech == "2 items are low on stock in Disposable Goods."
    inventory_with_coordinator.async_get_low_stock_items.assert_awaited_once_with("inv_1")


@pytest.mark.asyncio
async def test_low_stock_count_intent_singular_wording(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    inventory_with_coordinator.async_get_low_stock_items = AsyncMock(
        return_value=[{"name": "Bacon", "inventory_id": "inv_1"}]
    )
    intent_obj = _make_intent(
        hass, INTENT_LOW_STOCK_COUNT_QUERY, {"inventory": {"value": "Disposable Goods"}}
    )
    response = await LowStockCountIntent().async_handle(intent_obj)
    speech = response.speech["plain"]["speech"]
    assert speech == "1 item is low on stock in Disposable Goods."


@pytest.mark.asyncio
async def test_low_stock_count_intent_zero_count(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    inventory_with_coordinator.async_get_low_stock_items = AsyncMock(return_value=[])
    intent_obj = _make_intent(
        hass, INTENT_LOW_STOCK_COUNT_QUERY, {"inventory": {"value": "Disposable Goods"}}
    )
    response = await LowStockCountIntent().async_handle(intent_obj)
    speech = response.speech["plain"]["speech"]
    assert speech == "0 items are low on stock in Disposable Goods."


@pytest.mark.asyncio
async def test_low_stock_count_intent_unscoped_omits_inventory_phrase(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    inventory_with_coordinator.async_get_low_stock_items = AsyncMock(
        return_value=[{"name": "Bacon", "inventory_id": "inv_1"}]
    )
    intent_obj = _make_intent(hass, INTENT_LOW_STOCK_COUNT_QUERY, {})
    response = await LowStockCountIntent().async_handle(intent_obj)
    speech = response.speech["plain"]["speech"]
    assert speech == "1 item is low on stock."
    inventory_with_coordinator.async_get_low_stock_items.assert_awaited_once_with(None)


@pytest.mark.asyncio
async def test_low_stock_count_intent_unknown_inventory_raises_intent_handle_error(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    intent_obj = _make_intent(
        hass, INTENT_LOW_STOCK_COUNT_QUERY, {"inventory": {"value": "Nonexistent Place"}}
    )
    with pytest.raises(intent.IntentHandleError):
        await LowStockCountIntent().async_handle(intent_obj)


@pytest.mark.asyncio
async def test_low_stock_count_intent_no_coordinators_raises_intent_handle_error(
    hass: HomeAssistant,
) -> None:
    intent_obj = _make_intent(hass, INTENT_LOW_STOCK_COUNT_QUERY, {})
    with pytest.raises(intent.IntentHandleError):
        await LowStockCountIntent().async_handle(intent_obj)


@pytest.mark.asyncio
async def test_expiry_list_intent_lists_names(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    inventory_with_coordinator.async_get_items_expiring_soon = AsyncMock(
        return_value=[
            {"name": "Old Milk", "days_until_expiry": -3},
            {"name": "Stale Bread", "days_until_expiry": -1},
            {"name": "Fresh Eggs", "days_until_expiry": 2},
        ]
    )
    intent_obj = _make_intent(
        hass,
        INTENT_EXPIRY_LIST_QUERY,
        {"status": {"value": "expired"}, "inventory": {"value": "Disposable Goods"}},
    )
    response = await ExpiryListIntent().async_handle(intent_obj)
    speech = response.speech["plain"]["speech"]
    assert speech == "2 items are expired in Disposable Goods: Old Milk and Stale Bread."


@pytest.mark.asyncio
async def test_expiry_list_intent_three_names_oxford_comma(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    inventory_with_coordinator.async_get_items_expiring_soon = AsyncMock(
        return_value=[
            {"name": "A", "days_until_expiry": -1},
            {"name": "B", "days_until_expiry": -1},
            {"name": "C", "days_until_expiry": -1},
        ]
    )
    intent_obj = _make_intent(
        hass,
        INTENT_EXPIRY_LIST_QUERY,
        {"status": {"value": "expired"}, "inventory": {"value": "Disposable Goods"}},
    )
    response = await ExpiryListIntent().async_handle(intent_obj)
    speech = response.speech["plain"]["speech"]
    assert speech == "3 items are expired in Disposable Goods: A, B, and C."


@pytest.mark.asyncio
async def test_expiry_list_intent_zero_count(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    inventory_with_coordinator.async_get_items_expiring_soon = AsyncMock(return_value=[])
    intent_obj = _make_intent(
        hass,
        INTENT_EXPIRY_LIST_QUERY,
        {"status": {"value": "expired"}, "inventory": {"value": "Disposable Goods"}},
    )
    response = await ExpiryListIntent().async_handle(intent_obj)
    speech = response.speech["plain"]["speech"]
    assert speech == "0 items are expired in Disposable Goods."


@pytest.mark.asyncio
async def test_expiry_list_intent_caps_at_eight_names(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    inventory_with_coordinator.async_get_items_expiring_soon = AsyncMock(
        return_value=[{"name": f"Item{i}", "days_until_expiry": -1} for i in range(10)]
    )
    intent_obj = _make_intent(
        hass,
        INTENT_EXPIRY_LIST_QUERY,
        {"status": {"value": "expired"}, "inventory": {"value": "Disposable Goods"}},
    )
    response = await ExpiryListIntent().async_handle(intent_obj)
    speech = response.speech["plain"]["speech"]
    assert speech == (
        "10 items are expired in Disposable Goods: Item0, Item1, Item2, Item3, "
        "Item4, Item5, Item6, Item7, and 2 more."
    )


@pytest.mark.asyncio
async def test_expiry_list_intent_expiring_soon_status(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    inventory_with_coordinator.async_get_items_expiring_soon = AsyncMock(
        return_value=[
            {"name": "Old Milk", "days_until_expiry": -3},
            {"name": "Fresh Eggs", "days_until_expiry": 2},
        ]
    )
    intent_obj = _make_intent(
        hass,
        INTENT_EXPIRY_LIST_QUERY,
        {"status": {"value": "expiring_soon"}, "inventory": {"value": "Disposable Goods"}},
    )
    response = await ExpiryListIntent().async_handle(intent_obj)
    speech = response.speech["plain"]["speech"]
    assert speech == "1 item is expiring soon in Disposable Goods: Fresh Eggs."


@pytest.mark.asyncio
async def test_expiry_list_intent_unscoped_omits_inventory_phrase(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    inventory_with_coordinator.async_get_items_expiring_soon = AsyncMock(
        return_value=[{"name": "Old Milk", "days_until_expiry": -3}]
    )
    intent_obj = _make_intent(hass, INTENT_EXPIRY_LIST_QUERY, {"status": {"value": "expired"}})
    response = await ExpiryListIntent().async_handle(intent_obj)
    speech = response.speech["plain"]["speech"]
    assert speech == "1 item is expired: Old Milk."
    inventory_with_coordinator.async_get_items_expiring_soon.assert_awaited_once_with(None)


@pytest.mark.asyncio
async def test_expiry_list_intent_unknown_inventory_raises_intent_handle_error(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    intent_obj = _make_intent(
        hass,
        INTENT_EXPIRY_LIST_QUERY,
        {"status": {"value": "expired"}, "inventory": {"value": "Nonexistent Place"}},
    )
    with pytest.raises(intent.IntentHandleError):
        await ExpiryListIntent().async_handle(intent_obj)


@pytest.mark.asyncio
async def test_expiry_list_intent_no_coordinators_raises_intent_handle_error(
    hass: HomeAssistant,
) -> None:
    intent_obj = _make_intent(hass, INTENT_EXPIRY_LIST_QUERY, {"status": {"value": "expired"}})
    with pytest.raises(intent.IntentHandleError):
        await ExpiryListIntent().async_handle(intent_obj)


def test_format_name_list() -> None:
    from custom_components.simple_inventory.intents import _format_name_list

    assert _format_name_list(["A"]) == "A"
    assert _format_name_list(["A", "B"]) == "A and B"
    assert _format_name_list(["A", "B", "C"]) == "A, B, and C"


@pytest.mark.asyncio
async def test_set_item_quantity_intent_calls_update_item(
    hass: HomeAssistant,
    inventory_with_coordinator: MagicMock,
    registered_services: dict[str, list[dict]],
) -> None:
    intent_obj = _make_intent(
        hass,
        INTENT_SET_ITEM_QUANTITY,
        {
            "item": {"value": "aluminum foil"},
            "inventory": {"value": "Disposable Goods"},
            "quantity": {"value": 5},
        },
    )
    response = await SetItemQuantityIntent().async_handle(intent_obj)
    speech = response.speech["plain"]["speech"]
    assert speech == "Set aluminum foil to 5 in Disposable Goods."
    assert registered_services["update_item"] == [
        {
            "inventory_id": "inv_1",
            "old_name": "Aluminum Foil",
            "name": "Aluminum Foil",
            "quantity": 5.0,
        }
    ]


@pytest.mark.asyncio
async def test_set_item_quantity_intent_string_quantity_coerces(
    hass: HomeAssistant,
    inventory_with_coordinator: MagicMock,
    registered_services: dict[str, list[dict]],
) -> None:
    """LLM tool calls commonly send numeric args as strings; must coerce cleanly."""
    intent_obj = _make_intent(
        hass,
        INTENT_SET_ITEM_QUANTITY,
        {
            "item": {"value": "Aluminum Foil"},
            "inventory": {"value": "Disposable Goods"},
            "quantity": {"value": "5"},
        },
    )
    response = await SetItemQuantityIntent().async_handle(intent_obj)
    speech = response.speech["plain"]["speech"]
    assert speech == "Set Aluminum Foil to 5 in Disposable Goods."


@pytest.mark.asyncio
async def test_set_item_quantity_intent_allows_zero(
    hass: HomeAssistant,
    inventory_with_coordinator: MagicMock,
    registered_services: dict[str, list[dict]],
) -> None:
    intent_obj = _make_intent(
        hass,
        INTENT_SET_ITEM_QUANTITY,
        {
            "item": {"value": "Aluminum Foil"},
            "inventory": {"value": "Disposable Goods"},
            "quantity": {"value": 0},
        },
    )
    response = await SetItemQuantityIntent().async_handle(intent_obj)
    speech = response.speech["plain"]["speech"]
    assert speech == "Set Aluminum Foil to 0 in Disposable Goods."


def test_set_item_quantity_intent_rejects_negative_quantity() -> None:
    with pytest.raises(vol.Invalid):
        SetItemQuantityIntent().async_validate_slots(
            {
                "item": {"value": "Aluminum Foil"},
                "inventory": {"value": "Disposable Goods"},
                "quantity": {"value": -1},
            }
        )


def test_set_item_quantity_intent_rejects_missing_quantity() -> None:
    with pytest.raises(vol.Invalid):
        SetItemQuantityIntent().async_validate_slots(
            {"item": {"value": "Aluminum Foil"}, "inventory": {"value": "Disposable Goods"}}
        )


@pytest.mark.asyncio
async def test_set_item_quantity_intent_unresolvable_item_raises_intent_handle_error(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    intent_obj = _make_intent(
        hass,
        INTENT_SET_ITEM_QUANTITY,
        {
            "item": {"value": "Nonexistent Item"},
            "inventory": {"value": "Disposable Goods"},
            "quantity": {"value": 5},
        },
    )
    with pytest.raises(intent.IntentHandleError):
        await SetItemQuantityIntent().async_handle(intent_obj)


@pytest.mark.asyncio
async def test_set_item_quantity_intent_unknown_inventory_raises_intent_handle_error(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    intent_obj = _make_intent(
        hass,
        INTENT_SET_ITEM_QUANTITY,
        {
            "item": {"value": "Aluminum Foil"},
            "inventory": {"value": "Nonexistent Place"},
            "quantity": {"value": 5},
        },
    )
    with pytest.raises(intent.IntentHandleError):
        await SetItemQuantityIntent().async_handle(intent_obj)


@pytest.mark.asyncio
async def test_set_item_quantity_intent_no_coordinators_raises_intent_handle_error(
    hass: HomeAssistant,
) -> None:
    intent_obj = _make_intent(
        hass,
        INTENT_SET_ITEM_QUANTITY,
        {
            "item": {"value": "Aluminum Foil"},
            "inventory": {"value": "Disposable Goods"},
            "quantity": {"value": 5},
        },
    )
    with pytest.raises(intent.IntentHandleError):
        await SetItemQuantityIntent().async_handle(intent_obj)


@pytest.mark.asyncio
async def test_set_item_quantity_intent_service_error_becomes_intent_handle_error(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    """Resolution succeeds (real coordinator, real item), but the update_item service
    call itself fails downstream (e.g. a race where the item vanished between resolve
    and update) -- must still surface as a clean IntentHandleError."""

    async def _update_item(call: ServiceCall) -> None:
        raise ServiceValidationError("No item named 'Aluminum Foil' found")

    hass.services.async_register(DOMAIN, "update_item", _update_item)

    intent_obj = _make_intent(
        hass,
        INTENT_SET_ITEM_QUANTITY,
        {
            "item": {"value": "Aluminum Foil"},
            "inventory": {"value": "Disposable Goods"},
            "quantity": {"value": 5},
        },
    )
    with pytest.raises(intent.IntentHandleError):
        await SetItemQuantityIntent().async_handle(intent_obj)
