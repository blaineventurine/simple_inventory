"""Coordinator overview: attention sections, precedence, reasons, sorting and summaries."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (  # type: ignore[import-untyped]
    MockConfigEntry,
)

from custom_components.simple_inventory.const import DOMAIN
from custom_components.simple_inventory.coordinator import SimpleInventoryCoordinator

from .harness import add_entry, integration_env, open_database, setup_entry

INVENTORIES = {"kitchen": "Kitchen", "garage": "Garage"}

# Today is frozen at 2026-06-15 (local).
_SEED = """
INSERT INTO inventories (id, name) VALUES ('orphan', 'Orphan');

INSERT INTO items (id, inventory_id, name, quantity, expiry_alert_days, auto_add_enabled,
                   auto_add_to_list_quantity, desired_quantity)
VALUES ('milk', 'kitchen', 'Milk', 4, 3, 1, 10, 0),
       ('yogurt', 'kitchen', 'Yogurt', 4, 7, 0, 0, 0),
       ('cheese', 'kitchen', 'Cheese', 1, 0, 0, 0, 0),
       ('eggs', 'kitchen', 'Eggs', 0, 0, 1, 0, 0),
       ('k_flour', 'kitchen', 'Flour', 0, 0, 0, 0, 0),
       ('rice', 'kitchen', 'Rice', 1, 0, 1, 2, 5),
       ('sugar', 'kitchen', 'Sugar', 1, 0, 0, 1, 0),
       ('pasta', 'kitchen', 'Pasta', 3, 0, 1, 0, 0),
       ('powder', 'garage', 'milk powder', 1, 3, 0, 0, 0),
       ('bread', 'garage', 'Bread', 1, 3, 0, 0, 0),
       ('g_flour', 'garage', 'Flour', 0, 0, 0, 0, 0),
       ('batteries', 'garage', 'Batteries', 1, 0, 0, 3, 0),
       ('ancient', 'orphan', 'Ancient', 1, 3, 0, 0, 0),
       ('zero', 'orphan', 'Zero', 0, 0, 0, 0, 0);

INSERT INTO item_batches (id, item_id, inventory_id, quantity, expiry_date, location_id,
                          unit_price, purchased_at, created_at, updated_at)
VALUES ('m1', 'milk', 'kitchen', 1, '2026-06-10', NULL, 1.0, 'x', 'x', 'x'),
       ('m2', 'milk', 'kitchen', 2, '2026-06-13', NULL, 0, 'x', 'x', 'x'),
       ('m3', 'milk', 'kitchen', 1, '2026-06-30', NULL, 0, 'x', 'x', 'x'),
       ('y1', 'yogurt', 'kitchen', 1, '2026-06-17', NULL, 0, 'x', 'x', 'x'),
       ('y2', 'yogurt', 'kitchen', 2, '2026-06-20', NULL, 0, 'x', 'x', 'x'),
       ('y3', 'yogurt', 'kitchen', 1, '2026-06-25', NULL, 0, 'x', 'x', 'x'),
       ('c1', 'cheese', 'kitchen', 1, '2026-06-16', NULL, 0, 'x', 'x', 'x'),
       ('r1', 'rice', 'kitchen', 1, '', NULL, 2.5, 'x', 'x', 'x'),
       ('s1', 'sugar', 'kitchen', 1, '', NULL, 0, 'x', 'x', 'x'),
       ('p1', 'pasta', 'kitchen', 3, '', NULL, 0, 'x', 'x', 'x'),
       ('w1', 'powder', 'garage', 1, '2026-06-10', NULL, 0, 'x', 'x', 'x'),
       ('br1', 'bread', 'garage', 1, '2026-06-17', NULL, 0, 'x', 'x', 'x'),
       ('ba1', 'batteries', 'garage', 1, '', NULL, 0, 'x', 'x', 'x'),
       ('a1', 'ancient', 'orphan', 1, '2026-01-01', NULL, 0, 'x', 'x', 'x');
