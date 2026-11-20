"""Batch storage: schema v4, migration, D3/D4/D7 primitives."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import aiosqlite
import pytest
from homeassistant.core import HomeAssistant

from custom_components.simple_inventory.const import (
    FIELD_EXPIRY_DATE,
    FIELD_NAME,
    FIELD_QUANTITY,
    INVENTORY_ITEMS,
    INVENTORY_NAME,
)
from custom_components.simple_inventory.storage._batches import InsufficientStockError
from custom_components.simple_inventory.storage.repository import (
    SCHEMA_VERSION,
    InventoryRepository,
)


@pytest.fixture
async def repo(hass_with_tmp_config: HomeAssistant) -> AsyncGenerator[InventoryRepository, None]:
    repository = InventoryRepository(hass_with_tmp_config, db_filename="batches.db")
    await repository.async_initialize()
    await repository.upsert_inventory("inv", "Kitchen")
    try:
        yield repository
    finally:
        await repository.async_close()


async def test_schema_version_is_6(repo: InventoryRepository) -> None:
    assert SCHEMA_VERSION == 6
    assert await repo.get_metadata_value("schema_version") == "6"


async def test_v3_database_migrates_one_batch_per_stocked_item(
    hass_with_tmp_config: HomeAssistant,
) -> None:
    path = Path(hass_with_tmp_config.config.path("v3.db"))
    repo = InventoryRepository(hass_with_tmp_config, db_filename="v3.db")
    await repo.async_initialize()
    await repo.upsert_inventory("inv", "Kitchen")
    await repo.async_close()

    # Recreate a v3 database: items carry quantity/expiry directly, no batch table.
    async with aiosqlite.connect(path) as db:
        await db.execute("DROP TABLE item_batches")
        await db.execute("UPDATE metadata SET value = '3' WHERE key = 'schema_version'")
        await db.execute(
            "INSERT INTO locations (inventory_id, name) VALUES ('inv', 'Fridge'), ('inv', 'Garage')"
        )
        await db.execute(
            "INSERT INTO items (id, inventory_id, name, quantity, expiry_date, price, created_at)"
            " VALUES ('milk', 'inv', 'Milk', 2.5, '2026-11-01', 1.2, '2026-10-01 08:00:00'),"
            "        ('rice', 'inv', 'Rice', 0, '', 0, '2026-10-01 08:00:00'),"
            "        ('oats', 'inv', 'Oats', 1, '', 0, NULL),"
            "        ('jam', 'inv', 'Jam', 0, '2025-01-01', 0, '2026-10-01 08:00:00')"
        )
        await db.execute(
            "INSERT INTO item_locations (item_id, location_id) VALUES ('milk', 2), ('milk', 1)"
        )
        await db.commit()

    repo = InventoryRepository(hass_with_tmp_config, db_filename="v3.db")
    await repo.async_initialize()
    try:
        assert await repo.list_batches("rice") == []
        [batch] = await repo.list_batches("milk")
        assert batch["quantity"] == 2.5
        assert batch["expiry_date"] == "2026-11-01"
        assert batch["location"] == "Garage"  # first item_locations row by rowid
        assert batch["unit_price"] == 1.2
        assert batch["purchased_at"] == "2026-10-01"
        item = await repo.get_item_by_name("inv", "Milk")
        assert item is not None and item["quantity"] == 2.5

        # A NULL created_at falls back to today's date.
        [oats] = await repo.list_batches("oats")
        cursor = await repo._connection().execute("SELECT date('now')")
        today_row = await cursor.fetchone()
        await cursor.close()
        assert today_row is not None and oats["purchased_at"] == today_row[0]
        # Out-of-stock items lose stale derived columns.
        jam = await repo.get_item_by_name("inv", "Jam")
        assert jam is not None
        assert (jam["quantity"], jam["expiry_date"]) == (0, "")
        assert await repo.list_batches("jam") == []

        # Re-running the migration never duplicates batches.
        await repo._migrate_to_v4()
        await repo._migrate_to_v4()
        assert len(await repo.list_batches("milk")) == 1
        assert len(await repo.list_batches("oats")) == 1
        jam = await repo.get_item_by_name("inv", "Jam")
        milk = await repo.get_item_by_name("inv", "Milk")
        assert jam is not None and milk is not None
        assert (jam["quantity"], jam["expiry_date"]) == (0, "")
        assert (milk["quantity"], milk["expiry_date"]) == (2.5, "2026-11-01")
    finally:
        await repo.async_close()


async def _item(repo: InventoryRepository, name: str = "Milk") -> str:
    return await repo.create_item("inv", {FIELD_NAME: name})


async def test_add_stock_creates_batch_and_refreshes_item_totals(repo: InventoryRepository) -> None:
    item_id = await _item(repo)
    change = await repo.add_stock(
        item_id, "inv", 2, expiry_date="2026-11-01", unit_price=1.5, purchased_at="2026-10-25"
    )
    assert (change.item_before, change.item_after) == (0, 2)
    [batch] = await repo.list_batches(item_id)
    assert batch["id"] == change.batches[0].batch_id
    item = await repo.get_item_by_name("inv", "Milk")
    assert item is not None
    assert (item["quantity"], item["expiry_date"]) == (2, "2026-11-01")


async def test_add_stock_merges_on_expiry_location_and_price(repo: InventoryRepository) -> None:
    """D4: same expiry + location + unit price tops up; any difference starts a new batch."""
    item_id = await _item(repo)
    fridge = await repo.ensure_location("inv", "Fridge")
    await repo.add_stock(
        item_id, "inv", 1, location_id=fridge, unit_price=2, purchased_at="2026-10-20"
    )
    await repo.add_stock(
        item_id, "inv", 2, location_id=fridge, unit_price=2, purchased_at="2026-10-10"
    )
    await repo.add_stock(
        item_id, "inv", 1, location_id=fridge, unit_price=3, purchased_at="2026-10-25"
    )
    await repo.add_stock(
        item_id, "inv", 1, location_id=None, unit_price=2, purchased_at="2026-10-25"
    )

    batches = await repo.list_batches(item_id)
    assert sorted((b["quantity"], b["unit_price"], b["location"]) for b in batches) == [
        (1, 2, ""),
        (1, 3, "Fridge"),
        (3, 2, "Fridge"),
    ]
    merged = next(b for b in batches if b["quantity"] == 3)
    assert merged["purchased_at"] == "2026-10-10"  # earliest purchase is kept


async def test_consume_stock_order_and_overflow(repo: InventoryRepository) -> None:
    """D3: soonest expiry first, then oldest purchase, no-expiry last; D7: empty batches go."""
    item_id = await _item(repo)
    await repo.add_stock(item_id, "inv", 2, expiry_date="", purchased_at="2026-01-01")
    await repo.add_stock(item_id, "inv", 1, expiry_date="2026-12-01", purchased_at="2026-10-02")
    await repo.add_stock(
        item_id, "inv", 1, expiry_date="2026-11-01", unit_price=9, purchased_at="2026-10-03"
    )
    await repo.add_stock(item_id, "inv", 1, expiry_date="2026-11-01", purchased_at="2026-10-01")

    change = await repo.consume_stock(item_id, 2.5)

    consumed = [(c.quantity_before, c.quantity_after) for c in change.batches]
    assert consumed == [(1, 0), (1, 0), (1, 0.5)]  # 11-01 (older purchase), 11-01, 12-01
    assert [c.unit_price for c in change.batches] == [0, 9, 0]  # purchase-date tie-break
    assert (change.item_before, change.item_after) == (5, 2.5)
    remaining = await repo.list_batches(item_id)
    assert [(b["expiry_date"], b["quantity"]) for b in remaining] == [("2026-12-01", 0.5), ("", 2)]


async def test_consume_stock_is_clamped_to_available(repo: InventoryRepository) -> None:
    item_id = await _item(repo)
    await repo.add_stock(item_id, "inv", 1, purchased_at="2026-10-01")
    change = await repo.consume_stock(item_id, 5)
    assert (change.item_before, change.item_after) == (1, 0)
    assert await repo.list_batches(item_id) == []
    item = await repo.get_item_by_name("inv", "Milk")
    assert item is not None and (item["quantity"], item["expiry_date"]) == (0, "")


async def test_consume_stock_filtered_by_location_and_batch(repo: InventoryRepository) -> None:
    item_id = await _item(repo)
    fridge = await repo.ensure_location("inv", "Fridge")
    garage = await repo.ensure_location("inv", "Garage")
    await repo.add_stock(
        item_id, "inv", 2, location_id=fridge, expiry_date="2026-11-01", purchased_at="2026-10-01"
    )
    garage_change = await repo.add_stock(
        item_id, "inv", 3, location_id=garage, expiry_date="2026-12-01", purchased_at="2026-10-01"
    )

    by_location = await repo.consume_stock(item_id, 1, location_id=garage)
    assert [c.location for c in by_location.batches] == ["Garage"]

    batch_id = garage_change.batches[0].batch_id
    by_batch = await repo.consume_stock(item_id, 1, batch_id=batch_id)
    assert [c.batch_id for c in by_batch.batches] == [batch_id]

    nothing = await repo.consume_stock(
        item_id, 1, location_id=await repo.ensure_location("inv", "Attic")
    )
    assert nothing.batches == () and nothing.item_before == nothing.item_after


async def test_update_and_delete_batch_refresh_totals(repo: InventoryRepository) -> None:
    item_id = await _item(repo)
    change = await repo.add_stock(
        item_id, "inv", 2, expiry_date="2026-11-01", purchased_at="2026-10-01"
    )
    batch_id = change.batches[0].batch_id

    updated = await repo.update_batch(batch_id, {"quantity": 5, "expiry_date": "2026-11-15"})
    assert updated is not None and (updated.item_before, updated.item_after) == (2, 5)
    item = await repo.get_item_by_name("inv", "Milk")
    assert item is not None and (item["quantity"], item["expiry_date"]) == (5, "2026-11-15")

    zeroed = await repo.update_batch(batch_id, {"quantity": 0})  # D7: deletes the batch
    assert zeroed is not None and zeroed.item_after == 0
    assert await repo.get_batch(batch_id) is None
    assert await repo.update_batch(batch_id, {"quantity": 1}) is None
    assert await repo.delete_batch(batch_id) is None


async def test_item_writes_cannot_set_derived_columns(repo: InventoryRepository) -> None:
    item_id = await repo.create_item(
        "inv", {FIELD_NAME: "Milk", FIELD_QUANTITY: 7, FIELD_EXPIRY_DATE: "2027-01-01"}
    )
    await repo.update_item(
        item_id, {FIELD_QUANTITY: 9, FIELD_EXPIRY_DATE: "2027-02-02", "unit": "L"}
    )
    item = await repo.get_item_by_name("inv", "Milk")
    assert item is not None
    assert (item[FIELD_QUANTITY], item[FIELD_EXPIRY_DATE], item["unit"]) == (0, "", "L")


@pytest.mark.parametrize("quantity", [0, 1e-7])
async def test_add_stock_of_nothing_is_a_no_op(repo: InventoryRepository, quantity: float) -> None:
    item_id = await _item(repo)
    change = await repo.add_stock(item_id, "inv", quantity, purchased_at="2026-10-01")
    assert (change.item_before, change.item_after, change.batches) == (0, 0, ())
    assert await repo.list_batches(item_id) == []


async def test_add_stock_negative_raises_and_leaves_batches(repo: InventoryRepository) -> None:
    item_id = await _item(repo)
    await repo.add_stock(item_id, "inv", 2, purchased_at="2026-10-01")
    with pytest.raises(ValueError, match="must be positive"):
        await repo.add_stock(item_id, "inv", -1, purchased_at="2026-10-01")
    [batch] = await repo.list_batches(item_id)
    assert batch["quantity"] == 2


async def test_legacy_item_with_null_expiry_migrates_to_one_batch(
    hass_with_tmp_config: HomeAssistant,
) -> None:
    payload = {
        "inventories": {
            "inv_legacy": {
                INVENTORY_NAME: "Legacy",
                INVENTORY_ITEMS: {
                    "Milk": {FIELD_NAME: "Milk", FIELD_QUANTITY: 2, FIELD_EXPIRY_DATE: None}
                },
            }
        }
    }
    repo = InventoryRepository(hass_with_tmp_config, db_filename="legacy_null_expiry.db")
    local_now = datetime(2001, 2, 3, 23, 30, tzinfo=UTC)
    with (
        patch(
            "custom_components.simple_inventory.storage.repository.Store.async_load",
            new=AsyncMock(return_value=payload),
        ),
        patch(
            "custom_components.simple_inventory.storage.repository.dt_util.now",
            return_value=local_now,
        ),
    ):
        await repo.async_initialize()
    try:
        item = await repo.get_item_by_name("inv_legacy", "Milk")
        assert item is not None
        [batch] = await repo.list_batches(item["id"])
        assert (batch["quantity"], batch["expiry_date"]) == (2, "")
        assert batch["purchased_at"] == "2001-02-03"  # HA local date, not date.today()
    finally:
        await repo.async_close()


async def test_history_event_records_batch_id(repo: InventoryRepository) -> None:
    item_id = await _item(repo)
    await repo.record_history_event(
        item_id=item_id,
        inventory_id="inv",
        event_type="increment",
        amount=1,
        quantity_before=0,
        quantity_after=1,
        batch_id="b-1",
    )
    [event] = await repo.get_item_history(item_id)
    assert event["batch_id"] == "b-1"


async def test_list_items_includes_batches_and_stocked_locations(
    repo: InventoryRepository,
) -> None:
    item_id = await _item(repo)
    fridge = await repo.ensure_location("inv", "Fridge")
    garage = await repo.ensure_location("inv", "Garage")
    await repo.add_stock(
        item_id, "inv", 1, location_id=garage, expiry_date="2026-12-01", purchased_at="2026-10-01"
    )
    await repo.add_stock(
        item_id, "inv", 2, location_id=fridge, expiry_date="2026-11-01", purchased_at="2026-10-01"
    )
    await repo.add_stock(
        item_id, "inv", 1, location_id=fridge, expiry_date="", purchased_at="2026-10-01"
    )

    [item] = await repo.list_items_with_details("inv")

    assert [(b["quantity"], b["location"], b["expiry_date"]) for b in item["batches"]] == [
        (2, "Fridge", "2026-11-01"),
        (1, "Garage", "2026-12-01"),
        (1, "Fridge", ""),
    ]
    assert item["stocked_locations"] == ["Fridge", "Garage"]
    assert set(item["batches"][0]) == {
        "id",
        "quantity",
        "expiry_date",
        "location",
        "unit_price",
        "purchased_at",
    }


async def test_list_items_unstocked_and_locationless_batches(repo: InventoryRepository) -> None:
    milk = await _item(repo)
    await _item(repo, "Eggs")
    await repo.add_stock(
        milk, "inv", 3, expiry_date="2026-11-05", unit_price=1.25, purchased_at="2026-10-02"
    )

    items = {item[FIELD_NAME]: item for item in await repo.list_items_with_details("inv")}

    assert items["Eggs"]["batches"] == []
    assert items["Eggs"]["stocked_locations"] == []
    [batch] = items["Milk"]["batches"]
    assert batch["location"] == ""
    assert batch["unit_price"] == 1.25
    assert batch["purchased_at"] == "2026-10-02"
    assert items["Milk"]["stocked_locations"] == []


# --- transfers (spec 2026-10-25: T2 sources, T3 amount, T4 usual locations, T5 merge) ---


async def _locations(repo: InventoryRepository, *names: str) -> list[int]:
    return [await repo.ensure_location("inv", name) for name in names]


async def test_transfer_part_of_a_batch_keeps_its_attributes(repo: InventoryRepository) -> None:
    item_id = await _item(repo)
    fridge, garage = await _locations(repo, "Fridge", "Garage")
    await repo.add_stock(
        item_id,
        "inv",
        6,
        expiry_date="2026-11-01",
        location_id=fridge,
        unit_price=1.5,
        purchased_at="2026-10-20",
    )
    [source] = await repo.list_batches(item_id)

    change = await repo.transfer_stock(
        item_id, "inv", 2, to_location_id=garage, batch_id=source["id"]
    )

    [move] = change.moves
    assert (move.batch_id, move.location_from, move.moved, move.unit_price) == (
        source["id"],
        "Fridge",
        2,
        1.5,
    )
    assert (change.item_total, change.location_to) == (6, "Garage")
    batches = {b["location"]: b for b in await repo.list_batches(item_id)}
    assert batches["Fridge"]["quantity"] == 4
    moved = batches["Garage"]
    assert moved["id"] == move.destination_batch_id != source["id"]
    assert (
        moved["quantity"],
        moved["expiry_date"],
        moved["unit_price"],
        moved["purchased_at"],
    ) == (2, "2026-11-01", 1.5, "2026-10-20")
    item = await repo.get_item_by_id(item_id)
    assert item is not None and (item["quantity"], item["expiry_date"]) == (6, "2026-11-01")


async def test_transfer_of_a_whole_batch_relocates_it(repo: InventoryRepository) -> None:
    item_id = await _item(repo)
    fridge, garage = await _locations(repo, "Fridge", "Garage")
    await repo.add_stock(item_id, "inv", 3, location_id=fridge, purchased_at="2026-10-20")
    [source] = await repo.list_batches(item_id)

    change = await repo.transfer_stock(
        item_id, "inv", None, to_location_id=garage, batch_id=source["id"]
    )

    assert [(m.batch_id, m.moved, m.destination_batch_id) for m in change.moves] == [
        (source["id"], 3, source["id"])
    ]
    assert [(b["id"], b["location"], b["quantity"]) for b in await repo.list_batches(item_id)] == [
        (source["id"], "Garage", 3)
    ]


async def test_transfer_merges_into_matching_destination_batch(repo: InventoryRepository) -> None:
    """Same expiry + unit price at the destination merges (earliest purchase date kept);
    the emptied source batch is deleted."""
    item_id = await _item(repo)
    fridge, garage = await _locations(repo, "Fridge", "Garage")
    await repo.add_stock(
        item_id,
        "inv",
        2,
        expiry_date="2026-11-01",
        location_id=fridge,
        unit_price=1.5,
        purchased_at="2026-10-01",
    )
    await repo.add_stock(
        item_id,
        "inv",
        1,
        expiry_date="2026-11-01",
        location_id=garage,
        unit_price=1.5,
        purchased_at="2026-10-15",
    )
    target = next(b for b in await repo.list_batches(item_id) if b["location"] == "Garage")

    change = await repo.transfer_stock(
        item_id, "inv", None, to_location_id=garage, from_location_id=fridge
    )

    assert [m.destination_batch_id for m in change.moves] == [target["id"]]
    [merged] = await repo.list_batches(item_id)
    assert (merged["id"], merged["location"], merged["quantity"], merged["purchased_at"]) == (
        target["id"],
        "Garage",
        3,
        "2026-10-01",
    )


async def test_transfer_part_into_matching_destination_batch(repo: InventoryRepository) -> None:
    """A partial move merges into the matching destination batch (earliest purchase date
    kept) and the source keeps the remainder."""
    item_id = await _item(repo)
    fridge, garage = await _locations(repo, "Fridge", "Garage")
    for qty, location, purchased in ((5, fridge, "2026-10-01"), (1, garage, "2026-10-15")):
        await repo.add_stock(
            item_id,
            "inv",
            qty,
            expiry_date="2026-11-01",
            location_id=location,
            unit_price=1.5,
            purchased_at=purchased,
        )
    by_location = {b["location"]: b for b in await repo.list_batches(item_id)}

    change = await repo.transfer_stock(
        item_id, "inv", 2, to_location_id=garage, from_location_id=fridge
    )

    assert [(m.batch_id, m.moved, m.destination_batch_id) for m in change.moves] == [
        (by_location["Fridge"]["id"], 2, by_location["Garage"]["id"])
    ]
    after = {b["location"]: b for b in await repo.list_batches(item_id)}
    assert (after["Fridge"]["id"], after["Fridge"]["quantity"]) == (by_location["Fridge"]["id"], 3)
    assert (
        after["Garage"]["id"],
        after["Garage"]["quantity"],
        after["Garage"]["purchased_at"],
    ) == (by_location["Garage"]["id"], 3, "2026-10-01")
    assert change.item_total == 6


@pytest.mark.parametrize("quantity", [0, -3])
async def test_transfer_rejects_non_positive_quantity(
    repo: InventoryRepository, quantity: float
) -> None:
    item_id = await _item(repo)
    fridge, garage = await _locations(repo, "Fridge", "Garage")
    await repo.add_stock(item_id, "inv", 2, location_id=fridge, purchased_at="2026-10-01")
    before = await repo.list_batches(item_id)

    with pytest.raises(ValueError):
        await repo.transfer_stock(
            item_id, "inv", quantity, to_location_id=garage, from_location_id=fridge
        )

    assert await repo.list_batches(item_id) == before


async def test_transfer_with_no_sources_raises(repo: InventoryRepository) -> None:
    item_id = await _item(repo)
    fridge, garage = await _locations(repo, "Fridge", "Garage")

    with pytest.raises(ValueError):
        await repo.transfer_stock(item_id, "inv", None, to_location_id=garage)
    assert await repo.first_item_location_id(item_id) is None


async def test_transfer_without_source_takes_soonest_stock_not_at_destination(
    repo: InventoryRepository,
) -> None:
    item_id = await _item(repo)
    fridge, garage, pantry = await _locations(repo, "Fridge", "Garage", "Pantry")
    await repo.add_stock(
        item_id, "inv", 1, expiry_date="2026-10-30", location_id=garage, purchased_at="2026-10-01"
    )
    await repo.add_stock(
        item_id, "inv", 1, expiry_date="2026-11-05", location_id=pantry, purchased_at="2026-10-01"
    )
    await repo.add_stock(
        item_id, "inv", 1, expiry_date="2026-11-01", location_id=fridge, purchased_at="2026-10-01"
    )
    await repo.add_stock(item_id, "inv", 2, location_id=None, purchased_at="2026-10-01")

    change = await repo.transfer_stock(item_id, "inv", 2, to_location_id=garage)

    assert [(m.location_from, m.moved) for m in change.moves] == [("Fridge", 1), ("Pantry", 1)]
    assert sorted(
        (b["location"], b["expiry_date"], b["quantity"]) for b in await repo.list_batches(item_id)
    ) == [
        ("", "", 2),
        ("Garage", "2026-10-30", 1),
        ("Garage", "2026-11-01", 1),
        ("Garage", "2026-11-05", 1),
    ]
    item = await repo.get_item_by_id(item_id)
    assert item is not None and (item["quantity"], item["expiry_date"]) == (5, "2026-10-30")


async def test_transfer_sources_exclude_only_the_destination(repo: InventoryRepository) -> None:
    item_id = await _item(repo)
    fridge, garage = await _locations(repo, "Fridge", "Garage")
    await repo.add_stock(item_id, "inv", 1, location_id=garage, purchased_at="2026-10-01")
    await repo.add_stock(item_id, "inv", 2, location_id=None, purchased_at="2026-10-02")
    await repo.add_stock(item_id, "inv", 3, location_id=fridge, purchased_at="2026-10-03")

    elsewhere = await repo.list_transfer_sources(item_id, to_location_id=garage)
    new_place = await repo.list_transfer_sources(item_id, to_location_id=None)
    from_fridge = await repo.list_transfer_sources(
        item_id, to_location_id=garage, from_location_id=fridge
    )

    assert [b["quantity"] for b in elsewhere] == [2, 3]  # unlocated stock is a source
    assert [b["quantity"] for b in new_place] == [1, 2, 3]
    assert [b["location"] for b in from_fridge] == ["Fridge"]


async def test_transfer_more_than_the_source_holds_writes_nothing(
    repo: InventoryRepository,
) -> None:
    item_id = await _item(repo)
    fridge, garage = await _locations(repo, "Fridge", "Garage")
    await repo.add_stock(item_id, "inv", 2, location_id=fridge, purchased_at="2026-10-01")
    before = await repo.list_batches(item_id)

    with pytest.raises(InsufficientStockError) as err:
        await repo.transfer_stock(item_id, "inv", 3, to_location_id=garage, from_location_id=fridge)

    assert err.value.available == 2
    assert await repo.list_batches(item_id) == before
    assert await repo.first_item_location_id(item_id) is None  # usual location not appended


async def test_transfer_appends_the_destination_to_usual_locations_once(
    repo: InventoryRepository,
) -> None:
    item_id = await _item(repo)
    fridge, garage = await _locations(repo, "Fridge", "Garage")
    await repo.set_item_locations(item_id, [fridge])
    await repo.add_stock(item_id, "inv", 2, location_id=fridge, purchased_at="2026-10-01")

    await repo.transfer_stock(item_id, "inv", 1, to_location_id=garage, from_location_id=fridge)
    await repo.transfer_stock(item_id, "inv", 1, to_location_id=garage, from_location_id=fridge)

    [item] = await repo.list_items_with_details("inv")
    assert item["locations"] == ["Fridge", "Garage"]
    assert [(b["location"], b["quantity"]) for b in item["batches"]] == [("Garage", 2)]
