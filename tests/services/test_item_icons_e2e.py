"""Item icons end to end: services -> coordinator -> SQLite -> list_items/get_items/get_item."""

from __future__ import annotations

from typing import Any

import pytest
import voluptuous as vol

from custom_components.simple_inventory.const import FIELD_ICON, FIELD_UNIT

from ..harness import TodoStack


async def _listed(stack: TodoStack, name: str) -> dict[str, Any]:
    items = await stack.coordinators["kitchen"].async_list_items("kitchen")
    [item] = [i for i in items if i["name"] == name]
    return item


async def test_add_item_icon_reaches_every_item_payload(todo_stack: TodoStack) -> None:
    await todo_stack.call(
        "add_item", inventory_id="kitchen", name="Milk", quantity=1, icon="mdi:cup"
    )

    assert (await _listed(todo_stack, "Milk"))[FIELD_ICON] == "mdi:cup"
    response = await todo_stack.call("get_items", inventory_id="kitchen")
    assert [item[FIELD_ICON] for item in response["items"]] == ["mdi:cup"]
    detail = await todo_stack.coordinators["kitchen"].async_get_item("kitchen", "milk")
    assert detail is not None and detail[FIELD_ICON] == "mdi:cup"


async def test_add_item_without_icon_stores_empty_icon(todo_stack: TodoStack) -> None:
    await todo_stack.call("add_item", inventory_id="kitchen", name="Rice")

    assert (await _listed(todo_stack, "Rice"))[FIELD_ICON] == ""


async def test_update_item_changes_keeps_and_clears_icon(todo_stack: TodoStack) -> None:
    await todo_stack.call("add_item", inventory_id="kitchen", name="Milk", icon="mdi:cup")

    await todo_stack.call(
        "update_item", inventory_id="kitchen", old_name="Milk", name="Milk", icon="mdi:bottle-tonic"
    )
    assert (await _listed(todo_stack, "Milk"))[FIELD_ICON] == "mdi:bottle-tonic"

    # An update without `icon` leaves it untouched.
    await todo_stack.call(
        "update_item", inventory_id="kitchen", old_name="Milk", name="Whole Milk", unit="L"
    )
    renamed = await _listed(todo_stack, "Whole Milk")
    assert (renamed[FIELD_ICON], renamed[FIELD_UNIT]) == ("mdi:bottle-tonic", "L")

    await todo_stack.call(
        "update_item", inventory_id="kitchen", old_name="Whole Milk", name="Whole Milk", icon=""
    )
    assert (await _listed(todo_stack, "Whole Milk"))[FIELD_ICON] == ""


async def test_invalid_icon_is_rejected_before_anything_is_written(
    todo_stack: TodoStack,
) -> None:
    with pytest.raises(vol.Invalid):
        await todo_stack.call("add_item", inventory_id="kitchen", name="Milk", icon="cup")
    assert await todo_stack.item("kitchen", "Milk") is None

    await todo_stack.call("add_item", inventory_id="kitchen", name="Milk", icon="mdi:cup")
    with pytest.raises(vol.Invalid):
        await todo_stack.call(
            "update_item", inventory_id="kitchen", old_name="Milk", name="Milk", icon="cup"
        )
    assert (await _listed(todo_stack, "Milk"))[FIELD_ICON] == "mdi:cup"