"""


@pytest.fixture
async def coordinator(
    hass: HomeAssistant, tmp_path: Path, enable_custom_integrations: None
) -> AsyncGenerator[SimpleInventoryCoordinator, None]:
    async with integration_env(hass, tmp_path) as hass_env:
        async with open_database(hass_env) as repository:
            await repository.upsert_inventory("kitchen", "Kitchen", entry_type="inventory")
            await repository.upsert_inventory("garage", "Garage", entry_type="inventory")
            conn = repository._connection()
            await conn.executescript(_SEED)
            await conn.commit()
        kitchen = MockConfigEntry(
            domain=DOMAIN,
            entry_id="kitchen",
            title="Kitchen",
            data={"name": "Kitchen", "entry_type": "inventory", "icon": "mdi:fridge"},
        )
        kitchen.add_to_hass(hass_env)
        add_entry(hass_env, "garage", "Garage")
        await setup_entry(hass_env, kitchen)
        today = datetime(2026, 6, 15, 12, 0, tzinfo=dt_util.get_default_time_zone())
        with patch(
            "custom_components.simple_inventory.hub.dt_util.now",
            return_value=today,
        ):
            yield hass_env.data[DOMAIN].coordinators["kitchen"]


async def _listed(coordinator: SimpleInventoryCoordinator) -> dict[str, dict[str, Any]]:
    items: dict[str, dict[str, Any]] = {}
    for inventory_id in INVENTORIES:
        items.update(
            {item["id"]: item for item in await coordinator.async_list_items(inventory_id)}
        )
    return items


def _ids(section: list[dict[str, Any]]) -> list[str]:
    return [entry["id"] for entry in section]


async def test_sections_precedence_and_sort_order(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    overview = await coordinator.hub.async_overview(INVENTORIES)

    # Milk is expired and below threshold: listed only as expired. Eggs (0, auto-add with
    # threshold 0) only as out of stock. Ties sort by name, then inventory name.
    assert _ids(overview["expired"]) == ["milk", "powder"]
    assert _ids(overview["expiring_soon"]) == ["bread", "yogurt"]
    assert _ids(overview["out_of_stock"]) == ["eggs", "g_flour", "k_flour"]
    assert _ids(overview["low_stock"]) == ["batteries", "rice", "sugar"]


async def test_expired_sorts_most_overdue_first(coordinator: SimpleInventoryCoordinator) -> None:
    conn = coordinator.repository._connection()
    await conn.execute("UPDATE item_batches SET expiry_date = '2026-06-01' WHERE id = 'w1'")
    await conn.commit()

    overview = await coordinator.hub.async_overview(INVENTORIES)

    assert _ids(overview["expired"]) == ["powder", "milk"]
    assert overview["expired"][0]["reason"]["days_overdue"] == 14


async def test_expiring_sorts_soonest_first(coordinator: SimpleInventoryCoordinator) -> None:
    conn = coordinator.repository._connection()
    await conn.execute("UPDATE item_batches SET expiry_date = '2026-06-18' WHERE id = 'br1'")
    await conn.commit()

    overview = await coordinator.hub.async_overview(INVENTORIES)

    assert _ids(overview["expiring_soon"]) == ["yogurt", "bread"]


async def test_expiry_reasons_count_batches_in_their_state(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    overview = await coordinator.hub.async_overview(INVENTORIES)
    reasons = {entry["id"]: entry["reason"] for entry in overview["expired"]}
    reasons.update({entry["id"]: entry["reason"] for entry in overview["expiring_soon"]})

    # Milk: m1 5 days and m2 2 days overdue; m3 (in 15 days) is outside its 3-day window.
    assert reasons["milk"] == {"days_overdue": 5, "batches": 2, "quantity": 3.0}
    # Yogurt: y1 in 2 days and y2 in 5 days are in its 7-day window; y3 (10 days) is not.
    assert reasons["yogurt"] == {"days_until_expiry": 2, "batches": 2, "quantity": 3.0}
    assert reasons["bread"] == {"days_until_expiry": 2, "batches": 1, "quantity": 1.0}


async def test_each_item_uses_its_own_alert_window(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    overview = await coordinator.hub.async_overview(INVENTORIES)

    # Cheese expires tomorrow but alerts 0 days ahead; Bread (window 3) is listed.
    listed = {
        entry["id"] for section in ("expired", "expiring_soon") for entry in overview[section]
    }
    assert "cheese" not in listed
    assert "bread" in listed


async def test_low_stock_reasons(coordinator: SimpleInventoryCoordinator) -> None:
    overview = await coordinator.hub.async_overview(INVENTORIES)
    reasons = {entry["id"]: entry["reason"] for entry in overview["low_stock"]}

    assert reasons == {
        # desired 5 - quantity 1
        "rice": {"threshold": 2.0, "quantity_needed": 4.0},
        # no desired: threshold 1 - quantity 1 + 1
        "sugar": {"threshold": 1.0, "quantity_needed": 1.0},
        "batteries": {"threshold": 3.0, "quantity_needed": 3.0},
    }
    assert all(entry["reason"] == {} for entry in overview["out_of_stock"])
    # Pasta: auto-add with threshold 0 but in stock, so not low.
    assert "pasta" not in _ids(overview["low_stock"])


async def test_entries_are_list_items_dicts_plus_extras(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    overview = await coordinator.hub.async_overview(INVENTORIES)
    listed = await _listed(coordinator)
    names = {"milk": "Kitchen", "powder": "Garage", "eggs": "Kitchen", "batteries": "Garage"}
    entries = {
        entry["id"]: entry
        for section in ("expired", "expiring_soon", "out_of_stock", "low_stock")
        for entry in overview[section]
    }

    for item_id, inventory_name in names.items():
        entry = dict(entries[item_id])
        assert entry.pop("inventory_name") == inventory_name
        entry.pop("reason")
        assert entry == listed[item_id]


async def test_summaries(coordinator: SimpleInventoryCoordinator) -> None:
    overview = await coordinator.hub.async_overview(INVENTORIES)
    kitchen_stats = await coordinator.async_get_inventory_statistics("kitchen")

    assert overview["inventories"] == [
        {
            "id": "garage",
            "name": "Garage",
            "icon": "",
            "total_items": 4,
            "total_value": 0,
            "attention": {"expired": 1, "expiring_soon": 1, "out_of_stock": 1, "low_stock": 1},
        },
        {
            "id": "kitchen",
            "name": "Kitchen",
            "icon": "mdi:fridge",
            "total_items": 8,
            "total_value": 3.5,
            # Milk counts once (expired), Eggs once (out of stock).
            "attention": {"expired": 1, "expiring_soon": 1, "out_of_stock": 2, "low_stock": 2},
        },
    ]
    assert kitchen_stats["total_items"] == 8
    assert kitchen_stats["total_value"] == 3.5


async def test_unlisted_inventories_are_excluded(coordinator: SimpleInventoryCoordinator) -> None:
    overview = await coordinator.hub.async_overview({"garage": "Garage"})

    assert [summary["id"] for summary in overview["inventories"]] == ["garage"]
    entries = [
        entry
        for section in ("expired", "expiring_soon", "out_of_stock", "low_stock")
        for entry in overview[section]
    ]
    assert {entry["inventory_id"] for entry in entries} == {"garage"}
    assert "ancient" not in _ids(entries)
    assert "zero" not in _ids(entries)


async def test_nothing_to_report(coordinator: SimpleInventoryCoordinator) -> None:
    assert await coordinator.hub.async_overview({}) == {
        "inventories": [],
        "expired": [],
        "expiring_soon": [],
        "out_of_stock": [],
        "low_stock": [],
    }


async def test_write_through_another_coordinator_is_seen_at_once(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    garage: SimpleInventoryCoordinator = coordinator.hass.data[DOMAIN].coordinators["garage"]
    before = await coordinator.hub.async_overview(INVENTORIES)
    assert "bread" in _ids(before["expiring_soon"])

    assert await garage.async_decrement_item("garage", "Bread", 1)
    after = await coordinator.hub.async_overview(INVENTORIES)

    assert "bread" in _ids(after["out_of_stock"])
    assert "bread" not in _ids(after["expiring_soon"])
