"""End-to-end todo sync regressions: real services + coordinator + SQLite + TodoManager."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import voluptuous as vol
from homeassistant.core import Event, HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import (  # type: ignore[import-untyped]
    MockConfigEntry,
)

from custom_components.simple_inventory.const import (
    DOMAIN,
    EVENT_ITEM_ADDED_TO_LIST,
    EVENT_ITEM_REMOVED_FROM_LIST,
)

from ..harness import TodoStack

AUTO_ADD = {
    "auto_add_enabled": True,
    "auto_add_to_list_quantity": 2,
    "todo_list": "todo.grocery",
}


def _capture(hass: HomeAssistant, event_type: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    @callback
    def _listener(event: Event) -> None:
        events.append(dict(event.data))

    hass.bus.async_listen(event_type, _listener)
    return events


async def _add_milk(stack: TodoStack, **overrides: Any) -> None:
    data: dict[str, Any] = {"inventory_id": "kitchen", "name": "Milk", "quantity": 1, **AUTO_ADD}
    data.update(overrides)
    await stack.call("add_item", **data)


# --- item 1: errors propagate, whitespace names rejected, cleaned-name lookup ----------


@pytest.mark.parametrize("service", ["add_item", "update_item"])
async def test_whitespace_only_name_is_rejected(todo_stack: TodoStack, service: str) -> None:
    await _add_milk(todo_stack)
    data: dict[str, Any] = {"inventory_id": "kitchen", "name": "   ", "quantity": 9}
    if service == "update_item":
        data["old_name"] = "Milk"

    with pytest.raises(vol.Invalid):
        await todo_stack.call(service, **data)

    item = await todo_stack.item("kitchen", "Milk")
    assert item is not None and item["quantity"] == 1


async def test_unexpected_coordinator_error_propagates(todo_stack: TodoStack) -> None:
    await _add_milk(todo_stack, quantity=5)
    coordinator = todo_stack.coordinators["kitchen"]

    with (
        patch.object(
            coordinator,
            "async_decrement_item",
            AsyncMock(side_effect=RuntimeError("database is locked")),
        ),
        pytest.raises(RuntimeError, match="database is locked"),
    ):
        await todo_stack.call("decrement_item", inventory_id="kitchen", name="Milk")


async def test_padded_name_still_syncs_todo(todo_stack: TodoStack) -> None:
    await todo_stack.call(
        "add_item", inventory_id="kitchen", name="  Milk  ", quantity=1, **AUTO_ADD
    )

    assert todo_stack.todo.summaries("todo.grocery") == ["Milk (x2)"]


async def test_padded_name_syncs_todo_without_schema(todo_stack: TodoStack) -> None:
    """Direct handler calls (no schema) still look the item up by its cleaned name."""
    call = ServiceCall(
        todo_stack.hass,
        DOMAIN,
        "add_item",
        {"inventory_id": "kitchen", "name": " Milk ", "quantity": 1, **AUTO_ADD},
    )
    await todo_stack.handler.async_add_item(call)

    assert todo_stack.todo.summaries("todo.grocery") == ["Milk (x2)"]


# --- item 2: remove_item removes the entry --------------------------------------------


async def test_remove_item_removes_todo_entry_legacy_mode(todo_stack: TodoStack) -> None:
    await _add_milk(todo_stack)
    assert todo_stack.todo.summaries("todo.grocery") == ["Milk (x2)"]
    added = _capture(todo_stack.hass, EVENT_ITEM_ADDED_TO_LIST)
    removed = _capture(todo_stack.hass, EVENT_ITEM_REMOVED_FROM_LIST)

    await todo_stack.call("remove_item", inventory_id="kitchen", name="Milk")
    await todo_stack.hass.async_block_till_done()

    assert todo_stack.todo.summaries("todo.grocery") == []
    assert added == []
    assert [e["item_name"] for e in removed] == ["Milk"]


async def test_remove_item_removes_todo_entry_desired_mode(todo_stack: TodoStack) -> None:
    await _add_milk(todo_stack, name="Eggs", desired_quantity=12)
    assert todo_stack.todo.summaries("todo.grocery") == ["Eggs (x12)"]

    await todo_stack.call("remove_item", inventory_id="kitchen", name="Eggs")

    assert todo_stack.todo.summaries("todo.grocery") == []


# --- item 3: rename / todo_list change --------------------------------------------------


async def test_rename_replaces_todo_entry(todo_stack: TodoStack) -> None:
    await _add_milk(todo_stack)

    await todo_stack.call("update_item", inventory_id="kitchen", old_name="Milk", name="Whole Milk")

    assert todo_stack.todo.summaries("todo.grocery") == ["Whole Milk (x2)"]


async def test_todo_list_change_moves_entry(todo_stack: TodoStack) -> None:
    await _add_milk(todo_stack)

    await todo_stack.call(
        "update_item", inventory_id="kitchen", old_name="Milk", name="Milk", todo_list="todo.other"
    )

    assert todo_stack.todo.summaries("todo.grocery") == []
    assert todo_stack.todo.summaries("todo.other") == ["Milk (x2)"]


# --- item 4: user descriptions are preserved ---------------------------------------------


async def test_refresh_does_not_clobber_user_description(todo_stack: TodoStack) -> None:
    await _add_milk(todo_stack)
    entry = todo_stack.todo.lists["todo.grocery"][0]
    assert "description" not in entry
    entry["description"] = "get the organic one"

    await todo_stack.call("decrement_item", inventory_id="kitchen", name="Milk")

    entry = todo_stack.todo.lists["todo.grocery"][0]
    assert entry["summary"] == "Milk (x3)"
    assert entry["description"] == "get the organic one"
    assert all("description" not in data for _, data in todo_stack.todo.calls if _ != "get_items")


async def test_description_placement_still_writes_description(todo_stack: TodoStack) -> None:
    await _add_milk(todo_stack, todo_quantity_placement="description")

    entry = todo_stack.todo.lists["todo.grocery"][0]
    assert entry["summary"] == "Milk"
    assert entry["description"] == "(x2)"


# --- item 5: desired_quantity change refreshes the entry -----------------------------------


async def test_desired_change_refreshes_entry_below_threshold(todo_stack: TodoStack) -> None:
    await _add_milk(todo_stack, name="Eggs", desired_quantity=12)
    assert todo_stack.todo.summaries("todo.grocery") == ["Eggs (x12)"]

    await todo_stack.call(
        "update_item", inventory_id="kitchen", old_name="Eggs", name="Eggs", desired_quantity=6
    )

    assert todo_stack.todo.summaries("todo.grocery") == ["Eggs (x6)"]


async def test_desired_change_refreshes_entry_above_threshold(todo_stack: TodoStack) -> None:
    await _add_milk(todo_stack, name="Eggs", desired_quantity=12)
    await todo_stack.call("increment_item", inventory_id="kitchen", name="Eggs", amount=2)
    assert todo_stack.todo.summaries("todo.grocery") == ["Eggs (x12)"]

    await todo_stack.call(
        "update_item", inventory_id="kitchen", old_name="Eggs", name="Eggs", desired_quantity=6
    )

    assert todo_stack.todo.summaries("todo.grocery") == ["Eggs (x6)"]


async def test_unchanged_entry_is_not_rewritten(todo_stack: TodoStack) -> None:
    await _add_milk(todo_stack, name="Eggs", desired_quantity=12)
    todo_stack.todo.calls.clear()
    added = _capture(todo_stack.hass, EVENT_ITEM_ADDED_TO_LIST)

    await todo_stack.call("decrement_item", inventory_id="kitchen", name="Eggs", amount=0.5)
    await todo_stack.hass.async_block_till_done()

    assert [name for name, _ in todo_stack.todo.calls] == ["get_items"]
    assert added == []


# --- item 6: disabling auto-add removes the entry ---------------------------------------


async def test_disabling_auto_add_removes_entry(todo_stack: TodoStack) -> None:
    await _add_milk(todo_stack)

    await todo_stack.call(
        "update_item",
        inventory_id="kitchen",
        old_name="Milk",
        name="Milk",
        auto_add_enabled=False,
    )

    assert todo_stack.todo.summaries("todo.grocery") == []


# --- item 7: todo_list validation / missing entity ---------------------------------------


@pytest.mark.parametrize("todo_list", ["light.kitchen", "not an entity", "todo"])
async def test_todo_list_must_be_todo_entity(todo_stack: TodoStack, todo_list: str) -> None:
    with pytest.raises(vol.Invalid):
        await _add_milk(todo_stack, todo_list=todo_list)
    assert await todo_stack.item("kitchen", "Milk") is None


async def test_missing_todo_entity_fires_no_added_event(todo_stack: TodoStack) -> None:
    added = _capture(todo_stack.hass, EVENT_ITEM_ADDED_TO_LIST)

    await _add_milk(todo_stack, todo_list="todo.nope")
    await todo_stack.hass.async_block_till_done()

    assert added == []
    assert not [c for c in todo_stack.todo.calls if c[0] == "add_item"]


# --- item 8: remove_item matches exact name or alias only -------------------------------


async def test_remove_item_does_not_fuzzy_match(todo_stack: TodoStack) -> None:
    await todo_stack.call("add_item", inventory_id="kitchen", name="Almond Milk", quantity=1)

    with pytest.raises(ServiceValidationError):
        await todo_stack.call("remove_item", inventory_id="kitchen", name="Milk")

    assert await todo_stack.item("kitchen", "Almond Milk") is not None


async def test_remove_item_by_alias_and_case(todo_stack: TodoStack) -> None:
    await todo_stack.call(
        "add_item", inventory_id="kitchen", name="Oatmeal", quantity=1, aliases="oats"
    )
    await todo_stack.call("add_item", inventory_id="kitchen", name="Rice", quantity=1)

    await todo_stack.call("remove_item", inventory_id="kitchen", name="OATS")
    await todo_stack.call("remove_item", inventory_id="kitchen", name="rice")

    assert await todo_stack.item("kitchen", "Oatmeal") is None
    assert await todo_stack.item("kitchen", "Rice") is None


async def test_decrement_still_fuzzy_matches(todo_stack: TodoStack) -> None:
    await todo_stack.call("add_item", inventory_id="kitchen", name="Soda Water", quantity=5)

    await todo_stack.call("decrement_item", inventory_id="kitchen", name="Soda", amount=2)

    item = await todo_stack.item("kitchen", "Soda Water")
    assert item is not None and item["quantity"] == 3


# --- item 9: same-named items in different inventories on one list ----------------------


async def test_same_name_in_two_inventories_keeps_separate_entries(
    todo_stack: TodoStack,
) -> None:
    await todo_stack.add_inventory("garage", "Garage")
    for inventory_id in ("kitchen", "garage"):
        await todo_stack.call(
            "add_item",
            inventory_id=inventory_id,
            name="Batteries",
            quantity=1,
            auto_add_id_to_description_enabled=True,
            **AUTO_ADD,
        )

    entries = todo_stack.todo.lists["todo.grocery"]
    assert sorted(e["description"] for e in entries) == ["(garage)", "(kitchen)"]

    await todo_stack.call("increment_item", inventory_id="garage", name="Batteries", amount=5)

    entries = todo_stack.todo.lists["todo.grocery"]
    assert [(e["summary"], e["description"]) for e in entries] == [("Batteries (x2)", "(kitchen)")]


# --- item 10: get_items resolves inventory names like other services ---------------------


async def test_get_items_uses_fuzzy_inventory_resolution(todo_stack: TodoStack) -> None:
    await todo_stack.call("add_item", inventory_id="kitchen", name="Milk", quantity=1)

    result = await todo_stack.call("get_items", inventory_name="kitch")

    assert [item["name"] for item in result["items"]] == ["Milk"]


async def test_get_items_does_not_target_global_entry(todo_stack: TodoStack) -> None:
    MockConfigEntry(
        domain=DOMAIN,
        entry_id="global",
        data={"name": "All Inventories", "entry_type": "global"},
    ).add_to_hass(todo_stack.hass)

    with pytest.raises(ServiceValidationError):
        await todo_stack.call("get_items", inventory_name="All Inventories")


# --- item 12 (C9): one refresh signal per change --------------------------------------


async def test_service_change_signals_refresh_once(todo_stack: TodoStack) -> None:
    await _add_milk(todo_stack, quantity=5)
    scoped = _capture(todo_stack.hass, f"{DOMAIN}_updated_kitchen")
    general = _capture(todo_stack.hass, f"{DOMAIN}_updated")

    await todo_stack.call("increment_item", inventory_id="kitchen", name="Milk")
    await todo_stack.hass.async_block_till_done()

    assert len(scoped) == 1
    assert len(general) == 1


@pytest.mark.parametrize(
    ("field", "conflict"),
    [("barcode", {"barcode": "222"}), ("aliases", {"aliases": "loaf"})],
)
async def test_update_with_relation_conflict_writes_nothing(
    todo_stack: TodoStack, field: str, conflict: dict[str, str]
) -> None:
    """A conflicting barcode/alias rejects the whole edit: no rename, no quantity change,
    no location change -- so the card's still-open modal can retry with the same old_name."""
    await todo_stack.call(
        "add_item", inventory_id="kitchen", name="Bread", quantity=1, barcode="222", aliases="loaf"
    )
    await todo_stack.call(
        "add_item", inventory_id="kitchen", name="Milk", quantity=2, location="Fridge"
    )

    with pytest.raises(ServiceValidationError):
        await todo_stack.call(
            "update_item",
            inventory_id="kitchen",
            old_name="Milk",
            name="Whole Milk",
            quantity=7,
            location="Garage",
            **conflict,
        )

    assert await todo_stack.item("kitchen", "Whole Milk") is None
    milk = next(
        it
        for it in await todo_stack.repo.list_items_with_details("kitchen")
        if it["name"] == "Milk"
    )
    assert milk["quantity"] == 2
    assert milk["locations"] == ["Fridge"]


