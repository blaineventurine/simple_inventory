"""Transfers end to end (spec 2026-10-25, T1-T8): coordinator/services -> SQLite."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError

from custom_components.simple_inventory.const import (
    EVENT_ITEM_DEPLETED,
    EVENT_ITEM_QUANTITY_CHANGED,
    EVENT_ITEM_RESTOCKED,
    EVENT_ITEM_TRANSFERRED,
)
from custom_components.simple_inventory.coordinator import SimpleInventoryCoordinator

from ..harness import TodoStack


def _capture(hass: HomeAssistant, event_type: str) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []

    @callback
    def _listener(event: Event) -> None:
        seen.append(dict(event.data))

    hass.bus.async_listen(event_type, _listener)
    return seen


async def _item(stack: TodoStack, name: str = "Milk") -> dict[str, Any]:
    [item] = [i for i in await stack.repo.list_items_with_details("kitchen") if i["name"] == name]
    return item


async def _stock_milk(stack: TodoStack) -> None:
    """Milk: 6 in the Fridge (expires 2026-11-01, 1.5 each) and 2 in the Pantry (no expiry)."""
    await stack.call(
        "add_item",
        inventory_id="kitchen",
        name="Milk",
        quantity=6,
        location="Fridge",
        expiry_date="2026-11-01",
        price=1.5,
    )
    await stack.call(
        "increment_item", inventory_id="kitchen", name="Milk", amount=2, location="Pantry"
    )


def _kitchen(stack: TodoStack) -> SimpleInventoryCoordinator:
    return stack.coordinators["kitchen"]


async def _transfers(stack: TodoStack) -> list[dict[str, Any]]:
    return await _kitchen(stack).async_get_item_history("kitchen", "Milk", event_type="transfer")


# --- coordinator ------------------------------------------------------------------------


async def test_transfer_part_of_a_batch(todo_stack: TodoStack) -> None:
    await _stock_milk(todo_stack)
    fridge = (await _item(todo_stack))["batches"][0]
    transferred = _capture(todo_stack.hass, EVENT_ITEM_TRANSFERRED)
    quantity_events = [
        _capture(todo_stack.hass, event)
        for event in (EVENT_ITEM_DEPLETED, EVENT_ITEM_RESTOCKED, EVENT_ITEM_QUANTITY_CHANGED)
    ]

    payload = await _kitchen(todo_stack).async_transfer_item(
        "kitchen", "Milk", to_location="Garage", amount=2, batch_id=fridge["id"]
    )
    await todo_stack.hass.async_block_till_done()

    expected = {
        "item_name": "Milk",
        "inventory_id": "kitchen",
        "amount": 2,
        "from_location": "Fridge",
        "to_location": "Garage",
    }
    assert payload == expected
    assert transferred == [expected]
    assert quantity_events == [[], [], []]
    milk = await _item(todo_stack)
    assert milk["quantity"] == 8
    assert sorted(
        (b["location"], b["quantity"], b["expiry_date"], b["unit_price"]) for b in milk["batches"]
    ) == [
        ("Fridge", 4, "2026-11-01", 1.5),
        ("Garage", 2, "2026-11-01", 1.5),
        ("Pantry", 2, "", 1.5),
    ]
    assert milk["locations"] == ["Fridge", "Garage"]  # T4: appended, first one unchanged
    assert [
        (
            h["amount"],
            h["quantity_before"],
            h["quantity_after"],
            h["location_from"],
            h["location_to"],
            h["batch_id"],
            h["source"],
            h["price"],
        )
        for h in await _transfers(todo_stack)
    ] == [(2, 8, 8, "Fridge", "Garage", fridge["id"], "service", 1.5)]


async def test_transfer_without_source_moves_soonest_stock_not_already_there(
    todo_stack: TodoStack,
) -> None:
    await _stock_milk(todo_stack)
    await todo_stack.call(
        "increment_item",
        inventory_id="kitchen",
        name="Milk",
        amount=1,
        location="Garage",
        expiry_date="2026-10-28",
    )

    payload = await _kitchen(todo_stack).async_transfer_item(
        "kitchen", "Milk", to_location="garage", amount=7
    )

    assert (payload["amount"], payload["from_location"], payload["to_location"]) == (
        7,
        "",
        "Garage",
    )
    milk = await _item(todo_stack)
    assert sorted((b["location"], b["expiry_date"], b["quantity"]) for b in milk["batches"]) == [
        ("Garage", "", 1),
        ("Garage", "2026-10-28", 1),
        ("Garage", "2026-11-01", 6),
        ("Pantry", "", 1),
    ]
    assert sorted((h["location_from"], h["amount"]) for h in await _transfers(todo_stack)) == [
        ("Fridge", 6),
        ("Pantry", 1),
    ]


async def test_transfer_everything_at_a_location(todo_stack: TodoStack) -> None:
    await _stock_milk(todo_stack)

    payload = await _kitchen(todo_stack).async_transfer_item(
        "kitchen", "Milk", to_location="Fridge", from_location="pantry"
    )

    assert (payload["amount"], payload["from_location"]) == (2, "Pantry")
    milk = await _item(todo_stack)
    assert sorted((b["location"], b["expiry_date"], b["quantity"]) for b in milk["batches"]) == [
        ("Fridge", "", 2),
        ("Fridge", "2026-11-01", 6),
    ]


@pytest.mark.parametrize(
    ("kwargs", "key"),
    [
        ({"name": "Milk", "to_location": "Fridge", "from_location": "fridge"}, "same_location"),
        ({"name": "Milk", "to_location": "Fridge", "batch_id": "<fridge>"}, "same_location"),
        ({"name": "Milk", "to_location": "Attic", "batch_id": "nope"}, "batch_not_found"),
        (
            {"name": "Milk", "to_location": "Attic", "from_location": "Garage"},
            "no_stock_at_location",
        ),
        (
            {"name": "Milk", "to_location": "Attic", "from_location": "Fridge", "amount": 7},
            "insufficient_stock",
        ),
        ({"name": "Milk", "to_location": "Attic", "amount": 9}, "insufficient_stock"),
        ({"name": "Bread", "to_location": "Attic"}, "item_not_found"),
        ({"name": "Milk", "to_location": "Attic", "amount": 0}, "invalid_amount"),
        ({"name": "Milk", "to_location": "Attic", "amount": -3}, "invalid_amount"),
        ({"name": "Milk", "to_location": "Attic", "amount": 0.0000001}, "invalid_amount"),
        ({"name": "Milk", "to_location": "   "}, "location_required"),
        ({"name": "Milk", "to_location": ""}, "location_required"),
    ],
)
async def test_transfer_errors_write_nothing(
    todo_stack: TodoStack, kwargs: dict[str, Any], key: str
) -> None:
    await _stock_milk(todo_stack)
    before = await _item(todo_stack)
    fridge_batch = before["batches"][0]["id"]
    call = {k: (fridge_batch if v == "<fridge>" else v) for k, v in kwargs.items()}
    transferred = _capture(todo_stack.hass, EVENT_ITEM_TRANSFERRED)

    with pytest.raises(ServiceValidationError) as err:
        await _kitchen(todo_stack).async_transfer_item("kitchen", **call)
    await todo_stack.hass.async_block_till_done()

    assert err.value.translation_key == key
    after = await _item(todo_stack)
    assert (after["batches"], after["locations"]) == (before["batches"], before["locations"])
    assert await _transfers(todo_stack) == []
    assert "Attic" not in await _kitchen(todo_stack).async_list_location_names("kitchen")
    assert transferred == []


async def test_insufficient_stock_names_the_source_and_what_it_holds(
    todo_stack: TodoStack,
) -> None:
    await _stock_milk(todo_stack)

    with pytest.raises(ServiceValidationError) as err:
        await _kitchen(todo_stack).async_transfer_item(
            "kitchen", "Milk", to_location="Garage", from_location="Pantry", amount=2.5
        )

    assert err.value.translation_placeholders == {
        "name": "Milk",
        "location": "Pantry",
        "available": "2",
    }


async def test_invalid_amount_names_the_amount(todo_stack: TodoStack) -> None:
    await _stock_milk(todo_stack)

    with pytest.raises(ServiceValidationError) as err:
        await _kitchen(todo_stack).async_transfer_item(
            "kitchen", "Milk", to_location="Garage", amount=-3
        )

    assert err.value.translation_placeholders == {"amount": "-3"}


async def test_batch_source_vanishing_concurrently_is_a_clean_error(
    todo_stack: TodoStack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A batch deleted between validation and listing its stock: no IndexError."""
    await _stock_milk(todo_stack)
    fridge = (await _item(todo_stack))["batches"][0]

    async def _no_sources(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr(todo_stack.repo, "list_transfer_sources", _no_sources)

    with pytest.raises(ServiceValidationError) as err:
        await _kitchen(todo_stack).async_transfer_item(
            "kitchen", "Milk", to_location="Pantry", batch_id=fridge["id"]
        )

    assert err.value.translation_key == "insufficient_stock"
    assert await _transfers(todo_stack) == []


async def test_sources_emptied_before_the_transaction_is_insufficient_stock(
    todo_stack: TodoStack, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _stock_milk(todo_stack)

    async def _emptied(*_args: Any, **_kwargs: Any) -> Any:
        raise ValueError("no stock to transfer")

    monkeypatch.setattr(todo_stack.repo, "transfer_stock", _emptied)

    with pytest.raises(ServiceValidationError) as err:
        await _kitchen(todo_stack).async_transfer_item(
            "kitchen", "Milk", to_location="Garage", from_location="Pantry"
        )

    assert (err.value.translation_key, err.value.translation_placeholders) == (
        "insufficient_stock",
        {"name": "Milk", "location": "Pantry", "available": "0"},
    )
    assert await _transfers(todo_stack) == []


async def test_transfer_with_nothing_outside_the_destination(todo_stack: TodoStack) -> None:
    await todo_stack.call("add_item", inventory_id="kitchen", name="Eggs", quantity=0)
    await todo_stack.call(
        "add_item", inventory_id="kitchen", name="Rice", quantity=1, location="Pantry"
    )

    with pytest.raises(ServiceValidationError) as empty:
        await _kitchen(todo_stack).async_transfer_item("kitchen", "Eggs", to_location="Pantry")
    with pytest.raises(ServiceValidationError) as there:
        await _kitchen(todo_stack).async_transfer_item("kitchen", "Rice", to_location="pantry")

    assert (empty.value.translation_key, empty.value.translation_placeholders) == (
        "insufficient_stock",
        {"name": "Eggs", "location": "Kitchen", "available": "0"},
    )
    assert (there.value.translation_key, there.value.translation_placeholders) == (
        "same_location",
        {"location": "pantry"},
    )


# --- service ----------------------------------------------------------------------------


async def test_transfer_item_service_by_inventory_name_and_fuzzy_item_name(
    todo_stack: TodoStack,
) -> None:
    await _stock_milk(todo_stack)
    fridge = (await _item(todo_stack))["batches"][0]

    await todo_stack.call(
        "transfer_item",
        inventory_name="kitchen",
        name="milk",
        to_location="Garage",
        amount=2,
        batch_id=fridge["id"],
    )

    milk = await _item(todo_stack)
    assert sorted((b["location"], b["quantity"]) for b in milk["batches"]) == [
        ("Fridge", 4),
        ("Garage", 2),
        ("Pantry", 2),
    ]


async def test_transfer_item_service_by_barcode(todo_stack: TodoStack) -> None:
    await todo_stack.call(
        "add_item",
        inventory_id="kitchen",
        name="Milk",
        quantity=3,
        location="Fridge",
        barcode="123",
    )

    await todo_stack.call(
        "transfer_item", inventory_id="kitchen", barcode="123", to_location="Garage"
    )

    assert [(b["location"], b["quantity"]) for b in (await _item(todo_stack))["batches"]] == [
        ("Garage", 3)
    ]


async def test_transfer_item_service_errors_carry_the_translation_key(
    todo_stack: TodoStack,
) -> None:
    await _stock_milk(todo_stack)

    with pytest.raises(ServiceValidationError) as err:
        await todo_stack.call(
            "transfer_item",
            inventory_id="kitchen",
            name="Milk",
            from_location="Fridge",
            to_location="fridge",
        )

    assert err.value.translation_key == "same_location"


async def test_transfer_item_service_leaves_the_todo_list_alone(todo_stack: TodoStack) -> None:
    await todo_stack.call(
        "add_item",
        inventory_id="kitchen",
        name="Milk",
        quantity=1,
        location="Fridge",
        auto_add_enabled=True,
        auto_add_to_list_quantity=2,
        todo_list="todo.grocery",
    )
    assert todo_stack.todo.summaries("todo.grocery") == ["Milk (x2)"]
    todo_stack.todo.calls.clear()

    await todo_stack.call(
        "transfer_item", inventory_id="kitchen", name="Milk", to_location="Garage"
    )

    assert todo_stack.todo.calls == []
    assert todo_stack.todo.summaries("todo.grocery") == ["Milk (x2)"]
