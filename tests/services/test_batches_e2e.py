"""Batches end to end: real services -> coordinator -> SQLite."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError

from custom_components.simple_inventory.const import (
    EVENT_ITEM_DEPLETED,
    EVENT_ITEM_QUANTITY_CHANGED,
)

from ..harness import TodoStack


def _capture(hass: HomeAssistant, event_type: str) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []

    @callback
    def _listener(event: Event) -> None:
        seen.append(dict(event.data))

    hass.bus.async_listen(event_type, _listener)
    return seen


async def _milk(stack: TodoStack) -> dict[str, Any]:
    [item] = [i for i in await stack.repo.list_items_with_details("kitchen") if i["name"] == "Milk"]
    return item


async def test_add_item_creates_initial_batch(todo_stack: TodoStack) -> None:
    await todo_stack.call(
        "add_item",
        inventory_id="kitchen",
        name="Milk",
        quantity=2,
        expiry_date="2026-11-01",
        location="Fridge, Garage",
        price=1.5,
    )
    milk = await _milk(todo_stack)
    assert [
        (b["quantity"], b["location"], b["expiry_date"], b["unit_price"]) for b in milk["batches"]
    ] == [(2, "Fridge", "2026-11-01", 1.5)]


async def test_increment_merges_or_creates_batches(todo_stack: TodoStack) -> None:
    await todo_stack.call(
        "add_item", inventory_id="kitchen", name="Milk", quantity=1, location="Fridge"
    )
    await todo_stack.call("increment_item", inventory_id="kitchen", name="Milk", amount=2)
    await todo_stack.call(
        "increment_item",
        inventory_id="kitchen",
        name="Milk",
        amount=1,
        expiry_date="2026-11-01",
        location="Garage",
        purchased_at="2026-10-20",
    )
    milk = await _milk(todo_stack)
    assert milk["quantity"] == 4
    assert sorted((b["quantity"], b["location"]) for b in milk["batches"]) == [
        (1, "Garage"),
        (3, "Fridge"),
    ]


async def test_decrement_consumes_soonest_expiry_and_records_one_event_per_batch(
    todo_stack: TodoStack,
) -> None:
    await todo_stack.call("add_item", inventory_id="kitchen", name="Milk", quantity=0)
    for expiry in ("2026-12-01", "2026-11-01"):
        await todo_stack.call(
            "increment_item", inventory_id="kitchen", name="Milk", amount=1, expiry_date=expiry
        )
    changed = _capture(todo_stack.hass, EVENT_ITEM_QUANTITY_CHANGED)

    await todo_stack.call("decrement_item", inventory_id="kitchen", name="Milk", amount=1.5)
    await todo_stack.hass.async_block_till_done()

    milk = await _milk(todo_stack)
    assert [(b["expiry_date"], b["quantity"]) for b in milk["batches"]] == [("2026-12-01", 0.5)]
    history = await todo_stack.coordinators["kitchen"].async_get_item_history("kitchen", "Milk")
    decrements = [h for h in history if h["event_type"] == "decrement"]
    assert sorted((h["amount"], h["quantity_before"], h["quantity_after"]) for h in decrements) == [
        (0.5, 1, 0.5),
        (1, 2, 1),
    ]
    assert all(h["batch_id"] for h in decrements)
    assert len(changed) == 1 and (changed[0]["quantity_before"], changed[0]["quantity_after"]) == (
        2,
        0.5,
    )


async def test_decrement_by_location(todo_stack: TodoStack) -> None:
    await todo_stack.call(
        "add_item", inventory_id="kitchen", name="Milk", quantity=2, location="Fridge"
    )
    await todo_stack.call(
        "increment_item", inventory_id="kitchen", name="Milk", amount=1, location="Garage"
    )
    await todo_stack.call(
        "decrement_item", inventory_id="kitchen", name="Milk", amount=1, location="Garage"
    )
    milk = await _milk(todo_stack)
    assert [(b["location"], b["quantity"]) for b in milk["batches"]] == [("Fridge", 2)]


@pytest.mark.parametrize(
    ("extra", "key"),
    [
        ({"location": "Attic"}, "no_stock_at_location"),
        ({"location": "Garage"}, "no_stock_at_location"),
        ({"batch_id": "nope"}, "batch_not_found"),
    ],
)
async def test_decrement_target_errors_write_nothing(
    todo_stack: TodoStack, extra: dict[str, str], key: str
) -> None:
    await todo_stack.call(
        "add_item", inventory_id="kitchen", name="Milk", quantity=2, location="Fridge", price=1.5
    )
    await todo_stack.call("add_item", inventory_id="kitchen", name="Eggs", location="Garage")
    with pytest.raises(ServiceValidationError) as err:
        await todo_stack.call(
            "decrement_item", inventory_id="kitchen", name="Milk", amount=1, price=9.5, **extra
        )
    assert err.value.translation_key == key
    milk = await _milk(todo_stack)
    assert (milk["quantity"], milk["price"]) == (2, 1.5)


async def test_decrement_batch_id_wins_over_location(todo_stack: TodoStack) -> None:
    await todo_stack.call(
        "add_item", inventory_id="kitchen", name="Milk", quantity=2, location="Fridge"
    )
    [batch] = (await _milk(todo_stack))["batches"]
    await todo_stack.call(
        "decrement_item",
        inventory_id="kitchen",
        name="Milk",
        amount=1,
        batch_id=batch["id"],
        location="Attic",
    )
    assert (await _milk(todo_stack))["quantity"] == 1


async def test_decrement_records_caller_price_on_history(todo_stack: TodoStack) -> None:
    await todo_stack.call("add_item", inventory_id="kitchen", name="Milk", quantity=1, price=1.5)
    await todo_stack.call(
        "increment_item", inventory_id="kitchen", name="Milk", amount=1, expiry_date="2026-11-01"
    )
    await todo_stack.call("decrement_item", inventory_id="kitchen", name="Milk", amount=2, price=4)
    history = await todo_stack.coordinators["kitchen"].async_get_item_history("kitchen", "Milk")
    prices = [h["price"] for h in history if h["event_type"] == "decrement"]
    assert prices == [4, 4]


async def test_scan_barcode_increment_creates_batch_at_location(todo_stack: TodoStack) -> None:
    await todo_stack.call(
        "add_item",
        inventory_id="kitchen",
        name="Milk",
        quantity=1,
        location="Fridge",
        barcode="123",
    )
    await todo_stack.call(
        "scan_barcode",
        barcode="123",
        action="increment",
        inventory_id="kitchen",
        location="Garage",
        expiry_date="2026-11-01",
    )
    milk = await _milk(todo_stack)
    assert sorted((b["location"], b["expiry_date"], b["quantity"]) for b in milk["batches"]) == [
        ("Fridge", "", 1),
        ("Garage", "2026-11-01", 1),
    ]


async def test_depleted_fires_once_when_last_batch_consumed(todo_stack: TodoStack) -> None:
    await todo_stack.call("add_item", inventory_id="kitchen", name="Milk", quantity=1)
    await todo_stack.call(
        "increment_item", inventory_id="kitchen", name="Milk", amount=1, expiry_date="2026-11-01"
    )
    depleted = _capture(todo_stack.hass, EVENT_ITEM_DEPLETED)
    await todo_stack.call("decrement_item", inventory_id="kitchen", name="Milk", amount=5)
    await todo_stack.hass.async_block_till_done()
    assert len(depleted) == 1 and depleted[0]["previous_quantity"] == 2


async def test_update_quantity_up_adds_stock_and_down_consumes(todo_stack: TodoStack) -> None:
    await todo_stack.call(
        "add_item", inventory_id="kitchen", name="Milk", quantity=2, expiry_date="2026-11-01"
    )
    await todo_stack.call(
        "update_item", inventory_id="kitchen", old_name="Milk", name="Milk", quantity=5
    )
    milk = await _milk(todo_stack)
    assert milk["quantity"] == 5 and len(milk["batches"]) == 2  # new stock has no expiry
    await todo_stack.call(
        "update_item", inventory_id="kitchen", old_name="Milk", name="Milk", quantity=1
    )
    milk = await _milk(todo_stack)
    assert [(b["expiry_date"], b["quantity"]) for b in milk["batches"]] == [("", 1)]


async def test_update_expiry_applies_to_single_batch(todo_stack: TodoStack) -> None:
    await todo_stack.call(
        "add_item", inventory_id="kitchen", name="Milk", quantity=2, expiry_date="2026-11-01"
    )
    await todo_stack.call(
        "update_item",
        inventory_id="kitchen",
        old_name="Milk",
        name="Milk",
        expiry_date="2026-11-09",
    )
    assert [b["expiry_date"] for b in (await _milk(todo_stack))["batches"]] == ["2026-11-09"]


async def test_full_form_resave_is_a_noop_with_many_batches(todo_stack: TodoStack) -> None:
    await todo_stack.call(
        "add_item",
        inventory_id="kitchen",
        name="Milk",
        quantity=1,
        expiry_date="2026-11-01",
        price=2,
    )
    await todo_stack.call(
        "increment_item", inventory_id="kitchen", name="Milk", amount=1, expiry_date="2026-12-01"
    )
    milk = await _milk(todo_stack)
    await todo_stack.call(
        "update_item",
        inventory_id="kitchen",
        old_name="Milk",
        name="Milk",
        quantity=milk["quantity"],
        expiry_date=milk["expiry_date"],
        price=milk["price"],
        unit="L",
    )
    after = await _milk(todo_stack)
    assert after["batches"] == milk["batches"] and after["unit"] == "L"


@pytest.mark.parametrize("field", [{"expiry_date": "2027-01-01"}, {"price": 9}])
async def test_ambiguous_scalar_edit_is_rejected_without_writing(
    todo_stack: TodoStack, field: dict[str, Any]
) -> None:
    await todo_stack.call(
        "add_item",
        inventory_id="kitchen",
        name="Milk",
        quantity=1,
        expiry_date="2026-11-01",
        location="Fridge",
    )
    await todo_stack.call(
        "increment_item", inventory_id="kitchen", name="Milk", amount=1, expiry_date="2026-12-01"
    )
    before = await _milk(todo_stack)
    with pytest.raises(ServiceValidationError) as err:
        await todo_stack.call(
            "update_item",
            inventory_id="kitchen",
            old_name="Milk",
            name="Whole Milk",
            unit="L",
            location="Pantry",
            **field,
        )
    assert err.value.translation_key == "batch_required"
    assert await todo_stack.item("kitchen", "Whole Milk") is None
    assert await _milk(todo_stack) == before


async def test_resave_echoing_rounded_stored_price_is_not_a_price_change(
    todo_stack: TodoStack,
) -> None:
    await todo_stack.call(
        "add_item", inventory_id="kitchen", name="Milk", quantity=1, expiry_date="2026-11-01"
    )
    await todo_stack.call(
        "increment_item",
        inventory_id="kitchen",
        name="Milk",
        amount=1,
        expiry_date="2026-12-01",
        price=10 / 3,
    )
    milk = await _milk(todo_stack)
    await todo_stack.call(
        "update_item",
        inventory_id="kitchen",
        old_name="Milk",
        name="Milk",
        quantity=milk["quantity"],
        expiry_date=milk["expiry_date"],
        price=milk["price"],
        unit="L",
    )
    after = await _milk(todo_stack)
    assert after["batches"] == milk["batches"] and after["unit"] == "L"


async def test_expiry_edit_without_batches_is_rejected_without_writing(
    todo_stack: TodoStack,
) -> None:
    await todo_stack.call("add_item", inventory_id="kitchen", name="Milk", quantity=0)
    before = await _milk(todo_stack)
    with pytest.raises(ServiceValidationError) as err:
        await todo_stack.call(
            "update_item",
            inventory_id="kitchen",
            old_name="Milk",
            name="Milk",
            expiry_date="2027-01-01",
            unit="L",
        )
    assert err.value.translation_key == "no_stock_for_expiry"
    assert err.value.translation_placeholders == {"name": "Milk"}
    assert await _milk(todo_stack) == before


async def test_price_edit_without_batches_updates_item_price(todo_stack: TodoStack) -> None:
    await todo_stack.call("add_item", inventory_id="kitchen", name="Milk", quantity=0, price=1)
    await todo_stack.call(
        "update_item", inventory_id="kitchen", old_name="Milk", name="Milk", price=2.5
    )
    milk = await _milk(todo_stack)
    assert milk["price"] == 2.5 and milk["batches"] == []


async def test_coordinator_update_and_remove_batch(todo_stack: TodoStack) -> None:
    await todo_stack.call(
        "add_item", inventory_id="kitchen", name="Milk", quantity=2, location="Fridge"
    )
    coordinator = todo_stack.coordinators["kitchen"]
    [batch] = (await _milk(todo_stack))["batches"]

    await coordinator.async_update_batch(
        "kitchen",
        batch["id"],
        quantity=3,
        expiry_date="2026-11-01",
        location="Garage",
        unit_price=1.25,
    )
    [batch] = (await _milk(todo_stack))["batches"]
    assert (batch["quantity"], batch["expiry_date"], batch["location"], batch["unit_price"]) == (
        3,
        "2026-11-01",
        "Garage",
        1.25,
    )
    history = await coordinator.async_get_item_history("kitchen", "Milk")
    assert history[0]["event_type"] == "update" and history[0]["batch_id"] == batch["id"]

    await coordinator.async_remove_batch("kitchen", batch["id"])
    assert (await _milk(todo_stack))["quantity"] == 0
    with pytest.raises(ServiceValidationError):
        await coordinator.async_remove_batch("kitchen", batch["id"])


async def test_update_batch_without_quantity_change_writes_no_history(
    todo_stack: TodoStack,
) -> None:
    await todo_stack.call("add_item", inventory_id="kitchen", name="Milk", quantity=2)
    coordinator = todo_stack.coordinators["kitchen"]
    [batch] = (await _milk(todo_stack))["batches"]
    history_before = await coordinator.async_get_item_history("kitchen", "Milk")
    refreshes: list[str] = []
    original = coordinator._after_change

    async def _spy(inventory_id: str) -> None:
        refreshes.append(inventory_id)
        await original(inventory_id)

    coordinator._after_change = _spy  # type: ignore[method-assign]

    name = await coordinator.async_update_batch("kitchen", batch["id"], expiry_date="2026-12-01")

    assert name == "Milk"
    assert refreshes == ["kitchen"]
    [batch] = (await _milk(todo_stack))["batches"]
    assert (batch["quantity"], batch["expiry_date"]) == (2, "2026-12-01")
    assert await coordinator.async_get_item_history("kitchen", "Milk") == history_before


async def test_update_batch_rejects_batch_from_other_inventory(todo_stack: TodoStack) -> None:
    await todo_stack.call("add_item", inventory_id="kitchen", name="Milk", quantity=2)
    [batch] = (await _milk(todo_stack))["batches"]
    pantry = await todo_stack.add_inventory("pantry", "Pantry")
    with pytest.raises(ServiceValidationError) as err:
        await pantry.async_update_batch("pantry", batch["id"], quantity=1)
    assert err.value.translation_key == "batch_not_found"
    with pytest.raises(ServiceValidationError):
        await pantry.async_remove_batch("pantry", batch["id"])
    assert [b["quantity"] for b in (await _milk(todo_stack))["batches"]] == [2]


async def test_update_batch_unit_price_becomes_item_price(todo_stack: TodoStack) -> None:
    await todo_stack.call("add_item", inventory_id="kitchen", name="Milk", quantity=2, price=1.0)
    coordinator = todo_stack.coordinators["kitchen"]
    [batch] = (await _milk(todo_stack))["batches"]

    await coordinator.async_update_batch("kitchen", batch["id"], unit_price=2.5)
    assert (await _milk(todo_stack))["price"] == 2.5

    await todo_stack.call("increment_item", inventory_id="kitchen", name="Milk", amount=1)
    milk = await _milk(todo_stack)
    assert [(b["id"], b["quantity"], b["unit_price"]) for b in milk["batches"]] == [
        (batch["id"], 3, 2.5)
    ]


async def test_update_batch_ignores_blank_purchased_at(todo_stack: TodoStack) -> None:
    await todo_stack.call("add_item", inventory_id="kitchen", name="Milk", quantity=2)
    coordinator = todo_stack.coordinators["kitchen"]
    [batch] = (await _milk(todo_stack))["batches"]

    await coordinator.async_update_batch("kitchen", batch["id"], purchased_at="")
    await coordinator.async_update_batch("kitchen", batch["id"], purchased_at="  ")

    [after] = (await _milk(todo_stack))["batches"]
    assert after["purchased_at"] == batch["purchased_at"] != ""


async def test_update_batch_and_remove_batch_services_sync_todo(todo_stack: TodoStack) -> None:
    await todo_stack.call(
        "add_item",
        inventory_id="kitchen",
        name="Milk",
        quantity=3,
        auto_add_enabled=True,
        auto_add_to_list_quantity=1,
        todo_list="todo.grocery",
    )
    [batch] = (await _milk(todo_stack))["batches"]
    await todo_stack.call("update_batch", inventory_id="kitchen", batch_id=batch["id"], quantity=1)
    assert todo_stack.todo.summaries("todo.grocery") == ["Milk (x1)"]
    await todo_stack.call("update_batch", inventory_id="kitchen", batch_id=batch["id"], quantity=5)
    assert todo_stack.todo.summaries("todo.grocery") == []
    await todo_stack.call("update_batch", inventory_id="kitchen", batch_id=batch["id"], quantity=1)
    assert todo_stack.todo.summaries("todo.grocery") == ["Milk (x1)"]
    for service, extra in (("update_batch", {"quantity": 5}), ("remove_batch", {})):
        with pytest.raises(ServiceValidationError) as err:
            await todo_stack.call(service, inventory_id="kitchen", batch_id="nope", **extra)
        assert err.value.translation_key == "batch_not_found"
        assert todo_stack.todo.summaries("todo.grocery") == ["Milk (x1)"]
    await todo_stack.call("remove_batch", inventory_id="kitchen", batch_id=batch["id"])
    assert todo_stack.todo.summaries("todo.grocery") == ["Milk (x2)"]


async def test_total_value_uses_batch_prices(todo_stack: TodoStack) -> None:
    await todo_stack.call("add_item", inventory_id="kitchen", name="Milk", quantity=2, price=1)
    await todo_stack.call("increment_item", inventory_id="kitchen", name="Milk", amount=1, price=3)
    stats = await todo_stack.coordinators["kitchen"].async_get_inventory_statistics("kitchen")
    assert stats["total_value"] == 5  # 2 x 1 + 1 x 3, not 3 x last price


async def test_expiring_items_are_per_batch(todo_stack: TodoStack, freezer: Any) -> None:
    freezer.move_to("2026-10-25 12:00:00")
    await todo_stack.call(
        "add_item",
        inventory_id="kitchen",
        name="Milk",
        quantity=1,
        expiry_date="2026-10-24",
        expiry_alert_days=3,
        location="Fridge",
    )
    await todo_stack.call(
        "increment_item",
        inventory_id="kitchen",
        name="Milk",
        amount=2,
        expiry_date="2026-10-27",
        location="Garage",
    )
    await todo_stack.call(
        "increment_item", inventory_id="kitchen", name="Milk", amount=5, expiry_date="2026-12-01"
    )
    entries = await todo_stack.hub.async_items_expiring_soon("kitchen")
    assert [
        (e["quantity"], e["location"], e["days_until_expiry"], bool(e["batch_id"])) for e in entries
    ] == [(1, "Fridge", -1, True), (2, "Garage", 2, True)]
    assert all("batches" not in e for e in entries)