# --- E6: every change syncs from the item's state, whatever its direction ----------------


async def test_increment_still_below_threshold_restores_missing_entry(
    todo_stack: TodoStack,
) -> None:
    """An entry deleted from the list comes back when the item is still low after a restock."""
    await _add_milk(todo_stack, quantity=0)
    todo_stack.todo.lists["todo.grocery"].clear()

    await todo_stack.call("increment_item", inventory_id="kitchen", name="Milk", amount=1)

    assert todo_stack.todo.summaries("todo.grocery") == ["Milk (x2)"]


async def test_decrement_above_threshold_clears_leftover_entry(todo_stack: TodoStack) -> None:
    """A stocked item's entry left behind (e.g. the list was offline) goes on the next change."""
    await _add_milk(todo_stack, quantity=6)
    todo_stack.todo.seed("todo.grocery", "Milk (x2)")

    await todo_stack.call("decrement_item", inventory_id="kitchen", name="Milk", amount=1)

    assert todo_stack.todo.summaries("todo.grocery") == []


async def test_import_adds_low_new_item_to_list(todo_stack: TodoStack) -> None:
    coordinator = todo_stack.coordinators["kitchen"]

    await coordinator.async_import_inventory(
        "kitchen", [{"name": "Milk", "quantity": 1, **AUTO_ADD}], "json"
    )

    assert todo_stack.todo.summaries("todo.grocery") == ["Milk (x2)"]


