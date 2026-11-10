"""Tests for Simple Inventory's native voice/AI intents."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol
from homeassistant.core import Context, HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import intent, translation

from custom_components.simple_inventory.const import DOMAIN
from custom_components.simple_inventory.data import SimpleInventoryData
from custom_components.simple_inventory.intents import (
    INTENT_ADD_ITEM,
    INTENT_EXPIRY_COUNT_QUERY,
    INTENT_EXPIRY_LIST_QUERY,
    INTENT_LOW_STOCK_COUNT_QUERY,
    INTENT_QUERY_ITEM,
    INTENT_REMOVE_ITEM,
    INTENT_SET_ITEM_QUANTITY,
    INTENT_TRANSFER_ITEM,
    INTENT_TYPES,
    AddItemIntent,
    ExpiryCountIntent,
    ExpiryListIntent,
    LowStockCountIntent,
    QueryItemIntent,
    RemoveItemIntent,
    SetItemQuantityIntent,
    TransferItemIntent,
    async_register_intents,
    async_unregister_intents,
)


@pytest.fixture(autouse=True)
async def loaded_translations(hass: HomeAssistant, enable_custom_integrations: None) -> None:
    """Intents speak str(err); translation-keyed errors render from the English cache
    of set-up components, so mirror what HA does when the integration is set up."""
    await translation.async_load_integrations(hass, {DOMAIN})
    hass.config.components.add(DOMAIN)


@pytest.fixture
def registered_services(hass: HomeAssistant) -> dict[str, list[dict]]:
    """Register fake decrement/increment/update_item/transfer_item services and capture calls."""
    calls: dict[str, list[dict]] = {
        "decrement_item": [],
        "increment_item": [],
        "update_item": [],
        "transfer_item": [],
    }

    async def _decrement(call: ServiceCall) -> None:
        calls["decrement_item"].append(dict(call.data))

    async def _increment(call: ServiceCall) -> None:
        calls["increment_item"].append(dict(call.data))

    async def _update_item(call: ServiceCall) -> None:
        calls["update_item"].append(dict(call.data))

    async def _transfer_item(call: ServiceCall) -> None:
        calls["transfer_item"].append(dict(call.data))

    hass.services.async_register(DOMAIN, "decrement_item", _decrement)
    hass.services.async_register(DOMAIN, "increment_item", _increment)
    hass.services.async_register(DOMAIN, "update_item", _update_item)
    hass.services.async_register(DOMAIN, "transfer_item", _transfer_item)
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
    coordinator.async_list_location_names = AsyncMock(return_value=["Fridge", "Garage"])

    domain_data = hass.data.setdefault(DOMAIN, SimpleInventoryData())
    domain_data.coordinators = {"inv_1": coordinator}
    domain_data.hub = coordinator.hub

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


async def _refusal(handler: intent.IntentHandler, intent_obj: intent.Intent) -> str:
    """Run *handler*; it must refuse with a spoken error response (not an exception)."""
    response = await handler.async_handle(intent_obj)
    assert response.response_type is intent.IntentResponseType.ERROR
    assert response.error_code is intent.IntentResponseErrorCode.FAILED_TO_HANDLE
    return str(response.speech["plain"]["speech"])


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
async def test_query_item_intent_item_not_present_is_refused(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    intent_obj = _make_intent(
        hass,
        INTENT_QUERY_ITEM,
        {"item": {"value": "Paper Towels"}, "inventory": {"value": "Disposable Goods"}},
    )

    assert "Paper Towels" in await _refusal(QueryItemIntent(), intent_obj)


@pytest.mark.asyncio
async def test_query_item_intent_unknown_inventory_is_refused(
    hass: HomeAssistant,
) -> None:
    """An unresolvable inventory must produce clean intent-level speech, not a crash."""
    with patch.object(hass.config_entries, "async_entries", return_value=[]):
        intent_obj = _make_intent(
            hass,
            INTENT_QUERY_ITEM,
            {"item": {"value": "Aluminum Foil"}, "inventory": {"value": "Nonexistent Inventory"}},
        )

        assert "Nonexistent Inventory" in await _refusal(QueryItemIntent(), intent_obj)


def test_async_unregister_intents_removes_all(hass: HomeAssistant) -> None:
    async_register_intents(hass)
    async_unregister_intents(hass)

    registered_types = {handler.intent_type for handler in intent.async_get(hass)}
    assert not set(INTENT_TYPES) & registered_types


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
        TransferItemIntent,
    ):
        assert handler_cls.description
        assert len(handler_cls.description) > 20


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

        assert "not currently loaded" in await _refusal(QueryItemIntent(), intent_obj)


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
    inventory_with_coordinator.hub.async_items_expiring_soon = AsyncMock(
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
    inventory_with_coordinator.hub.async_items_expiring_soon.assert_awaited_once_with("inv_1")


@pytest.mark.asyncio
async def test_expiry_count_intent_counts_expiring_soon_items(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    inventory_with_coordinator.hub.async_items_expiring_soon = AsyncMock(
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
    inventory_with_coordinator.hub.async_items_expiring_soon.assert_awaited_once_with("inv_1")


@pytest.mark.asyncio
async def test_expiry_count_intent_singular_wording(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    inventory_with_coordinator.hub.async_items_expiring_soon = AsyncMock(
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
    inventory_with_coordinator.hub.async_items_expiring_soon.assert_awaited_once_with("inv_1")


@pytest.mark.asyncio
async def test_expiry_count_intent_zero_count(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    inventory_with_coordinator.hub.async_items_expiring_soon = AsyncMock(return_value=[])
    intent_obj = _make_intent(
        hass,
        INTENT_EXPIRY_COUNT_QUERY,
        {"status": {"value": "expired"}, "inventory": {"value": "Disposable Goods"}},
    )
    response = await ExpiryCountIntent().async_handle(intent_obj)
    speech = response.speech["plain"]["speech"]
    assert speech == "0 items are expired in Disposable Goods."
    inventory_with_coordinator.hub.async_items_expiring_soon.assert_awaited_once_with("inv_1")


@pytest.mark.asyncio
async def test_expiry_count_intent_unscoped_omits_inventory_phrase(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    """No `inventory` slot at all -> queries across all inventories (inventory_id=None)
    and the response doesn't mention any inventory by name."""
    inventory_with_coordinator.hub.async_items_expiring_soon = AsyncMock(
        return_value=[{"name": "Old Milk", "days_until_expiry": -3}]
    )
    intent_obj = _make_intent(hass, INTENT_EXPIRY_COUNT_QUERY, {"status": {"value": "expired"}})
    response = await ExpiryCountIntent().async_handle(intent_obj)
    speech = response.speech["plain"]["speech"]
    assert speech == "1 item is expired."
    inventory_with_coordinator.hub.async_items_expiring_soon.assert_awaited_once_with(None)


