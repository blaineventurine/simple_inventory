from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, patch

import aiosqlite
import pytest
from homeassistant.core import HomeAssistant

from custom_components.simple_inventory.const import (
    FIELD_AUTO_ADD_ENABLED,
    FIELD_AUTO_ADD_TO_LIST_QUANTITY,
    FIELD_CATEGORY,
    FIELD_DESCRIPTION,
    FIELD_DESIRED_QUANTITY,
    FIELD_EXPIRY_ALERT_DAYS,
    FIELD_EXPIRY_DATE,
    FIELD_LOCATION,
    FIELD_NAME,
    FIELD_QUANTITY,
    FIELD_TODO_LIST,
    FIELD_TODO_QUANTITY_PLACEMENT,
    FIELD_UNIT,
    INVENTORY_ITEMS,
    INVENTORY_NAME,
)
from custom_components.simple_inventory.storage.repository import (
    SCHEMA_VERSION,
    DatabaseFromNewerVersionError,
    InventoryRepository,
)


@pytest.fixture
async def repo(hass_with_tmp_config: HomeAssistant) -> AsyncGenerator[InventoryRepository, None]:
    repository = InventoryRepository(hass_with_tmp_config, db_filename="test_simple_inventory.db")
    await repository.async_initialize()
    try:
        yield repository
    finally:
        await repository.async_close()


@pytest.mark.asyncio
async def test_upsert_and_fetch_inventory(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "Desc", "mdi:fridge", "inventory", None)

    inv = await repo.fetch_inventory("inv1")
    assert inv is not None
    assert inv["id"] == "inv1"
    assert inv["name"] == "Kitchen"
    assert inv["description"] == "Desc"
    assert inv["icon"] == "mdi:fridge"
    assert inv["entry_type"] == "inventory"


@pytest.mark.asyncio
async def test_list_inventories_sorted_case_insensitive(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("a", "zeta", "", "", "", None)
    await repo.upsert_inventory("b", "Alpha", "", "", "", None)
    await repo.upsert_inventory("c", "beta", "", "", "", None)

    invs = await repo.list_inventories()
    assert [i["name"] for i in invs] == ["Alpha", "beta", "zeta"]


@pytest.mark.asyncio
async def test_create_item_and_get_by_name_case_insensitive(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)

    item_id = await repo.create_item(
        "inv1",
        {
            FIELD_NAME: "Milk",
            FIELD_UNIT: "L",
            FIELD_DESCRIPTION: "Whole milk",
            FIELD_EXPIRY_ALERT_DAYS: 0,
            FIELD_AUTO_ADD_ENABLED: False,
            FIELD_AUTO_ADD_TO_LIST_QUANTITY: 0,
            FIELD_TODO_LIST: "",
            "auto_add_id_to_description_enabled": False,
        },
    )
    await repo.add_stock(item_id, "inv1", 2, purchased_at="2026-10-01")

    item = await repo.get_item_by_name("inv1", "milk")
    assert item is not None
    assert item["id"] == item_id
    assert item[FIELD_NAME] == "Milk"
    assert item[FIELD_QUANTITY] == 2


@pytest.mark.asyncio
async def test_create_item_duplicate_name_raises_and_does_not_merge(
    repo: InventoryRepository,
) -> None:
    """create_item is a plain INSERT: a case-insensitive duplicate name raises and the
    existing row is left untouched (no silent quantity merge)."""
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)

    item_id = await repo.create_item(
        "inv1", {FIELD_NAME: "Milk", FIELD_DESCRIPTION: "", FIELD_UNIT: ""}
    )
    await repo.add_stock(item_id, "inv1", 2, purchased_at="2026-10-01")
    with pytest.raises(aiosqlite.IntegrityError):
        await repo.create_item(
            "inv1", {FIELD_NAME: "milk", FIELD_DESCRIPTION: "desc", FIELD_UNIT: "L"}
        )

    item = await repo.get_item_by_name("inv1", "MILK")
    assert item is not None
    assert item[FIELD_QUANTITY] == 2
    assert item[FIELD_UNIT] == ""
    assert item[FIELD_DESCRIPTION] == ""


@pytest.mark.asyncio
async def test_update_item_updates_fields(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)

    item_id = await repo.create_item("inv1", {FIELD_NAME: "Bread"})
    await repo.add_stock(item_id, "inv1", 5, purchased_at="2026-10-01")
    ok = await repo.update_item(item_id, {FIELD_DESCRIPTION: "Rye", FIELD_UNIT: "loaf"})
    assert ok is True

    item = await repo.get_item_by_name("inv1", "bread")
    assert item is not None
    assert item[FIELD_QUANTITY] == 5
    assert item[FIELD_DESCRIPTION] == "Rye"
    assert item[FIELD_UNIT] == "loaf"


@pytest.mark.asyncio
async def test_delete_item_cascades_links(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)

    item_id = await repo.create_item("inv1", {FIELD_NAME: "Milk"})

    loc_id = await repo.ensure_location("inv1", "Fridge")
    await repo.set_item_locations(item_id, [loc_id])

    cat_id = await repo.ensure_category("Dairy")
    await repo.set_item_categories(item_id, [cat_id])

    ok = await repo.delete_item(item_id)
    assert ok is True

    # Verify it is gone
    item = await repo.get_item_by_name("inv1", "milk")
    assert item is None

    # And links are gone (indirectly: list should be empty)
    items = await repo.list_items_with_details("inv1")
    assert items == []


@pytest.mark.asyncio
async def test_locations_and_categories_show_in_list_items_with_details(
    repo: InventoryRepository,
) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)

    item_id = await repo.create_item("inv1", {FIELD_NAME: "Milk", FIELD_QUANTITY: 2})
    loc_id = await repo.ensure_location("inv1", "Fridge")
    await repo.set_item_locations(item_id, [loc_id])
    cat_id = await repo.ensure_category("Dairy")
    await repo.set_item_categories(item_id, [cat_id])

    items = await repo.list_items_with_details("inv1")
    assert len(items) == 1
    item = items[0]
    assert item[FIELD_NAME] == "Milk"
    assert item[FIELD_LOCATION] == "Fridge"
    assert item[FIELD_CATEGORY] == "Dairy"
    assert item["locations"] == ["Fridge"]
    assert item["categories"] == ["Dairy"]