async def test_import_merged_restock_removes_entry(todo_stack: TodoStack) -> None:
    await _add_milk(todo_stack)
    assert todo_stack.todo.summaries("todo.grocery") == ["Milk (x2)"]
    coordinator = todo_stack.coordinators["kitchen"]

    await coordinator.async_import_inventory(
        "kitchen", [{"name": "Milk", "quantity": 5}], "json", "merge_quantities"
    )

    assert todo_stack.todo.summaries("todo.grocery") == []


async def test_import_overwrite_moves_entry_to_new_list(todo_stack: TodoStack) -> None:
    await _add_milk(todo_stack)
    coordinator = todo_stack.coordinators["kitchen"]

    await coordinator.async_import_inventory(
        "kitchen", [{"name": "Milk", "todo_list": "todo.other"}], "json", "overwrite"
    )

    assert todo_stack.todo.summaries("todo.grocery") == []
    assert todo_stack.todo.summaries("todo.other") == ["Milk (x2)"]


async def test_import_skipped_record_leaves_list_alone(todo_stack: TodoStack) -> None:
    await _add_milk(todo_stack)
    todo_stack.todo.lists["todo.grocery"].clear()
    todo_stack.todo.calls.clear()
    coordinator = todo_stack.coordinators["kitchen"]

    await coordinator.async_import_inventory("kitchen", [{"name": "Milk", "quantity": 9}], "json")

    assert todo_stack.todo.calls == []