@pytest.mark.asyncio
async def test_expiry_count_intent_unknown_inventory_is_refused(
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
    await _refusal(ExpiryCountIntent(), intent_obj)


@pytest.mark.asyncio
async def test_expiry_count_intent_no_coordinators_is_refused(
    hass: HomeAssistant,
) -> None:
    intent_obj = _make_intent(hass, INTENT_EXPIRY_COUNT_QUERY, {"status": {"value": "expired"}})
    await _refusal(ExpiryCountIntent(), intent_obj)


def test_async_register_intents_registers_all(hass: HomeAssistant) -> None:
    async_register_intents(hass)
    try:
        registered_types = {i.intent_type for i in intent.async_get(hass)}
        assert set(INTENT_TYPES) <= registered_types
    finally:
        async_unregister_intents(hass)


@pytest.mark.asyncio
async def test_low_stock_count_intent_counts_items(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    inventory_with_coordinator.hub.async_low_stock_items = AsyncMock(
        return_value=[
            {"name": "Bacon", "quantity": 1, "inventory_id": "inv_1"},
            {"name": "Rice", "quantity": 1, "inventory_id": "inv_1"},
        ]
    )
    intent_obj = _make_intent(
        hass, INTENT_LOW_STOCK_COUNT_QUERY, {"inventory": {"value": "Disposable Goods"}}
    )
    response = await LowStockCountIntent().async_handle(intent_obj)
    speech = response.speech["plain"]["speech"]
    assert speech == "2 items are low on stock in Disposable Goods."
    inventory_with_coordinator.hub.async_low_stock_items.assert_awaited_once_with("inv_1")


@pytest.mark.asyncio
async def test_low_stock_count_intent_singular_wording(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    inventory_with_coordinator.hub.async_low_stock_items = AsyncMock(
        return_value=[{"name": "Bacon", "quantity": 1, "inventory_id": "inv_1"}]
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
    inventory_with_coordinator.hub.async_low_stock_items = AsyncMock(return_value=[])
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
    inventory_with_coordinator.hub.async_low_stock_items = AsyncMock(
        return_value=[{"name": "Bacon", "quantity": 1, "inventory_id": "inv_1"}]
    )
    intent_obj = _make_intent(hass, INTENT_LOW_STOCK_COUNT_QUERY, {})
    response = await LowStockCountIntent().async_handle(intent_obj)
    speech = response.speech["plain"]["speech"]
    assert speech == "1 item is low on stock."
    inventory_with_coordinator.hub.async_low_stock_items.assert_awaited_once_with(None)


@pytest.mark.asyncio
async def test_low_stock_count_intent_unknown_inventory_is_refused(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    intent_obj = _make_intent(
        hass, INTENT_LOW_STOCK_COUNT_QUERY, {"inventory": {"value": "Nonexistent Place"}}
    )
    await _refusal(LowStockCountIntent(), intent_obj)


@pytest.mark.asyncio
async def test_low_stock_count_intent_no_coordinators_is_refused(
    hass: HomeAssistant,
) -> None:
    intent_obj = _make_intent(hass, INTENT_LOW_STOCK_COUNT_QUERY, {})
    await _refusal(LowStockCountIntent(), intent_obj)


@pytest.mark.asyncio
async def test_expiry_list_intent_lists_names(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    inventory_with_coordinator.hub.async_items_expiring_soon = AsyncMock(
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
    inventory_with_coordinator.hub.async_items_expiring_soon = AsyncMock(
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
    inventory_with_coordinator.hub.async_items_expiring_soon = AsyncMock(return_value=[])
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
    inventory_with_coordinator.hub.async_items_expiring_soon = AsyncMock(
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
    inventory_with_coordinator.hub.async_items_expiring_soon = AsyncMock(
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
    inventory_with_coordinator.hub.async_items_expiring_soon = AsyncMock(
        return_value=[{"name": "Old Milk", "days_until_expiry": -3}]
    )
    intent_obj = _make_intent(hass, INTENT_EXPIRY_LIST_QUERY, {"status": {"value": "expired"}})
    response = await ExpiryListIntent().async_handle(intent_obj)
    speech = response.speech["plain"]["speech"]
    assert speech == "1 item is expired: Old Milk."
    inventory_with_coordinator.hub.async_items_expiring_soon.assert_awaited_once_with(None)


@pytest.mark.asyncio
async def test_expiry_list_intent_unknown_inventory_is_refused(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    intent_obj = _make_intent(
        hass,
        INTENT_EXPIRY_LIST_QUERY,
        {"status": {"value": "expired"}, "inventory": {"value": "Nonexistent Place"}},
    )
    await _refusal(ExpiryListIntent(), intent_obj)


@pytest.mark.asyncio
async def test_expiry_list_intent_no_coordinators_is_refused(
    hass: HomeAssistant,
) -> None:
    intent_obj = _make_intent(hass, INTENT_EXPIRY_LIST_QUERY, {"status": {"value": "expired"}})
    await _refusal(ExpiryListIntent(), intent_obj)


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
async def test_set_item_quantity_intent_unresolvable_item_is_refused(
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
    await _refusal(SetItemQuantityIntent(), intent_obj)


@pytest.mark.asyncio
async def test_set_item_quantity_intent_unknown_inventory_is_refused(
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
    await _refusal(SetItemQuantityIntent(), intent_obj)


@pytest.mark.asyncio
async def test_set_item_quantity_intent_no_coordinators_is_refused(
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
    await _refusal(SetItemQuantityIntent(), intent_obj)


@pytest.mark.asyncio
async def test_set_item_quantity_intent_service_error_is_refused(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    """Resolution succeeds (real coordinator, real item), but the update_item service
    call itself fails downstream (e.g. a race where the item vanished between resolve
    and update) -- must still surface as a clean spoken refusal."""

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
    await _refusal(SetItemQuantityIntent(), intent_obj)


_FOIL_SLOTS = {"item": {"value": "Aluminum Foil"}, "inventory": {"value": "Disposable Goods"}}


@pytest.mark.asyncio
async def test_remove_item_intent_calls_decrement_with_default_quantity(
    hass: HomeAssistant,
    inventory_with_coordinator: MagicMock,
    registered_services: dict[str, list[dict]],
) -> None:
    intent_obj = _make_intent(hass, INTENT_REMOVE_ITEM, _FOIL_SLOTS)

    response = await RemoveItemIntent().async_handle(intent_obj)

    assert registered_services["decrement_item"] == [
        {"inventory_id": "inv_1", "name": "Aluminum Foil", "amount": 1.0}
    ]
    assert response.speech["plain"]["speech"] == (
        "Removed 1 Aluminum Foil from Disposable Goods. 3 left."
    )


@pytest.mark.parametrize("quantity", [2, "2"])
@pytest.mark.asyncio
async def test_remove_item_intent_explicit_quantity_coerces(
    hass: HomeAssistant,
    inventory_with_coordinator: MagicMock,
    registered_services: dict[str, list[dict]],
    quantity: int | str,
) -> None:
    """LLM tool calls commonly send numeric args as strings; must coerce cleanly."""
    intent_obj = _make_intent(
        hass, INTENT_REMOVE_ITEM, {**_FOIL_SLOTS, "quantity": {"value": quantity}}
    )

    await RemoveItemIntent().async_handle(intent_obj)

    assert registered_services["decrement_item"] == [
        {"inventory_id": "inv_1", "name": "Aluminum Foil", "amount": 2.0}
    ]


@pytest.mark.asyncio
async def test_add_item_intent_calls_increment(
    hass: HomeAssistant,
    inventory_with_coordinator: MagicMock,
    registered_services: dict[str, list[dict]],
) -> None:
    intent_obj = _make_intent(hass, INTENT_ADD_ITEM, _FOIL_SLOTS)

    response = await AddItemIntent().async_handle(intent_obj)

    assert registered_services["increment_item"] == [
        {"inventory_id": "inv_1", "name": "Aluminum Foil", "amount": 1.0}
    ]
    assert response.speech["plain"]["speech"] == (
        "Added 1 Aluminum Foil to Disposable Goods. Now at 3."
    )


@pytest.mark.parametrize(
    ("spoken", "intent_cls", "intent_type", "expected"),
    [
        ("foil wrap", RemoveItemIntent, INTENT_REMOVE_ITEM, "3 left."),
        ("foil", AddItemIntent, INTENT_ADD_ITEM, "Now at 3."),
    ],
)
@pytest.mark.asyncio
async def test_quantity_intents_report_remaining_for_alias_or_partial_name(
    hass: HomeAssistant,
    inventory_with_coordinator: MagicMock,
    registered_services: dict[str, list[dict]],
    spoken: str,
    intent_cls: type[intent.IntentHandler],
    intent_type: str,
    expected: str,
) -> None:
    """The remaining count is looked up by the resolved stored name, so an alias or a
    partial name still gets the trailer (and the service gets the canonical name)."""
    inventory_with_coordinator.async_list_items = AsyncMock(
        return_value=[{"name": "Aluminum Foil", "quantity": 3, "aliases": ["foil wrap"]}]
    )
    intent_obj = _make_intent(
        hass,
        intent_type,
        {"item": {"value": spoken}, "inventory": {"value": "Disposable Goods"}},
    )

    response = await intent_cls().async_handle(intent_obj)

    speech = response.speech["plain"]["speech"]
    assert speech.endswith(expected)
    service_calls = registered_services["decrement_item"] + registered_services["increment_item"]
    assert [call["name"] for call in service_calls] == ["Aluminum Foil"]


@pytest.mark.parametrize(
    ("remaining", "trailer"),
    [
        (0.5, " 0.5 left."),
        (0.7000000000000001, " 0.7 left."),
        (0, " None left."),
        (None, ""),
    ],
)
@pytest.mark.asyncio
async def test_remove_item_intent_remaining_speech(
    hass: HomeAssistant,
    inventory_with_coordinator: MagicMock,
    registered_services: dict[str, list[dict]],
    remaining: float | None,
    trailer: str,
) -> None:
    """Remaining quantity is rendered without float drift; a vanished item drops the trailer."""
    inventory_with_coordinator.async_get_item = AsyncMock(
        return_value=None if remaining is None else {"name": "Aluminum Foil", "quantity": remaining}
    )
    intent_obj = _make_intent(hass, INTENT_REMOVE_ITEM, {**_FOIL_SLOTS, "quantity": {"value": 0.1}})

    response = await RemoveItemIntent().async_handle(intent_obj)

    assert response.speech["plain"]["speech"] == (
        f"Removed 0.1 Aluminum Foil from Disposable Goods.{trailer}"
    )


@pytest.mark.parametrize(
    ("intent_cls", "intent_type", "base"),
    [
        (RemoveItemIntent, INTENT_REMOVE_ITEM, "Removed 1 Aluminum Foil from Disposable Goods."),
        (AddItemIntent, INTENT_ADD_ITEM, "Added 1 Aluminum Foil to Disposable Goods."),
    ],
)
@pytest.mark.asyncio
async def test_quantity_intents_success_speech_survives_quantity_lookup_failure(
    hass: HomeAssistant,
    inventory_with_coordinator: MagicMock,
    registered_services: dict[str, list[dict]],
    intent_cls: type[intent.IntentHandler],
    intent_type: str,
    base: str,
) -> None:
    """A successful mutation still reports success if the follow-up lookup fails."""
    inventory_with_coordinator.async_get_item = AsyncMock(
        side_effect=HomeAssistantError("database is locked")
    )
    intent_obj = _make_intent(hass, intent_type, _FOIL_SLOTS)

    response = await intent_cls().async_handle(intent_obj)

    assert response.speech["plain"]["speech"] == base


@pytest.mark.asyncio
async def test_remove_item_intent_unresolvable_item_is_refused(
    hass: HomeAssistant,
    inventory_with_coordinator: MagicMock,
    registered_services: dict[str, list[dict]],
) -> None:
    intent_obj = _make_intent(
        hass,
        INTENT_REMOVE_ITEM,
        {"item": {"value": "Paper Towels"}, "inventory": {"value": "Disposable Goods"}},
    )

    assert "Paper Towels" in await _refusal(RemoveItemIntent(), intent_obj)
    assert registered_services["decrement_item"] == []


@pytest.mark.asyncio
async def test_remove_item_intent_service_validation_error_is_spoken(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    async def _decrement(call: ServiceCall) -> None:
        raise ServiceValidationError("No item named 'Aluminum Foil' found")

    hass.services.async_register(DOMAIN, "decrement_item", _decrement)
    intent_obj = _make_intent(hass, INTENT_REMOVE_ITEM, _FOIL_SLOTS)

    assert "No item named 'Aluminum Foil'" in await _refusal(RemoveItemIntent(), intent_obj)


@pytest.mark.parametrize(
    ("intent_cls", "intent_type", "service", "speech"),
    [
        (
            RemoveItemIntent,
            INTENT_REMOVE_ITEM,
            "decrement_item",
            "Sorry, I couldn't remove Aluminum Foil in Disposable Goods.",
        ),
        (
            AddItemIntent,
            INTENT_ADD_ITEM,
            "increment_item",
            "Sorry, I couldn't add Aluminum Foil in Disposable Goods.",
        ),
    ],
)
@pytest.mark.asyncio
async def test_quantity_intents_unexpected_service_failure_is_spoken(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    inventory_with_coordinator: MagicMock,
    intent_cls: type[intent.IntentHandler],
    intent_type: str,
    service: str,
    speech: str,
) -> None:
    """Services now propagate DB failures (HomeAssistantError); the intent must not
    claim success and must answer with speech instead of crashing the pipeline. The
    failure itself stays visible in the log."""

    async def _fail(call: ServiceCall) -> None:
        raise HomeAssistantError("disk I/O error")

    hass.services.async_register(DOMAIN, service, _fail)
    intent_obj = _make_intent(hass, intent_type, _FOIL_SLOTS)

    refusal = await _refusal(intent_cls(), intent_obj)
    assert refusal == speech
    [record] = [r for r in caplog.records if r.name.endswith("simple_inventory.intents")]
    assert record.levelname == "ERROR"
    assert record.exc_info is not None
    assert str(record.exc_info[1]) == "disk I/O error"


@pytest.mark.asyncio
async def test_set_item_quantity_intent_unexpected_service_failure_is_spoken(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    async def _update_item(call: ServiceCall) -> None:
        raise HomeAssistantError("disk I/O error")

    hass.services.async_register(DOMAIN, "update_item", _update_item)
    intent_obj = _make_intent(
        hass, INTENT_SET_ITEM_QUANTITY, {**_FOIL_SLOTS, "quantity": {"value": 5}}
    )

    refusal = await _refusal(SetItemQuantityIntent(), intent_obj)
    assert refusal == "Sorry, I couldn't update Aluminum Foil in Disposable Goods."


@pytest.mark.asyncio
async def test_expiry_count_intent_counts_items_not_batches(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    inventory_with_coordinator.hub.async_items_expiring_soon = AsyncMock(
        return_value=[
            {"name": "Milk", "inventory_id": "inv_1", "days_until_expiry": 1},
            {"name": "Milk", "inventory_id": "inv_1", "days_until_expiry": 2},
            {"name": "Eggs", "inventory_id": "inv_1", "days_until_expiry": 2},
        ]
    )
    intent_obj = _make_intent(
        hass, INTENT_EXPIRY_COUNT_QUERY, {"status": {"value": "expiring_soon"}}
    )
    response = await ExpiryCountIntent().async_handle(intent_obj)
    assert response.speech["plain"]["speech"] == "2 items are expiring soon."


@pytest.mark.asyncio
async def test_expiry_list_intent_names_each_item_once(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    inventory_with_coordinator.hub.async_items_expiring_soon = AsyncMock(
        return_value=[
            {"name": "Milk", "inventory_id": "inv_1", "days_until_expiry": -2},
            {"name": "Eggs", "inventory_id": "inv_1", "days_until_expiry": -1},
            {"name": "Milk", "inventory_id": "inv_1", "days_until_expiry": -1},
        ]
    )
    intent_obj = _make_intent(hass, INTENT_EXPIRY_LIST_QUERY, {"status": {"value": "expired"}})
    response = await ExpiryListIntent().async_handle(intent_obj)
    assert response.speech["plain"]["speech"] == "2 items are expired: Milk and Eggs."


@pytest.mark.asyncio
async def test_remove_intent_passes_location_slot(
    hass: HomeAssistant,
    inventory_with_coordinator: MagicMock,
    registered_services: dict[str, list[dict]],
) -> None:
    intent_obj = _make_intent(
        hass,
        INTENT_REMOVE_ITEM,
        {
            "item": {"value": "Aluminum Foil"},
            "inventory": {"value": "Disposable Goods"},
            "location": {"value": "garage"},
        },
    )

    await RemoveItemIntent().async_handle(intent_obj)

    [call] = registered_services["decrement_item"]
    assert call["location"] == "Garage"
    inventory_with_coordinator.async_list_location_names.assert_awaited_once_with("inv_1")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("intent_type", "handler", "service"),
    [
        (INTENT_ADD_ITEM, AddItemIntent, "increment_item"),
        (INTENT_REMOVE_ITEM, RemoveItemIntent, "decrement_item"),
    ],
)
async def test_quantity_intents_reject_unknown_location(
    hass: HomeAssistant,
    inventory_with_coordinator: MagicMock,
    registered_services: dict[str, list[dict]],
    intent_type: str,
    handler: type[intent.IntentHandler],
    service: str,
) -> None:
    intent_obj = _make_intent(hass, intent_type, {**_FOIL_SLOTS, "location": {"value": "Basement"}})

    refusal = await _refusal(handler(), intent_obj)

    assert refusal == "I don't know a location called Basement in Disposable Goods."
    assert registered_services[service] == []


@pytest.mark.asyncio
async def test_add_intent_rejects_ambiguous_location(
    hass: HomeAssistant,
    inventory_with_coordinator: MagicMock,
    registered_services: dict[str, list[dict]],
) -> None:
    inventory_with_coordinator.async_list_location_names = AsyncMock(
        return_value=["Fridge", "Fridge Door"]
    )
    intent_obj = _make_intent(hass, INTENT_ADD_ITEM, {**_FOIL_SLOTS, "location": {"value": "frid"}})

    refusal = await _refusal(AddItemIntent(), intent_obj)

    assert refusal == ("Which location in Disposable Goods did you mean: Fridge, Fridge Door?")
    assert registered_services["increment_item"] == []


@pytest.mark.asyncio
async def test_query_intent_reports_per_location_counts(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    inventory_with_coordinator.async_get_item = AsyncMock(
        return_value={
            "name": "Aluminum Foil",
            "quantity": 3,
            "stocked_locations": ["Fridge", "Garage"],
            "batches": [
                {"quantity": 1.5, "location": "Fridge"},
                {"quantity": 1, "location": "Garage"},
                {"quantity": 0.5, "location": "Fridge"},
            ],
        }
    )
    intent_obj = _make_intent(
        hass,
        INTENT_QUERY_ITEM,
        {"item": {"value": "Aluminum Foil"}, "inventory": {"value": "Disposable Goods"}},
    )

    response = await QueryItemIntent().async_handle(intent_obj)

    assert response.speech["plain"]["speech"] == (
        "Disposable Goods has 3 Aluminum Foil: 2 in Fridge, 1 in Garage."
    )


@pytest.mark.asyncio
async def test_add_intent_passes_location_slot(
    hass: HomeAssistant,
    inventory_with_coordinator: MagicMock,
    registered_services: dict[str, list[dict]],
) -> None:
    intent_obj = _make_intent(
        hass, INTENT_ADD_ITEM, {**_FOIL_SLOTS, "location": {"value": "FRIDGE"}}
    )

    await AddItemIntent().async_handle(intent_obj)

    assert registered_services["increment_item"] == [
        {"inventory_id": "inv_1", "name": "Aluminum Foil", "amount": 1.0, "location": "Fridge"}
    ]


@pytest.fixture
def more_inventories(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> Generator[None, None, None]:
    """Add inventories 'Stuff in Garage' (location Shelf), 'The Pantry' (Bin, Crate) and
    'Crate in The Pantry' (no locations) next to 'Disposable Goods'."""
    entries = []
    for entry_id, name in (
        ("inv_1", "Disposable Goods"),
        ("inv_2", "Stuff in Garage"),
        ("inv_3", "The Pantry"),
        ("inv_4", "Crate in The Pantry"),
    ):
        entry = MagicMock()
        entry.entry_id = entry_id
        entry.data = {"name": name, "entry_type": "inventory"}
        entries.append(entry)

    for entry_id, locations in (
        ("inv_2", ["Shelf"]),
        ("inv_3", ["Bin", "Crate"]),
        ("inv_4", []),
    ):
        coordinator = MagicMock()
        coordinator.async_list_items = AsyncMock(return_value=[{"name": "Aluminum Foil"}])
        coordinator.async_get_item = AsyncMock(
            return_value={"name": "Aluminum Foil", "quantity": 1}
        )
        coordinator.async_list_location_names = AsyncMock(return_value=locations)
        hass.data[DOMAIN].coordinators[entry_id] = coordinator

    with patch.object(hass.config_entries, "async_entries", return_value=entries):
        yield


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("spoken_inventory", "expected"),
    [
        # "<location> in [the] <inventory>" captured whole by a location-less sentence.
        ("fridge in the disposable goods", {"inventory_id": "inv_1", "location": "Fridge"}),
        ("Garage in Disposable Goods", {"inventory_id": "inv_1", "location": "Garage"}),
        # An inventory name containing " in " still resolves as the inventory.
        ("stuff in garage", {"inventory_id": "inv_2"}),
        # The last " in " is tried first, then earlier ones.
        ("shelf in stuff in garage", {"inventory_id": "inv_2", "location": "Shelf"}),
        # An inventory named "The Pantry": the raw right part is tried before the
        # "the"-stripped one.
        ("bin in the pantry", {"inventory_id": "inv_3", "location": "Bin"}),
        ("crate in the pantry", {"inventory_id": "inv_4"}),
        # Left part isn't a location of that inventory: today's fuzzy behaviour, no refusal.
        ("basement in disposable goods", {"inventory_id": "inv_1"}),
        # Right part only fuzzily names an inventory: no split.
        ("fridge in disposable", None),
        # The "the"-stripped whole text names an inventory: no split, today's fuzzy
        # resolution (here: ambiguous between 'The Pantry' and 'Crate in The Pantry').
        ("the crate in the pantry", None),
    ],
)
@pytest.mark.parametrize(
    ("handler", "service"),
    [(AddItemIntent, "increment_item"), (RemoveItemIntent, "decrement_item")],
)
async def test_quantity_intents_split_location_out_of_inventory_text(
    hass: HomeAssistant,
    more_inventories: None,
    registered_services: dict[str, list[dict]],
    handler: type[intent.IntentHandler],
    service: str,
    spoken_inventory: str,
    expected: dict[str, str] | None,
) -> None:
    intent_obj = _make_intent(
        hass,
        handler.intent_type or "",
        {"item": {"value": "Aluminum Foil"}, "inventory": {"value": spoken_inventory}},
    )

    if expected is None:
        await _refusal(handler(), intent_obj)
        assert registered_services[service] == []
        return

    await handler().async_handle(intent_obj)

    assert registered_services[service] == [{"name": "Aluminum Foil", "amount": 1.0, **expected}]


@pytest.mark.asyncio
async def test_quantity_intent_explicit_location_slot_skips_split(
    hass: HomeAssistant,
    more_inventories: None,
    registered_services: dict[str, list[dict]],
) -> None:
    intent_obj = _make_intent(
        hass,
        INTENT_ADD_ITEM,
        {
            "item": {"value": "Aluminum Foil"},
            "inventory": {"value": "fridge in the disposable goods"},
            "location": {"value": "garage"},
        },
    )

    await AddItemIntent().async_handle(intent_obj)

    # The whole text fuzzily resolves to 'Disposable Goods'; only the slot's location is used.
    assert registered_services["increment_item"] == [
        {"inventory_id": "inv_1", "name": "Aluminum Foil", "amount": 1.0, "location": "Garage"}
    ]


def _location_slots(path: str, spoken_location: str) -> dict[str, dict[str, str]]:
    """Item + inventory slots naming *spoken_location* via the slot or the '... in ...' split."""
    if path == "slot":
        return {**_FOIL_SLOTS, "location": {"value": spoken_location}}
    return {
        "item": {"value": "Aluminum Foil"},
        "inventory": {"value": f"{spoken_location} in Disposable Goods"},
    }


@pytest.fixture
def fridge_locations(inventory_with_coordinator: MagicMock) -> MagicMock:
    """'frid' matches Fridge, Fridge Door and Fridge Drawer; nothing else is spoken-alike."""
    inventory_with_coordinator.async_list_location_names = AsyncMock(
        return_value=["Fridge", "Fridge Door", "Fridge Drawer", "Garage"]
    )
    return inventory_with_coordinator


def _stocked_at(coordinator: MagicMock, *locations: str) -> None:
    coordinator.async_get_item = AsyncMock(
        return_value={
            "name": "Aluminum Foil",
            "quantity": len(locations),
            "stocked_locations": list(locations),
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["slot", "split"])
async def test_remove_ambiguous_location_narrows_to_the_one_stocked(
    hass: HomeAssistant,
    fridge_locations: MagicMock,
    registered_services: dict[str, list[dict]],
    path: str,
) -> None:
    _stocked_at(fridge_locations, "Garage", "Fridge Door")
    intent_obj = _make_intent(hass, INTENT_REMOVE_ITEM, _location_slots(path, "frid"))

    await RemoveItemIntent().async_handle(intent_obj)

    assert registered_services["decrement_item"] == [
        {"inventory_id": "inv_1", "name": "Aluminum Foil", "amount": 1.0, "location": "Fridge Door"}
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["slot", "split"])
async def test_remove_ambiguous_location_asks_among_stocked_candidates(
    hass: HomeAssistant,
    fridge_locations: MagicMock,
    registered_services: dict[str, list[dict]],
    path: str,
) -> None:
    _stocked_at(fridge_locations, "Fridge Drawer", "Garage", "Fridge")
    intent_obj = _make_intent(hass, INTENT_REMOVE_ITEM, _location_slots(path, "frid"))

    refusal = await _refusal(RemoveItemIntent(), intent_obj)

    assert refusal == ("Which location in Disposable Goods did you mean: Fridge, Fridge Drawer?")
    assert registered_services["decrement_item"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["slot", "split"])
async def test_remove_ambiguous_location_without_stock_there_is_refused(
    hass: HomeAssistant,
    fridge_locations: MagicMock,
    registered_services: dict[str, list[dict]],
    path: str,
) -> None:
    _stocked_at(fridge_locations, "Garage")
    intent_obj = _make_intent(hass, INTENT_REMOVE_ITEM, _location_slots(path, "frid"))

    refusal = await _refusal(RemoveItemIntent(), intent_obj)

    assert refusal == (
        "There is no Aluminum Foil at Fridge, Fridge Door or Fridge Drawer in Disposable Goods."
    )
    assert registered_services["decrement_item"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["slot", "split"])
async def test_add_ambiguous_location_asks_among_all_candidates(
    hass: HomeAssistant,
    fridge_locations: MagicMock,
    registered_services: dict[str, list[dict]],
    path: str,
) -> None:
    _stocked_at(fridge_locations, "Fridge Door")
    intent_obj = _make_intent(hass, INTENT_ADD_ITEM, _location_slots(path, "frid"))

    refusal = await _refusal(AddItemIntent(), intent_obj)

    assert refusal == (
        "Which location in Disposable Goods did you mean: Fridge, Fridge Door, Fridge Drawer?"
    )
    assert registered_services["increment_item"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["slot", "split"])
@pytest.mark.parametrize(
    ("handler", "service"),
    [(AddItemIntent, "increment_item"), (RemoveItemIntent, "decrement_item")],
)
async def test_exact_location_is_used_without_narrowing(
    hass: HomeAssistant,
    fridge_locations: MagicMock,
    registered_services: dict[str, list[dict]],
    handler: type[intent.IntentHandler],
    service: str,
    path: str,
) -> None:
    _stocked_at(fridge_locations, "Fridge Door")
    intent_obj = _make_intent(hass, handler.intent_type or "", _location_slots(path, "FRIDGE"))

    await handler().async_handle(intent_obj)

    [call] = registered_services[service]
    assert call["location"] == "Fridge"


@pytest.mark.asyncio
async def test_query_intent_reports_unassigned_remainder(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    inventory_with_coordinator.async_get_item = AsyncMock(
        return_value={
            "name": "Aluminum Foil",
            "quantity": 4.5,
            "stocked_locations": ["Fridge", "Garage"],
            "batches": [
                {"quantity": 2, "location": "Fridge"},
                {"quantity": 1.5, "location": ""},
                {"quantity": 1, "location": "Garage"},
            ],
        }
    )
    intent_obj = _make_intent(hass, INTENT_QUERY_ITEM, _FOIL_SLOTS)

    response = await QueryItemIntent().async_handle(intent_obj)

    assert response.speech["plain"]["speech"] == (
        "Disposable Goods has 4.5 Aluminum Foil: 2 in Fridge, 1 in Garage, 1.5 unassigned."
    )


# --- transfer ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transfer_intent_resolves_both_locations_and_calls_transfer_item(
    hass: HomeAssistant,
    inventory_with_coordinator: MagicMock,
    registered_services: dict[str, list[dict]],
) -> None:
    intent_obj = _make_intent(
        hass,
        INTENT_TRANSFER_ITEM,
        {
            **_FOIL_SLOTS,
            "quantity": {"value": "2"},
            "from_location": {"value": "fridge"},
            "to_location": {"value": "garag"},
        },
    )

    response = await TransferItemIntent().async_handle(intent_obj)

    assert registered_services["transfer_item"] == [
        {
            "inventory_id": "inv_1",
            "name": "Aluminum Foil",
            "to_location": "Garage",
            "from_location": "Fridge",
            "amount": 2.0,
        }
    ]
    assert response.speech["plain"]["speech"] == "Moved 2 Aluminum Foil from Fridge to Garage."


@pytest.mark.asyncio
async def test_transfer_intent_without_quantity_or_source(
    hass: HomeAssistant,
    inventory_with_coordinator: MagicMock,
    registered_services: dict[str, list[dict]],
) -> None:
    intent_obj = _make_intent(
        hass, INTENT_TRANSFER_ITEM, {**_FOIL_SLOTS, "to_location": {"value": "Garage"}}
    )

    response = await TransferItemIntent().async_handle(intent_obj)

    assert registered_services["transfer_item"] == [
        {"inventory_id": "inv_1", "name": "Aluminum Foil", "to_location": "Garage"}
    ]
    assert response.speech["plain"]["speech"] == "Moved Aluminum Foil to Garage."


@pytest.mark.asyncio
@pytest.mark.parametrize("slot", ["to_location", "from_location"])
async def test_transfer_intent_refuses_unknown_locations(
    hass: HomeAssistant,
    inventory_with_coordinator: MagicMock,
    registered_services: dict[str, list[dict]],
    slot: str,
) -> None:
    slots = {**_FOIL_SLOTS, "to_location": {"value": "Garage"}, slot: {"value": "Basement"}}
    intent_obj = _make_intent(hass, INTENT_TRANSFER_ITEM, slots)

    refusal = await _refusal(TransferItemIntent(), intent_obj)

    assert refusal == "I don't know a location called Basement in Disposable Goods."
    assert registered_services["transfer_item"] == []


def test_transfer_intent_requires_a_destination() -> None:
    with pytest.raises(vol.Invalid):
        TransferItemIntent().async_validate_slots(_FOIL_SLOTS)


@pytest.mark.asyncio
async def test_transfer_intent_speaks_the_translated_service_error(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    async def _transfer(call: ServiceCall) -> None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="insufficient_stock",
            translation_placeholders={
                "name": "Aluminum Foil",
                "location": "Fridge",
                "available": "1",
            },
        )

    hass.services.async_register(DOMAIN, "transfer_item", _transfer)
    intent_obj = _make_intent(
        hass, INTENT_TRANSFER_ITEM, {**_FOIL_SLOTS, "to_location": {"value": "Garage"}}
    )

    refusal = await _refusal(TransferItemIntent(), intent_obj)

    assert refusal == "Only 1 of Aluminum Foil available at Fridge; nothing was moved"


@pytest.mark.asyncio
async def test_transfer_intent_unexpected_service_failure_is_spoken(
    hass: HomeAssistant, inventory_with_coordinator: MagicMock
) -> None:
    async def _transfer(call: ServiceCall) -> None:
        raise HomeAssistantError("disk I/O error")

    hass.services.async_register(DOMAIN, "transfer_item", _transfer)
    intent_obj = _make_intent(
        hass, INTENT_TRANSFER_ITEM, {**_FOIL_SLOTS, "to_location": {"value": "Garage"}}
    )

    refusal = await _refusal(TransferItemIntent(), intent_obj)

    assert refusal == "Sorry, I couldn't move Aluminum Foil in Disposable Goods."