@pytest.mark.asyncio
async def test_legacy_migration_marks_flag_without_data(repo: InventoryRepository) -> None:
    # Create a fresh repo using a fresh DB file to ensure migration runs
    # (Use a new file name so the above repo doesn't interfere.)
    hass = repo._hass
    fresh = InventoryRepository(hass, db_filename="fresh_migration.db")

    with patch(
        "custom_components.simple_inventory.storage.repository.Store.async_load",
        new=AsyncMock(return_value=None),
    ):
        await fresh.async_initialize()

    # Verify migration flag
    conn = fresh._connection()
    cursor = await conn.execute("SELECT value FROM metadata WHERE key = ?", ("legacy_migrated",))
    row = await cursor.fetchone()
    await cursor.close()
    assert row is not None
    assert row[0] == "1"

    await fresh.async_close()


@pytest.mark.asyncio
async def test_legacy_migration_imports_items(repo: InventoryRepository) -> None:
    hass = repo._hass
    fresh = InventoryRepository(hass, db_filename="fresh_migration_with_data.db")

    legacy_payload: dict[str, Any] = {
        "inventories": {
            "inv_legacy": {
                INVENTORY_NAME: "Legacy Kitchen",
                INVENTORY_ITEMS: {
                    "Milk": {
                        FIELD_NAME: "Milk",
                        FIELD_QUANTITY: 2,
                        FIELD_UNIT: "L",
                        FIELD_LOCATION: "Fridge",
                        FIELD_CATEGORY: "Dairy",
                        FIELD_EXPIRY_DATE: "",
                        FIELD_EXPIRY_ALERT_DAYS: 0,
                        FIELD_DESCRIPTION: "",
                        FIELD_AUTO_ADD_ENABLED: False,
                        "auto_add_id_to_description_enabled": False,
                        FIELD_AUTO_ADD_TO_LIST_QUANTITY: 0,
                        FIELD_TODO_LIST: "",
                    }
                },
            }
        }
    }

    with patch(
        "custom_components.simple_inventory.storage.repository.Store.async_load",
        new=AsyncMock(return_value=legacy_payload),
    ):
        await fresh.async_initialize()

    invs = await fresh.list_inventories()
    assert any(i["id"] == "inv_legacy" for i in invs)

    items = await fresh.list_items_with_details("inv_legacy")
    assert len(items) == 1
    item = items[0]
    assert item[FIELD_NAME] == "Milk"
    assert item[FIELD_LOCATION] == "Fridge"
    assert item[FIELD_CATEGORY] == "Dairy"
    assert item[FIELD_QUANTITY] == 2
    [batch] = await fresh.list_batches(item["id"])
    assert (batch["quantity"], batch["location"]) == (2, "Fridge")

    await fresh.async_close()


@pytest.mark.asyncio
async def test_legacy_migration_skips_when_flag_already_set(repo: InventoryRepository) -> None:
    # Force flag in metadata
    conn = repo._connection()
    await conn.execute(
        "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
        ("legacy_migrated", "1"),
    )
    await conn.commit()

    with patch(
        "custom_components.simple_inventory.storage.repository.Store.async_load",
        new=AsyncMock(side_effect=AssertionError("Should not load legacy store")),
    ):
        # Call migration method again; it should return immediately
        await repo._maybe_migrate_legacy_store()


@pytest.mark.asyncio
async def test_schema_version_newer_raises_and_leaves_database_untouched(
    hass_with_tmp_config: HomeAssistant,
) -> None:
    repository = InventoryRepository(hass_with_tmp_config, db_filename="bad_schema.db")
    await repository.async_initialize()

    conn = repository._connection()
    await conn.execute(
        "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
        ("schema_version", "999"),
    )
    # An index a newer schema might own; the old code's schema setup drops this name.
    await conn.execute("CREATE INDEX idx_items_name_inventory ON items (inventory_id, name)")
    await conn.commit()
    await repository.async_close()

    repository2 = InventoryRepository(hass_with_tmp_config, db_filename="bad_schema.db")
    with pytest.raises(DatabaseFromNewerVersionError) as err:
        await repository2.async_initialize()
    assert isinstance(err.value, RuntimeError)
    assert (err.value.found, err.value.expected) == (999, SCHEMA_VERSION)
    await repository2.async_close()

    async with aiosqlite.connect(hass_with_tmp_config.config.path("bad_schema.db")) as raw:
        cursor = await raw.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name = ?",
            ("idx_items_name_inventory",),
        )
        assert await cursor.fetchone() is not None
        cursor = await raw.execute("SELECT value FROM metadata WHERE key = 'schema_version'")
        assert [tuple(row) for row in await cursor.fetchall()] == [("999",)]