# --- desired_quantity at or below the threshold: reaching it restocks the item ----------


async def test_increment_to_desired_at_threshold_removes_entry(todo_stack: TodoStack) -> None:
    await _add_milk(todo_stack, desired_quantity=2)
    assert todo_stack.todo.summaries("todo.grocery") == ["Milk (x2)"]

    await todo_stack.call("increment_item", inventory_id="kitchen", name="Milk", amount=1)

    assert todo_stack.todo.summaries("todo.grocery") == []


async def test_update_to_desired_at_threshold_removes_entry(todo_stack: TodoStack) -> None:
    await _add_milk(todo_stack, desired_quantity=2)

    await todo_stack.call(
        "update_item", inventory_id="kitchen", old_name="Milk", name="Milk", quantity=2
    )

    assert todo_stack.todo.summaries("todo.grocery") == []


async def test_add_at_desired_at_threshold_stays_off_list(todo_stack: TodoStack) -> None:
    await _add_milk(todo_stack, quantity=2, desired_quantity=2)

    assert todo_stack.todo.summaries("todo.grocery") == []


# --- a todo list that cannot be read is never synced blind --------------------------


@pytest.mark.parametrize(
    ("quantity_after", "seeded"),
    [(0, False), (1, True), (9, True)],
    ids=["would-add", "would-refresh", "would-remove"],
)
async def test_unreadable_list_skips_the_sync(
    todo_stack: TodoStack, caplog: pytest.LogCaptureFixture, quantity_after: float, seeded: bool
) -> None:
    await _add_milk(todo_stack, quantity=5)
    if seeded:
        todo_stack.todo.seed("todo.grocery", "Milk (x9)")
    todo_stack.todo.unreadable.add("todo.grocery")
    todo_stack.todo.calls.clear()

    await todo_stack.call(
        "update_item", inventory_id="kitchen", old_name="Milk", name="Milk", quantity=quantity_after
    )

    assert [name for name, _ in todo_stack.todo.calls] == ["get_items"]
    assert _warnings(caplog) == [
        "Todo list todo.grocery could not be read; not syncing Milk"
        " (retried on the item's next change)"
    ]


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.levelname == "WARNING"]


