"""InventoryHub: one cache for every reader, so a write through any coordinator is seen."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from homeassistant.config_entries import ConfigEntryDisabler
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (  # type: ignore[import-untyped]
    MockConfigEntry,
)

from custom_components.simple_inventory.const import DOMAIN
from custom_components.simple_inventory.coordinator import SimpleInventoryCoordinator
from custom_components.simple_inventory.data import get_hub
from custom_components.simple_inventory.hub import InventoryHub

from ..error_assertions import assert_translated_error
from ..harness import TodoStack, add_entry, integration_env, open_database, seed_items, setup_entry

LOW = {"auto_add_enabled": True, "auto_add_to_list_quantity": 1, "todo_list": "todo.grocery"}


@pytest.fixture
async def stack(todo_stack: TodoStack) -> TodoStack:
    """Kitchen (Milk) and Garage (Oil), each with one batch expiring in two days."""
    await todo_stack.add_inventory("garage", "Garage")
    soon = (dt_util.now().date() + timedelta(days=2)).isoformat()
    for inventory_id, name in (("kitchen", "Milk"), ("garage", "Oil")):
        await todo_stack.call(
            "add_item",
            inventory_id=inventory_id,
            name=name,
            quantity=2,
            expiry_date=soon,
            expiry_alert_days=7,
            **LOW,
        )
    return todo_stack


def _names(entries: list[dict]) -> list[str]:
    return sorted(str(entry["name"]) for entry in entries)


async def _reads(stack: TodoStack) -> dict[str, list[str]]:
    hub = stack.hub
    names = {"kitchen": "Kitchen", "garage": "Garage"}
    overview = await hub.async_overview(names)
    search = await hub.async_search("l", names, 50)
    return {
        "kitchen": _names(await hub.async_items_expiring_soon("kitchen")),
        "garage": _names(await hub.async_items_expiring_soon("garage")),
        "all": _names(await hub.async_items_expiring_soon(None)),
        "low": _names(await hub.async_low_stock_items(None)),
        "overview": _names(overview["expiring_soon"] + overview["low_stock"]),
        "search": [f"{item['name']}={item['quantity']}" for item in search["items"]],
    }


@pytest.mark.parametrize(
    ("writer", "inventory_id", "name"),
    [("kitchen", "kitchen", "Milk"), ("kitchen", "garage", "Oil"), ("garage", "kitchen", "Milk")],
)
async def test_write_through_any_coordinator_is_seen_by_every_hub_read(
    stack: TodoStack, writer: str, inventory_id: str, name: str
) -> None:
    before = await _reads(stack)
    assert before["all"] == ["Milk", "Oil"]
    assert before["low"] == []

    coordinator = stack.coordinators[writer]
    await coordinator.async_decrement_item(inventory_id, name=name, amount=2)
    after = await _reads(stack)

    # The item's only batch is consumed: no expiry entry, and it is now out of stock.
    other = "Oil" if name == "Milk" else "Milk"
    assert after["all"] == [other]
    assert after[inventory_id] == []
    assert after["kitchen" if inventory_id == "garage" else "garage"] == [other]
    assert after["low"] == [name]
    assert after["overview"] == [other]
    assert f"{name}=0.0" in after["search"]


async def test_the_hub_is_the_only_expiry_cache(stack: TodoStack) -> None:
    for coordinator in stack.coordinators.values():
        assert coordinator.hub is stack.hub
        assert not hasattr(coordinator, "_expiry_cache")
    assert not hasattr(SimpleInventoryCoordinator, "async_get_items_expiring_soon")


async def test_scan_without_inventory_is_resolved_by_the_hub(stack: TodoStack) -> None:
    await stack.call("update_item", inventory_id="garage", old_name="Oil", name="Oil", barcode="77")

    result = await stack.call("scan_barcode", barcode="77", action="increment", amount=1)
    lookup = await stack.call("scan_barcode", barcode="77", action="lookup")

    assert (result["inventory_id"], result["item_name"], result["success"]) == (
        "garage",
        "Oil",
        True,
    )
    assert lookup["item"]["inventory_name"] == "Garage"
    assert (await stack.item("garage", "Oil") or {})["quantity"] == 3.0


async def test_scan_without_inventory_reports_ambiguous_and_missing_barcodes(
    stack: TodoStack,
) -> None:
    await stack.call("update_item", inventory_id="garage", old_name="Oil", name="Oil", barcode="77")
    await stack.call(
        "update_item", inventory_id="kitchen", old_name="Milk", name="Milk", barcode="77"
    )

    with pytest.raises(ServiceValidationError) as err:
        await stack.call("scan_barcode", barcode="77", action="lookup")
    assert err.value.translation_key == "ambiguous_barcode"
    placeholders = err.value.translation_placeholders or {}
    assert sorted(placeholders["inventories"].split(", ")) == ["Garage", "Kitchen"]
    with pytest.raises(ServiceValidationError) as err:
        await stack.call("scan_barcode", barcode="404", action="lookup")
    assert_translated_error(err.value, "barcode_not_found", barcode="404")


async def test_scan_of_an_unloaded_inventory_item_is_refused(stack: TodoStack) -> None:
    await stack.call("update_item", inventory_id="garage", old_name="Oil", name="Oil", barcode="77")
    del stack.coordinators["garage"]

    with pytest.raises(ServiceValidationError) as err:
        await stack.call("scan_barcode", barcode="77", action="increment", amount=1)
    assert_translated_error(err.value, "inventory_not_loaded", inventory="Garage")


async def test_scan_lookup_of_an_unloaded_inventory_item_is_answered(stack: TodoStack) -> None:
    """A lookup is read-only, like lookup_by_barcode: it needs no loaded coordinator."""
    await stack.call("update_item", inventory_id="garage", old_name="Oil", name="Oil", barcode="77")
    del stack.coordinators["garage"]

    result = await stack.call("scan_barcode", barcode="77", action="lookup")

    assert (result["action"], result["inventory_id"]) == ("lookup", "garage")
    assert (result["item"]["name"], result["item"]["inventory_name"]) == ("Oil", "Garage")


# --- writes that bypass the coordinators (entry removal, orphan repair) ---------------


async def _seed_expiring(hass: HomeAssistant, inventory_id: str, name: str, item: str) -> None:
    soon = (dt_util.now().date() + timedelta(days=1)).isoformat()
    await seed_items(hass, inventory_id, name, [{"name": item, "expiry_alert_days": 7}])
    async with open_database(hass) as repository:
        await repository._connection().execute(
            "INSERT INTO item_batches (id, item_id, inventory_id, quantity, expiry_date,"
            " location_id, unit_price, purchased_at, created_at, updated_at)"
            " SELECT 'b_' || id, id, inventory_id, 1, ?, NULL, 0, 'x', 'x', 'x'"
            " FROM items WHERE name = ?",
            (soon, item),
        )
        await repository._connection().commit()


async def _expiring_everywhere(hub: InventoryHub) -> list[str]:
    return _names(await hub.async_items_expiring_soon(None))


async def test_removing_an_entry_refreshes_the_all_inventories_cache(
    hass: HomeAssistant, tmp_path: Path, enable_custom_integrations: None
) -> None:
    async with integration_env(hass, tmp_path) as env:
        await _seed_expiring(env, "kitchen", "Kitchen", "Milk")
        await _seed_expiring(env, "garage", "Garage", "Oil")
        kitchen = add_entry(env, "kitchen", "Kitchen")
        add_entry(env, "garage", "Garage")
        await setup_entry(env, kitchen)
        hub = get_hub(env)
        assert hub is not None
        assert await _expiring_everywhere(hub) == ["Milk", "Oil"]

        await env.config_entries.async_remove("garage")
        await env.async_block_till_done()

        assert get_hub(env) is hub
        assert await _expiring_everywhere(hub) == ["Milk"]


async def test_all_inventory_reads_cover_only_enabled_inventories(
    hass: HomeAssistant, tmp_path: Path, enable_custom_integrations: None
) -> None:
    """A disabled entry's data and a deleted entry's leftover data are never listed, as in
    search and the overview: voice counts and the global sensors agree with Home."""
    async with integration_env(hass, tmp_path) as env:
        for inventory_id, name, item in (
            ("kitchen", "Kitchen", "Milk"),
            ("attic", "Attic", "Oil"),
            ("ghost", "Old Garage", "Soap"),
        ):
            await _seed_expiring(env, inventory_id, name, item)
            async with open_database(env) as repository:
                connection = repository._connection()
                await connection.execute(
                    "UPDATE items SET auto_add_enabled = 1, auto_add_to_list_quantity = 2"
                    " WHERE name = ?",
                    (item,),
                )
                await connection.execute(
                    "INSERT INTO item_barcodes (item_id, inventory_id, barcode)"
                    " SELECT id, inventory_id, '4006381333931' FROM items WHERE name = ?",
                    (item,),
                )
                await connection.commit()
        kitchen = add_entry(env, "kitchen", "Kitchen")
        MockConfigEntry(
            domain=DOMAIN,
            entry_id="attic",
            title="Attic",
            data={"name": "Attic", "entry_type": "inventory"},
            disabled_by=ConfigEntryDisabler.USER,
        ).add_to_hass(env)
        await setup_entry(env, kitchen)
        hub = get_hub(env)
        assert hub is not None

        assert await _expiring_everywhere(hub) == ["Milk"]
        assert _names(await hub.async_low_stock_items(None)) == ["Milk"]
        assert [entry["name"] for entry in await hub.async_lookup_by_barcode("4006381333931")] == [
            "Milk"
        ]
        assert [
            inventory["inventory_id"] for inventory in await hub.async_items_by_inventory()
        ] == ["kitchen"]


# --- reads moved to the hub, through the real services ------------------------------


async def test_get_items_from_all_inventories_lists_every_inventory(stack: TodoStack) -> None:
    await stack.call("add_item", inventory_id="kitchen", name="apples")

    response = await stack.call("get_items_from_all_inventories")
    kitchen = await stack.coordinators["kitchen"].async_list_items("kitchen")
    garage = await stack.coordinators["garage"].async_list_items("garage")

    assert response == {
        "inventories": [
            {
                "inventory_id": "garage",
                "inventory_name": "Garage",
                "description": "",
                "items": garage,
            },
            {
                "inventory_id": "kitchen",
                "inventory_name": "Kitchen",
                "description": "",
                "items": sorted(kitchen, key=lambda item: item["name"].lower()),
            },
        ]
    }
    assert [item["name"] for item in response["inventories"][1]["items"]] == ["apples", "Milk"]


async def test_barcode_only_increment_and_remove_find_the_item_in_their_inventory(
    stack: TodoStack,
) -> None:
    """The per-inventory barcode lookup, not the global one, end to end."""
    await stack.call("update_item", inventory_id="garage", old_name="Oil", name="Oil", barcode="77")
    await stack.call(
        "update_item", inventory_id="kitchen", old_name="Milk", name="Milk", barcode="77"
    )

    await stack.call("increment_item", inventory_id="garage", barcode="77", amount=3)
    assert (await stack.item("garage", "Oil") or {})["quantity"] == 5.0
    assert (await stack.item("kitchen", "Milk") or {})["quantity"] == 2.0

    stack.todo.seed("todo.grocery", "Oil (x1)")
    await stack.call("remove_item", inventory_id="garage", barcode="77")

    assert await stack.item("garage", "Oil") is None
    assert await stack.item("kitchen", "Milk") is not None
    # Resolved before removal, so the removed item's todo entry went with it.
    assert "Oil (x1)" not in stack.todo.summaries("todo.grocery")