@pytest.mark.asyncio
async def test_update_item_no_fields_returns_false(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    item_id = await repo.create_item("inv1", {FIELD_NAME: "Milk", FIELD_QUANTITY: 1})

    ok = await repo.update_item(item_id, {})
    assert ok is False


@pytest.mark.asyncio
async def test_delete_item_missing_returns_false(repo: InventoryRepository) -> None:
    ok = await repo.delete_item("does-not-exist")
    assert ok is False


@pytest.mark.asyncio
async def test_list_items_with_details_empty_inventory(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv_empty", "Empty", "", "", "", None)
    items = await repo.list_items_with_details("inv_empty")
    assert items == []


@pytest.mark.asyncio
async def test_get_item_by_name_not_found(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    item = await repo.get_item_by_name("inv1", "nope")
    assert item is None


@pytest.mark.asyncio
async def test_set_item_locations_empty_clears_rows(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    item_id = await repo.create_item("inv1", {FIELD_NAME: "Milk", FIELD_QUANTITY: 1})
    loc_id = await repo.ensure_location("inv1", "Fridge")

    await repo.set_item_locations(item_id, [loc_id])
    await repo.set_item_locations(item_id, [])  # should clear

    items = await repo.list_items_with_details("inv1")
    assert items[0]["locations"] == []


@pytest.mark.asyncio
async def test_set_item_categories_empty_clears_rows(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    item_id = await repo.create_item("inv1", {FIELD_NAME: "Milk", FIELD_QUANTITY: 1})
    cat_id = await repo.ensure_category("Dairy")

    await repo.set_item_categories(item_id, [cat_id])
    await repo.set_item_categories(item_id, [])  # should clear

    items = await repo.list_items_with_details("inv1")
    assert items[0]["categories"] == []


@pytest.mark.asyncio
async def test_decimal_quantity_round_trip(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)

    item_id = await repo.create_item(
        "inv1",
        {
            FIELD_NAME: "Bacon",
            FIELD_UNIT: "packs",
            FIELD_AUTO_ADD_TO_LIST_QUANTITY: 1.5,
        },
    )
    await repo.add_stock(item_id, "inv1", 0.5, purchased_at="2026-10-01")

    item = await repo.get_item_by_name("inv1", "Bacon")
    assert item is not None
    assert item[FIELD_QUANTITY] == 0.5
    assert item[FIELD_AUTO_ADD_TO_LIST_QUANTITY] == 1.5

    # Add a decimal amount
    change = await repo.add_stock(item_id, "inv1", 2.25, purchased_at="2026-10-01")
    assert (change.item_before, change.item_after) == (0.5, 2.75)

    item = await repo.get_item_by_name("inv1", "Bacon")
    assert item is not None
    assert item[FIELD_QUANTITY] == 2.75

    # Verify locations work
    loc_id = await repo.ensure_location("inv1", "Fridge")
    await repo.set_item_locations(item_id, [loc_id])

    items = await repo.list_items_with_details("inv1")
    assert len(items) == 1
    assert items[0]["locations"] == ["Fridge"]


@pytest.mark.asyncio
async def test_desired_quantity_round_trip(repo: InventoryRepository) -> None:
    """Test desired_quantity is stored and retrieved correctly."""
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)

    item_id = await repo.create_item(
        "inv1",
        {
            FIELD_NAME: "Bacon",
            FIELD_QUANTITY: 2,
            FIELD_DESIRED_QUANTITY: 10.0,
            FIELD_AUTO_ADD_ENABLED: True,
            FIELD_AUTO_ADD_TO_LIST_QUANTITY: 3,
            FIELD_TODO_LIST: "todo.shopping",
        },
    )

    # get_item_by_name
    item = await repo.get_item_by_name("inv1", "Bacon")
    assert item is not None
    assert item[FIELD_DESIRED_QUANTITY] == 10.0

    # list_items_with_details
    items = await repo.list_items_with_details("inv1")
    assert len(items) == 1
    assert items[0][FIELD_DESIRED_QUANTITY] == 10.0

    # update_item
    ok = await repo.update_item(item_id, {FIELD_DESIRED_QUANTITY: 20.0})
    assert ok is True

    item = await repo.get_item_by_name("inv1", "Bacon")
    assert item is not None
    assert item[FIELD_DESIRED_QUANTITY] == 20.0


@pytest.mark.asyncio
async def test_todo_quantity_placement_round_trip(repo: InventoryRepository) -> None:
    """Test todo_quantity_placement is stored and retrieved correctly."""
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)

    # Create with "description" placement
    item_id = await repo.create_item(
        "inv1",
        {
            FIELD_NAME: "Milk",
            FIELD_QUANTITY: 2,
            FIELD_TODO_QUANTITY_PLACEMENT: "description",
        },
    )

    # get_item_by_name
    item = await repo.get_item_by_name("inv1", "Milk")
    assert item is not None
    assert item[FIELD_TODO_QUANTITY_PLACEMENT] == "description"

    # list_items_with_details
    items = await repo.list_items_with_details("inv1")
    assert len(items) == 1
    assert items[0][FIELD_TODO_QUANTITY_PLACEMENT] == "description"

    # update_item
    ok = await repo.update_item(item_id, {FIELD_TODO_QUANTITY_PLACEMENT: "none"})
    assert ok is True

    item = await repo.get_item_by_name("inv1", "Milk")
    assert item is not None
    assert item[FIELD_TODO_QUANTITY_PLACEMENT] == "none"


@pytest.mark.asyncio
async def test_todo_quantity_placement_defaults_to_name(repo: InventoryRepository) -> None:
    """Test todo_quantity_placement defaults to 'name' when not specified."""
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)

    await repo.create_item(
        "inv1",
        {FIELD_NAME: "Bread", FIELD_QUANTITY: 1},
    )

    item = await repo.get_item_by_name("inv1", "Bread")
    assert item is not None
    assert item[FIELD_TODO_QUANTITY_PLACEMENT] == "name"


# ---------------------------------------------------------------------------
# Barcode tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_and_get_item_barcode(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    item_id = await repo.create_item("inv1", {FIELD_NAME: "Milk"})
    await repo.add_stock(item_id, "inv1", 2, purchased_at="2026-10-01")

    await repo.set_item_barcodes(item_id, "inv1", ["123456789012"])

    item = await repo.get_item_by_barcode("inv1", "123456789012")
    assert item is not None
    assert item["id"] == item_id
    assert item[FIELD_NAME] == "Milk"
    assert item[FIELD_QUANTITY] == 2


@pytest.mark.asyncio
async def test_get_item_by_barcode_not_found(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)

    item = await repo.get_item_by_barcode("inv1", "nonexistent")
    assert item is None


@pytest.mark.asyncio
async def test_barcode_unique_per_inventory(repo: InventoryRepository) -> None:
    """Same barcode in different inventories is OK."""
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    await repo.upsert_inventory("inv2", "Pantry", "", "", "", None)

    item1 = await repo.create_item("inv1", {FIELD_NAME: "Milk", FIELD_QUANTITY: 1})
    item2 = await repo.create_item("inv2", {FIELD_NAME: "Milk", FIELD_QUANTITY: 1})

    await repo.set_item_barcodes(item1, "inv1", ["SAME-BARCODE"])
    await repo.set_item_barcodes(item2, "inv2", ["SAME-BARCODE"])

    result1 = await repo.get_item_by_barcode("inv1", "SAME-BARCODE")
    result2 = await repo.get_item_by_barcode("inv2", "SAME-BARCODE")

    assert result1 is not None
    assert result2 is not None
    assert result1["id"] == item1
    assert result2["id"] == item2


@pytest.mark.asyncio
async def test_barcode_duplicate_in_same_inventory_fails(repo: InventoryRepository) -> None:
    """Same barcode on two different items in one inventory should fail."""
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    item1 = await repo.create_item("inv1", {FIELD_NAME: "Milk", FIELD_QUANTITY: 1})
    item2 = await repo.create_item("inv1", {FIELD_NAME: "Bread", FIELD_QUANTITY: 1})

    await repo.set_item_barcodes(item1, "inv1", ["DUPE-BC"])

    with pytest.raises(aiosqlite.IntegrityError):
        await repo.set_item_barcodes(item2, "inv1", ["DUPE-BC"])


@pytest.mark.asyncio
async def test_multiple_barcodes_per_item(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    item_id = await repo.create_item("inv1", {FIELD_NAME: "Milk", FIELD_QUANTITY: 1})

    await repo.set_item_barcodes(item_id, "inv1", ["BC-001", "BC-002"])

    result1 = await repo.get_item_by_barcode("inv1", "BC-001")
    result2 = await repo.get_item_by_barcode("inv1", "BC-002")

    assert result1 is not None
    assert result2 is not None
    assert result1["id"] == item_id
    assert result2["id"] == item_id


@pytest.mark.asyncio
async def test_list_items_with_details_includes_barcodes(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    item_id = await repo.create_item("inv1", {FIELD_NAME: "Milk", FIELD_QUANTITY: 1})

    await repo.set_item_barcodes(item_id, "inv1", ["BC-A", "BC-B"])

    items = await repo.list_items_with_details("inv1")
    assert len(items) == 1
    assert sorted(items[0]["barcodes"]) == ["BC-A", "BC-B"]


@pytest.mark.asyncio
async def test_list_items_with_details_empty_barcodes(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    await repo.create_item("inv1", {FIELD_NAME: "Bread", FIELD_QUANTITY: 1})

    items = await repo.list_items_with_details("inv1")
    assert len(items) == 1
    assert items[0]["barcodes"] == []


@pytest.mark.asyncio
async def test_delete_item_cascades_barcodes(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    item_id = await repo.create_item("inv1", {FIELD_NAME: "Milk", FIELD_QUANTITY: 1})

    await repo.set_item_barcodes(item_id, "inv1", ["CASCADE-BC"])

    await repo.delete_item(item_id)

    # Barcode should be gone
    result = await repo.get_item_by_barcode("inv1", "CASCADE-BC")
    assert result is None


# --- Feature 2: Consumption History ---


@pytest.mark.asyncio
async def test_record_history_event(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    item_id = await repo.create_item("inv1", {FIELD_NAME: "Milk", FIELD_QUANTITY: 5})

    event_id = await repo.record_history_event(
        item_id=item_id,
        inventory_id="inv1",
        event_type="decrement",
        amount=2,
        quantity_before=5,
        quantity_after=3,
    )
    assert event_id  # non-empty UUID string


@pytest.mark.asyncio
async def test_get_item_history(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    item_id = await repo.create_item("inv1", {FIELD_NAME: "Milk", FIELD_QUANTITY: 5})

    await repo.record_history_event(
        item_id=item_id,
        inventory_id="inv1",
        event_type="decrement",
        amount=2,
        quantity_before=5,
        quantity_after=3,
    )
    await repo.record_history_event(
        item_id=item_id,
        inventory_id="inv1",
        event_type="increment",
        amount=1,
        quantity_before=3,
        quantity_after=4,
    )

    events = await repo.get_item_history(item_id)
    assert len(events) == 2
    # Most recent first
    assert events[0]["event_type"] == "increment"
    assert events[1]["event_type"] == "decrement"
    assert events[0]["item_name"] == "Milk"


@pytest.mark.asyncio
async def test_get_inventory_history(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    item_a = await repo.create_item("inv1", {FIELD_NAME: "Milk", FIELD_QUANTITY: 5})
    item_b = await repo.create_item("inv1", {FIELD_NAME: "Bread", FIELD_QUANTITY: 2})

    await repo.record_history_event(
        item_id=item_a,
        inventory_id="inv1",
        event_type="add",
        amount=5,
        quantity_before=0,
        quantity_after=5,
    )
    await repo.record_history_event(
        item_id=item_b,
        inventory_id="inv1",
        event_type="add",
        amount=2,
        quantity_before=0,
        quantity_after=2,
    )

    events = await repo.get_inventory_history("inv1")
    assert len(events) == 2


@pytest.mark.asyncio
async def test_get_history_with_event_type_filter(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    item_id = await repo.create_item("inv1", {FIELD_NAME: "Milk", FIELD_QUANTITY: 5})

    await repo.record_history_event(
        item_id=item_id,
        inventory_id="inv1",
        event_type="increment",
        amount=1,
        quantity_before=5,
        quantity_after=6,
    )
    await repo.record_history_event(
        item_id=item_id,
        inventory_id="inv1",
        event_type="decrement",
        amount=2,
        quantity_before=6,
        quantity_after=4,
    )

    events = await repo.get_item_history(item_id, event_type="decrement")
    assert len(events) == 1
    assert events[0]["event_type"] == "decrement"


@pytest.mark.asyncio
async def test_schema_migration_v1_to_v2(
    hass_with_tmp_config: HomeAssistant,
) -> None:
    """Test that an existing v1 database gets migrated to v2."""
    db_path = hass_with_tmp_config.config.path("migration_test.db")

    # Create a v1 database manually
    conn = await aiosqlite.connect(db_path)
    await conn.execute("PRAGMA foreign_keys = ON")
    await conn.executescript("""
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE inventories (
            id TEXT PRIMARY KEY, name TEXT NOT NULL,
            description TEXT DEFAULT '', icon TEXT DEFAULT '',
            entry_type TEXT DEFAULT '', metadata TEXT DEFAULT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE UNIQUE INDEX idx_inventories_name ON inventories (LOWER(name));
        CREATE TABLE items (
            id TEXT PRIMARY KEY, inventory_id TEXT NOT NULL,
            name TEXT NOT NULL COLLATE NOCASE, description TEXT DEFAULT '',
            quantity REAL NOT NULL DEFAULT 0, unit TEXT DEFAULT '',
            expiry_date TEXT DEFAULT '', expiry_alert_days INTEGER DEFAULT 0,
            auto_add_enabled INTEGER NOT NULL DEFAULT 0,
            auto_add_id_to_description_enabled INTEGER NOT NULL DEFAULT 0,
            auto_add_to_list_quantity REAL NOT NULL DEFAULT 0,
            desired_quantity REAL NOT NULL DEFAULT 0,
            todo_list TEXT DEFAULT '',
            todo_quantity_placement TEXT NOT NULL DEFAULT 'name',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (inventory_id) REFERENCES inventories(id) ON DELETE CASCADE,
            UNIQUE (inventory_id, name)
        );
        CREATE INDEX idx_items_inventory_id ON items (inventory_id);
        CREATE TABLE locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inventory_id TEXT NOT NULL, name TEXT NOT NULL COLLATE NOCASE,
            description TEXT DEFAULT '', color TEXT DEFAULT '',
            sort_order INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (inventory_id) REFERENCES inventories(id) ON DELETE CASCADE,
            UNIQUE (inventory_id, name)
        );
        CREATE TABLE item_locations (
            item_id TEXT NOT NULL, location_id INTEGER NOT NULL,
            quantity REAL NOT NULL DEFAULT 0, notes TEXT DEFAULT '',
            PRIMARY KEY (item_id, location_id),
            FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE,
            FOREIGN KEY (location_id) REFERENCES locations(id) ON DELETE CASCADE
        );
        CREATE TABLE categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL COLLATE NOCASE
        );
        CREATE UNIQUE INDEX idx_categories_name ON categories (name);
        CREATE TABLE item_categories (
            item_id TEXT NOT NULL, category_id INTEGER NOT NULL,
            PRIMARY KEY (item_id, category_id),
            FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE,
            FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE
        );
        CREATE TABLE item_barcodes (
            item_id TEXT NOT NULL, inventory_id TEXT NOT NULL,
            barcode TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (item_id, barcode),
            FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE,
            FOREIGN KEY (inventory_id) REFERENCES inventories(id) ON DELETE CASCADE
        );
        CREATE UNIQUE INDEX idx_item_barcodes_unique
            ON item_barcodes (inventory_id, barcode);
    """)
    await conn.execute("INSERT INTO metadata (key, value) VALUES ('schema_version', '1')")
    await conn.execute("INSERT INTO metadata (key, value) VALUES ('legacy_migrated', '1')")
    await conn.commit()
    await conn.close()

    # Now open via repository — it should migrate
    repo = InventoryRepository(hass_with_tmp_config, db_filename="migration_test.db")
    await repo.async_initialize()

    try:
        # Verify schema version is now current
        conn = repo._connection()
        cursor = await conn.execute("SELECT value FROM metadata WHERE key = 'schema_version'")
        row = await cursor.fetchone()
        await cursor.close()
        assert row is not None
        assert int(row[0]) == SCHEMA_VERSION

        # Verify consumption_history table exists
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='consumption_history'"
        )
        table = await cursor.fetchone()
        await cursor.close()
        assert table is not None

        # Verify price column was added to items and consumption_history
        cursor = await conn.execute("PRAGMA table_info(items)")
        item_columns = {r[1] for r in await cursor.fetchall()}
        await cursor.close()
        assert "price" in item_columns

        cursor = await conn.execute("PRAGMA table_info(consumption_history)")
        history_columns = {r[1] for r in await cursor.fetchall()}
        await cursor.close()
        assert "price" in history_columns
        assert "batch_id" in history_columns

        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='item_batches'"
        )
        assert await cursor.fetchone() is not None
        await cursor.close()
    finally:
        await repo.async_close()


# --- Feature: Global barcode lookup and set_item_barcodes ---


@pytest.mark.asyncio
async def test_get_item_by_barcode_global(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    await repo.upsert_inventory("inv2", "Pantry", "", "", "", None)

    item1 = await repo.create_item("inv1", {FIELD_NAME: "Milk", FIELD_QUANTITY: 1})
    item2 = await repo.create_item("inv2", {FIELD_NAME: "Milk 2L", FIELD_QUANTITY: 2})

    await repo.set_item_barcodes(item1, "inv1", ["GLOBAL-BC"])
    await repo.set_item_barcodes(item2, "inv2", ["GLOBAL-BC"])

    results = await repo.get_item_by_barcode_global("GLOBAL-BC")
    assert len(results) == 2

    inv_ids = {r["inventory_id"] for r in results}
    assert inv_ids == {"inv1", "inv2"}

    for r in results:
        assert "inventory_name" in r
        assert FIELD_NAME in r


@pytest.mark.asyncio
async def test_get_item_by_barcode_global_not_found(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    results = await repo.get_item_by_barcode_global("NONEXISTENT")
    assert results == []


async def _item_relations(repo: InventoryRepository, inventory_id: str, key: str) -> list[str]:
    items = await repo.list_items_with_details(inventory_id)
    assert len(items) == 1
    return list(items[0][key])


@pytest.mark.asyncio
async def test_set_item_barcodes_replaces_all(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    item_id = await repo.create_item("inv1", {FIELD_NAME: "Milk", FIELD_QUANTITY: 1})

    await repo.set_item_barcodes(item_id, "inv1", ["OLD-BC-1", "OLD-BC-2"])
    assert len(await _item_relations(repo, "inv1", "barcodes")) == 2

    await repo.set_item_barcodes(item_id, "inv1", ["NEW-BC-A", "NEW-BC-B", "NEW-BC-C"])

    barcodes = await _item_relations(repo, "inv1", "barcodes")
    assert sorted(barcodes) == ["NEW-BC-A", "NEW-BC-B", "NEW-BC-C"]


@pytest.mark.asyncio
async def test_set_item_barcodes_empty_clears(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    item_id = await repo.create_item("inv1", {FIELD_NAME: "Milk", FIELD_QUANTITY: 1})

    await repo.set_item_barcodes(item_id, "inv1", ["BC-1"])
    assert len(await _item_relations(repo, "inv1", "barcodes")) == 1

    await repo.set_item_barcodes(item_id, "inv1", [])
    assert await _item_relations(repo, "inv1", "barcodes") == []


@pytest.mark.asyncio
async def test_set_item_aliases_replaces_all(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    item_id = await repo.create_item("inv1", {FIELD_NAME: "Oatmeal", FIELD_QUANTITY: 1})

    await repo.set_item_aliases(item_id, "inv1", ["oats", "hot cereal"])
    aliases = await _item_relations(repo, "inv1", "aliases")
    assert sorted(aliases) == ["hot cereal", "oats"]

    await repo.set_item_aliases(item_id, "inv1", ["steel-cut oats"])
    assert await _item_relations(repo, "inv1", "aliases") == ["steel-cut oats"]


@pytest.mark.asyncio
async def test_set_item_aliases_empty_clears(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    item_id = await repo.create_item("inv1", {FIELD_NAME: "Oatmeal", FIELD_QUANTITY: 1})

    await repo.set_item_aliases(item_id, "inv1", ["oats"])
    assert len(await _item_relations(repo, "inv1", "aliases")) == 1

    await repo.set_item_aliases(item_id, "inv1", [])
    assert await _item_relations(repo, "inv1", "aliases") == []


@pytest.mark.asyncio
async def test_set_item_aliases_duplicate_across_items_raises(repo: InventoryRepository) -> None:
    """Two different items in the same inventory cannot share an alias."""
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    item_a = await repo.create_item("inv1", {FIELD_NAME: "Oatmeal", FIELD_QUANTITY: 1})
    item_b = await repo.create_item("inv1", {FIELD_NAME: "Granola", FIELD_QUANTITY: 1})

    await repo.set_item_aliases(item_a, "inv1", ["breakfast food"])

    with pytest.raises(aiosqlite.IntegrityError):
        await repo.set_item_aliases(item_b, "inv1", ["breakfast food"])


@pytest.mark.asyncio
async def test_aliases_show_in_list_items_with_details(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    item_id = await repo.create_item("inv1", {FIELD_NAME: "Oatmeal", FIELD_QUANTITY: 1})
    await repo.set_item_aliases(item_id, "inv1", ["oats", "hot cereal"])

    items = await repo.list_items_with_details("inv1")
    assert len(items) == 1
    assert sorted(items[0]["aliases"]) == ["hot cereal", "oats"]


@pytest.mark.asyncio
async def test_delete_item_cascades_aliases(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    item_id = await repo.create_item("inv1", {FIELD_NAME: "Oatmeal", FIELD_QUANTITY: 1})
    await repo.set_item_aliases(item_id, "inv1", ["oats"])

    ok = await repo.delete_item(item_id)
    assert ok is True

    cursor = await repo._connection().execute(
        "SELECT COUNT(*) FROM item_aliases WHERE item_id = ?", (item_id,)
    )
    row = await cursor.fetchone()
    await cursor.close()
    assert row is not None and row[0] == 0

    items = await repo.list_items_with_details("inv1")
    assert items == []


@pytest.mark.asyncio
async def test_get_barcode_provider_config_empty(repo: InventoryRepository) -> None:
    config = await repo.get_barcode_provider_config()
    assert config == {}


@pytest.mark.asyncio
async def test_set_and_get_barcode_provider_config(repo: InventoryRepository) -> None:
    await repo.set_barcode_provider_config({"provider": "openfoodfacts"})
    config = await repo.get_barcode_provider_config()
    assert config == {"provider": "openfoodfacts"}


@pytest.mark.asyncio
async def test_set_barcode_provider_config_overwrites(repo: InventoryRepository) -> None:
    await repo.set_barcode_provider_config({"provider": "openfoodfacts"})
    await repo.set_barcode_provider_config({"provider": "custom_provider"})
    config = await repo.get_barcode_provider_config()
    assert config == {"provider": "custom_provider"}


@pytest.mark.asyncio
async def test_set_barcode_provider_config_locked_write_round_trips(
    repo: InventoryRepository,
) -> None:
    """set_barcode_provider_config now acquires self._lock (matching every other
    write method in InventoryRepository, e.g. upsert_inventory) before writing to
    the metadata table. A single-threaded integration test cannot directly observe
    lock acquisition or exercise the race it prevents (concurrent writers
    interleaving INSERT OR REPLACE statements) - that requires a coordinator-level
    concurrency test. This test instead confirms the locked write path still
    behaves correctly for the common case: a single call writes a value that
    round-trips exactly through get_barcode_provider_config.
    """
    await repo.set_barcode_provider_config({"provider": "upcitemdb", "api_key": "abc123"})
    config = await repo.get_barcode_provider_config()
    assert config == {"provider": "upcitemdb", "api_key": "abc123"}


@pytest.mark.asyncio
async def test_add_stock_concurrent_increments_are_atomic(
    repo: InventoryRepository,
) -> None:
    """Concurrent add_stock calls on the same item must not lose updates: the
    single-lock transaction serializes the read-modify-write, so N concurrent +1
    additions must land as N distinct, non-overlapping steps.
    """
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    item_id = await repo.create_item("inv1", {FIELD_NAME: "Milk"})
    await repo.add_stock(item_id, "inv1", 10, purchased_at="2026-10-01")

    results = await asyncio.gather(
        *(repo.add_stock(item_id, "inv1", 1, purchased_at="2026-10-01") for _ in range(10))
    )

    pairs = sorted((change.item_before, change.item_after) for change in results)
    for (_before, after), (next_before, _next_after) in zip(pairs, pairs[1:]):
        assert after == next_before

    item = await repo.get_item_by_name("inv1", "milk")
    assert item is not None
    assert item[FIELD_QUANTITY] == 20  # 10 + 10 * 1, no lost updates


# --- Audit regressions ---


async def _commit_unrelated_write(repo: InventoryRepository) -> None:
    """Any later committing write would flush a half-applied transaction."""
    await repo.upsert_inventory("inv_other", "Other", "", "", "", None)


@pytest.mark.asyncio
async def test_set_item_barcodes_failure_rolls_back(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    milk = await repo.create_item("inv1", {FIELD_NAME: "Milk", FIELD_QUANTITY: 1})
    bread = await repo.create_item("inv1", {FIELD_NAME: "Bread", FIELD_QUANTITY: 1})
    await repo.set_item_barcodes(milk, "inv1", ["TAKEN"])
    await repo.set_item_barcodes(bread, "inv1", ["BREAD-1"])

    with pytest.raises(aiosqlite.IntegrityError):
        await repo.set_item_barcodes(bread, "inv1", ["BREAD-2", "TAKEN"])
    await _commit_unrelated_write(repo)

    items = {i[FIELD_NAME]: i for i in await repo.list_items_with_details("inv1")}
    assert items["Bread"]["barcodes"] == ["BREAD-1"]
    assert items["Milk"]["barcodes"] == ["TAKEN"]


@pytest.mark.asyncio
async def test_set_item_aliases_failure_rolls_back(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    milk = await repo.create_item("inv1", {FIELD_NAME: "Milk", FIELD_QUANTITY: 1})
    bread = await repo.create_item("inv1", {FIELD_NAME: "Bread", FIELD_QUANTITY: 1})
    await repo.set_item_aliases(milk, "inv1", ["taken"])
    await repo.set_item_aliases(bread, "inv1", ["loaf"])

    with pytest.raises(aiosqlite.IntegrityError):
        await repo.set_item_aliases(bread, "inv1", ["toast", "taken"])
    await _commit_unrelated_write(repo)

    items = {i[FIELD_NAME]: i for i in await repo.list_items_with_details("inv1")}
    assert items["Bread"]["aliases"] == ["loaf"]


@pytest.mark.asyncio
async def test_set_item_locations_failure_rolls_back(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    milk = await repo.create_item("inv1", {FIELD_NAME: "Milk", FIELD_QUANTITY: 1})
    fridge = await repo.ensure_location("inv1", "Fridge")
    pantry = await repo.ensure_location("inv1", "Pantry")
    await repo.set_item_locations(milk, [fridge])

    with pytest.raises(aiosqlite.IntegrityError):
        await repo.set_item_locations(milk, [pantry, pantry])
    await _commit_unrelated_write(repo)

    items = await repo.list_items_with_details("inv1")
    assert items[0]["locations"] == ["Fridge"]


@pytest.mark.asyncio
async def test_set_item_categories_failure_rolls_back(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    milk = await repo.create_item("inv1", {FIELD_NAME: "Milk", FIELD_QUANTITY: 1})
    dairy = await repo.ensure_category("Dairy")
    cold = await repo.ensure_category("Cold")
    await repo.set_item_categories(milk, [dairy])

    with pytest.raises(aiosqlite.IntegrityError):
        await repo.set_item_categories(milk, [cold, cold])
    await _commit_unrelated_write(repo)

    items = await repo.list_items_with_details("inv1")
    assert items[0]["categories"] == ["Dairy"]


@pytest.mark.asyncio
async def test_ensure_category_preserves_existing_casing(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    milk = await repo.create_item("inv1", {FIELD_NAME: "Milk", FIELD_QUANTITY: 1})
    first = await repo.ensure_category("Dairy")
    second = await repo.ensure_category("DAIRY")
    assert first == second

    await repo.set_item_categories(milk, [second])
    items = await repo.list_items_with_details("inv1")
    assert items[0]["categories"] == ["Dairy"]


@pytest.mark.asyncio
async def test_list_location_names_is_per_inventory_and_sorted(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    await repo.upsert_inventory("inv2", "Garage", "", "", "", None)
    await repo.ensure_location("inv1", "pantry")
    await repo.ensure_location("inv1", "Fridge")
    await repo.ensure_location("inv2", "Shelf")

    assert await repo.list_location_names("inv1") == ["Fridge", "pantry"]
    assert await repo.list_location_names("missing") == []


@pytest.mark.asyncio
async def test_locations_and_categories_keep_caller_order(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    milk = await repo.create_item("inv1", {FIELD_NAME: "Milk", FIELD_QUANTITY: 1})
    fridge = await repo.ensure_location("inv1", "Fridge")
    pantry = await repo.ensure_location("inv1", "Pantry")
    dairy = await repo.ensure_category("Dairy")
    cold = await repo.ensure_category("Cold")

    await repo.set_item_locations(milk, [pantry, fridge])
    await repo.set_item_categories(milk, [cold, dairy])

    item = (await repo.list_items_with_details("inv1"))[0]
    assert item["locations"] == ["Pantry", "Fridge"]
    assert item[FIELD_LOCATION] == "Pantry"
    assert item["categories"] == ["Cold", "Dairy"]
    assert item[FIELD_CATEGORY] == "Cold"


@pytest.mark.asyncio
async def test_create_and_update_item_round_quantities(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    item_id = await repo.create_item(
        "inv1",
        {
            FIELD_NAME: "Flour",
            FIELD_AUTO_ADD_TO_LIST_QUANTITY: 0.1 + 0.2,
            FIELD_DESIRED_QUANTITY: 0.1 + 0.2,
        },
    )
    item = await repo.get_item_by_name("inv1", "Flour")
    assert item is not None
    assert item[FIELD_AUTO_ADD_TO_LIST_QUANTITY] == 0.3
    assert item[FIELD_DESIRED_QUANTITY] == 0.3

    await repo.update_item(
        item_id,
        {
            FIELD_AUTO_ADD_TO_LIST_QUANTITY: 0.7 + 0.1,
            FIELD_DESIRED_QUANTITY: 0.7 + 0.1,
        },
    )
    item = await repo.get_item_by_name("inv1", "Flour")
    assert item is not None
    assert item[FIELD_AUTO_ADD_TO_LIST_QUANTITY] == 0.8
    assert item[FIELD_DESIRED_QUANTITY] == 0.8


@pytest.mark.asyncio
async def test_migrate_to_v3_is_idempotent_when_columns_exist(repo: InventoryRepository) -> None:
    await repo._migrate_to_v3()
    await repo._migrate_to_v3()


@pytest.mark.asyncio
async def test_migrate_to_v3_propagates_real_errors(repo: InventoryRepository) -> None:
    conn = repo._connection()
    await conn.execute("DROP TABLE consumption_history")
    await conn.commit()

    with pytest.raises(aiosqlite.OperationalError):
        await repo._migrate_to_v3()


def _legacy_payload(bad_alert_days: Any) -> dict[str, Any]:
    return {
        "inventories": {
            "inv_legacy": {
                INVENTORY_NAME: "Legacy Kitchen",
                INVENTORY_ITEMS: {
                    "Milk": {FIELD_NAME: "Milk", FIELD_QUANTITY: 2, FIELD_LOCATION: "Fridge"},
                    "Eggs": {
                        FIELD_NAME: "Eggs",
                        FIELD_QUANTITY: 12,
                        FIELD_EXPIRY_ALERT_DAYS: bad_alert_days,
                    },
                },
            }
        }
    }


async def _read_migration_flag(repository: InventoryRepository) -> str | None:
    cursor = await repository._connection().execute(
        "SELECT value FROM metadata WHERE key = ?", ("legacy_migrated",)
    )
    row = await cursor.fetchone()
    await cursor.close()
    return None if row is None else str(row[0])


@pytest.mark.asyncio
async def test_legacy_migration_failed_run_then_retry_does_not_double(
    hass_with_tmp_config: HomeAssistant,
) -> None:
    """A migration that fails part-way must leave nothing committed (no items, no
    'running' sentinel) so the retry imports each item exactly once."""
    store_path = "custom_components.simple_inventory.storage.repository.Store.async_load"

    first = InventoryRepository(hass_with_tmp_config, db_filename="legacy_retry.db")
    with (
        patch(store_path, new=AsyncMock(return_value=_legacy_payload("not-a-number"))),
        pytest.raises(ValueError),
    ):
        await first.async_initialize()
    assert await first.get_item_by_name("inv_legacy", "Milk") is None
    assert await _read_migration_flag(first) is None
    await first.async_close()

    second = InventoryRepository(hass_with_tmp_config, db_filename="legacy_retry.db")
    with patch(store_path, new=AsyncMock(return_value=_legacy_payload(3))):
        await second.async_initialize()
    try:
        items = {i[FIELD_NAME]: i for i in await second.list_items_with_details("inv_legacy")}
        assert items["Milk"][FIELD_QUANTITY] == 2
        assert items["Milk"]["locations"] == ["Fridge"]
        assert items["Eggs"][FIELD_QUANTITY] == 12
        assert await _read_migration_flag(second) == "1"
    finally:
        await second.async_close()


@pytest.mark.asyncio
async def test_legacy_migration_skips_items_that_already_exist(
    hass_with_tmp_config: HomeAssistant,
) -> None:
    """An interrupted pre-fix run may have committed some items; re-running must not
    merge quantities into them."""
    store_path = "custom_components.simple_inventory.storage.repository.Store.async_load"
    repository = InventoryRepository(hass_with_tmp_config, db_filename="legacy_skip.db")
    with patch(store_path, new=AsyncMock(return_value=None)):
        await repository.async_initialize()
    await repository.upsert_inventory("inv_legacy", "Legacy Kitchen")
    milk_id = await repository.create_item("inv_legacy", {FIELD_NAME: "Milk"})
    await repository.add_stock(milk_id, "inv_legacy", 2, purchased_at="2026-10-01")
    conn = repository._connection()
    await conn.execute("UPDATE metadata SET value = 'running' WHERE key = ?", ("legacy_migrated",))
    await conn.commit()

    with patch(store_path, new=AsyncMock(return_value=_legacy_payload(3))):
        await repository._maybe_migrate_legacy_store()
    try:
        items = {i[FIELD_NAME]: i for i in await repository.list_items_with_details("inv_legacy")}
        assert items["Milk"][FIELD_QUANTITY] == 2
        assert items["Eggs"][FIELD_QUANTITY] == 12
        assert len(await repository.list_batches(milk_id)) == 1
        assert [b["quantity"] for b in await repository.list_batches(items["Eggs"]["id"])] == [12]
        assert await _read_migration_flag(repository) == "1"
    finally:
        await repository.async_close()


# --- read helpers for diagnostics and repairs -------------------------------------------


async def test_get_metadata_value(repo: InventoryRepository) -> None:
    assert await repo.get_metadata_value("schema_version") == str(SCHEMA_VERSION)
    assert await repo.get_metadata_value("no_such_key") is None


async def test_get_inventory_counts(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen")
    await repo.upsert_inventory("inv2", "Garage")
    milk = await repo.create_item(
        "inv1",
        {FIELD_NAME: "Milk", FIELD_QUANTITY: 0, FIELD_AUTO_ADD_ENABLED: True},
    )
    eggs = await repo.create_item("inv1", {FIELD_NAME: "Eggs"})
    await repo.add_stock(eggs, "inv1", 6, purchased_at="2026-10-01")
    other = await repo.create_item("inv2", {FIELD_NAME: "Oil", FIELD_QUANTITY: 0})

    fridge = await repo.ensure_location("inv1", "Fridge")
    await repo.ensure_location("inv1", "Pantry")
    await repo.set_item_locations(milk, [fridge])
    dairy = await repo.ensure_category("Dairy")
    breakfast = await repo.ensure_category("Breakfast")
    await repo.set_item_categories(milk, [dairy, breakfast])
    await repo.set_item_categories(eggs, [breakfast])
    await repo.set_item_categories(other, [await repo.ensure_category("Automotive")])
    await repo.set_item_barcodes(milk, "inv1", ["111", "222"])
    await repo.set_item_aliases(eggs, "inv1", ["ova"])
    await repo.record_history_event(milk, "inv1", "increment", 1, 0, 1)
    await repo.record_history_event(other, "inv2", "increment", 1, 0, 1)

    assert await repo.get_inventory_counts("inv1") == {
        "items": 2,
        "items_out_of_stock": 1,
        "auto_add_enabled": 1,
        "locations": 2,
        "categories": 2,
        "barcodes": 2,
        "aliases": 1,
        "history_events": 1,
    }
    assert (await repo.get_inventory_counts("missing"))["items"] == 0


async def test_get_todo_list_references(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen")
    await repo.upsert_inventory("inv2", "Garage")
    await repo.create_item("inv1", {FIELD_NAME: "Milk", FIELD_TODO_LIST: "todo.grocery"})
    await repo.create_item("inv1", {FIELD_NAME: "Eggs", FIELD_TODO_LIST: "todo.grocery"})
    await repo.create_item("inv1", {FIELD_NAME: "Soap", FIELD_TODO_LIST: "todo.chores"})
    await repo.create_item("inv1", {FIELD_NAME: "Salt", FIELD_TODO_LIST: ""})
    await repo.create_item("inv2", {FIELD_NAME: "Oil", FIELD_TODO_LIST: "todo.garage"})

    assert await repo.get_todo_list_references("inv1") == {
        "todo.chores": 1,
        "todo.grocery": 2,
    }
    assert await repo.get_todo_list_references("missing") == {}


async def test_list_orphaned_inventories(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("kept", "Kitchen")
    await repo.upsert_inventory("gone_b", "zeta")
    await repo.upsert_inventory("gone_a", "Alpha")
    await repo.create_item("gone_a", {FIELD_NAME: "Milk"})
    await repo.create_item("gone_a", {FIELD_NAME: "Eggs"})
    await repo.create_item("kept", {FIELD_NAME: "Salt"})

    assert await repo.list_orphaned_inventories({"kept"}) == [
        {"id": "gone_a", "name": "Alpha", "item_count": 2},
        {"id": "gone_b", "name": "zeta", "item_count": 0},
    ]
    assert await repo.list_orphaned_inventories({"kept", "gone_a", "gone_b"}) == []


async def test_list_item_identifiers(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen")
    await repo.upsert_inventory("inv2", "Garage")
    oats = await repo.create_item("inv1", {FIELD_NAME: "Oatmeal"})
    milk = await repo.create_item("inv1", {FIELD_NAME: "Milk"})
    await repo.create_item("inv2", {FIELD_NAME: "Oil"})
    await repo.set_item_aliases(oats, "inv1", ["oats", "Porridge"])

    rows = await repo.list_item_identifiers("inv1")

    assert sorted(rows, key=lambda row: (row[1], row[2] or "")) == [
        (milk, "Milk", None),
        (oats, "Oatmeal", "Porridge"),
        (oats, "Oatmeal", "oats"),
    ]
    assert await repo.list_item_identifiers("missing") == []