async def test_unreadable_list_on_rename_warns_once_per_skipped_sync(
    todo_stack: TodoStack, caplog: pytest.LogCaptureFixture
) -> None:
    """The old entry's removal is not retried later, and the warning says so."""
    await _add_milk(todo_stack)
    assert todo_stack.todo.summaries("todo.grocery") == ["Milk (x2)"]
    todo_stack.todo.unreadable.add("todo.grocery")
    caplog.clear()

    await todo_stack.call("update_item", inventory_id="kitchen", old_name="Milk", name="Oat milk")

    assert todo_stack.todo.summaries("todo.grocery") == ["Milk (x2)"]
    assert _warnings(caplog) == [
        "Todo list todo.grocery could not be read; the entry for Milk was not removed"
        " and will not be retried (remove it from the list by hand)",
        "Todo list todo.grocery could not be read; not syncing Oat milk"
        " (retried on the item's next change)",
    ]


async def test_unreadable_list_is_synced_on_the_next_change(todo_stack: TodoStack) -> None:
    await _add_milk(todo_stack, quantity=5)
    todo_stack.todo.unreadable.add("todo.grocery")
    await todo_stack.call("decrement_item", inventory_id="kitchen", name="Milk", amount=4)
    assert todo_stack.todo.summaries("todo.grocery") == []

    todo_stack.todo.unreadable.clear()
    await todo_stack.call("decrement_item", inventory_id="kitchen", name="Milk", amount=0.5)

    assert todo_stack.todo.summaries("todo.grocery") == ["Milk (x2.5)"]


async def test_readable_empty_list_still_gets_the_entry(todo_stack: TodoStack) -> None:
    await _add_milk(todo_stack, quantity=5)

    await todo_stack.call("decrement_item", inventory_id="kitchen", name="Milk", amount=4)

    assert todo_stack.todo.summaries("todo.grocery") == ["Milk (x2)"]
