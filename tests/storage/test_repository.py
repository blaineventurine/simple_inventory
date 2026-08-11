from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

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
from custom_components.simple_inventory.storage.repository import InventoryRepository


@pytest.fixture
def hass_with_tmp_config(hass: HomeAssistant, tmp_path: Path) -> HomeAssistant:
    hass.config.config_dir = str(tmp_path)

    def _path(*parts: str) -> str:
        return str(tmp_path.joinpath(*parts))

    hass.config.path = _path  # type: ignore[method-assign]
    return hass


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
            FIELD_QUANTITY: 2,
            FIELD_UNIT: "L",
            FIELD_DESCRIPTION: "Whole milk",
            FIELD_EXPIRY_DATE: "",
            FIELD_EXPIRY_ALERT_DAYS: 0,
            FIELD_AUTO_ADD_ENABLED: False,
            FIELD_AUTO_ADD_TO_LIST_QUANTITY: 0,
            FIELD_TODO_LIST: "",
            "auto_add_id_to_description_enabled": False,
        },
    )

    item = await repo.get_item_by_name("inv1", "milk")
    assert item is not None
    assert item["id"] == item_id
    assert item[FIELD_NAME] == "Milk"
    assert item[FIELD_QUANTITY] == 2


@pytest.mark.asyncio
async def test_create_item_merges_on_name_conflict(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)

    first_id = await repo.create_item(
        "inv1",
        {FIELD_NAME: "Milk", FIELD_QUANTITY: 2, FIELD_DESCRIPTION: "", FIELD_UNIT: ""},
    )
    second_id = await repo.create_item(
        "inv1",
        {FIELD_NAME: "milk", FIELD_QUANTITY: 3, FIELD_DESCRIPTION: "desc", FIELD_UNIT: "L"},
    )

    # Should merge into one row; returned id should be the existing row id
    assert second_id == first_id

    item = await repo.get_item_by_name("inv1", "MILK")
    assert item is not None
    assert item[FIELD_QUANTITY] == 5
    assert item[FIELD_UNIT] == "L"
    assert item[FIELD_DESCRIPTION] == "desc"


@pytest.mark.asyncio
async def test_update_item_updates_fields(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)

    item_id = await repo.create_item("inv1", {FIELD_NAME: "Bread", FIELD_QUANTITY: 1})
    ok = await repo.update_item(item_id, {FIELD_QUANTITY: 5, FIELD_UNIT: "loaf"})
    assert ok is True

    item = await repo.get_item_by_name("inv1", "bread")
    assert item is not None
    assert item[FIELD_QUANTITY] == 5
    assert item[FIELD_UNIT] == "loaf"


@pytest.mark.asyncio
async def test_delete_item_cascades_links(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)

    item_id = await repo.create_item("inv1", {FIELD_NAME: "Milk", FIELD_QUANTITY: 2})

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
async def test_list_items_expiring_before(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    today = date.today()

    await repo.create_item(
        "inv1",
        {
            FIELD_NAME: "Soon",
            FIELD_QUANTITY: 1,
            FIELD_EXPIRY_DATE: (today + timedelta(days=1)).isoformat(),
            FIELD_EXPIRY_ALERT_DAYS: 7,
        },
    )
    await repo.create_item(
        "inv1",
        {
            FIELD_NAME: "Later",
            FIELD_QUANTITY: 1,
            FIELD_EXPIRY_DATE: (today + timedelta(days=60)).isoformat(),
            FIELD_EXPIRY_ALERT_DAYS: 7,
        },
    )
    await repo.create_item(
        "inv1",
        {
            FIELD_NAME: "ZeroQty",
            FIELD_QUANTITY: 0,
            FIELD_EXPIRY_DATE: (today + timedelta(days=1)).isoformat(),
            FIELD_EXPIRY_ALERT_DAYS: 7,
        },
    )

    results = await repo.list_items_expiring_before(today + timedelta(days=7), inventory_id="inv1")
    names = [r[FIELD_NAME] for r in results]
    assert "Soon" in names
    assert "Later" not in names
    assert "ZeroQty" not in names


@pytest.mark.asyncio
async def test_list_items_with_auto_add_condition(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)

    await repo.create_item(
        "inv1",
        {
            FIELD_NAME: "Eligible",
            FIELD_QUANTITY: 1,
            FIELD_AUTO_ADD_ENABLED: True,
            FIELD_AUTO_ADD_TO_LIST_QUANTITY: 2,
            FIELD_TODO_LIST: "todo.shopping",
        },
    )
    await repo.create_item(
        "inv1",
        {
            FIELD_NAME: "NotEnabled",
            FIELD_QUANTITY: 1,
            FIELD_AUTO_ADD_ENABLED: False,
            FIELD_AUTO_ADD_TO_LIST_QUANTITY: 2,
            FIELD_TODO_LIST: "todo.shopping",
        },
    )
    await repo.create_item(
        "inv1",
        {
            FIELD_NAME: "NoTodoList",
            FIELD_QUANTITY: 1,
            FIELD_AUTO_ADD_ENABLED: True,
            FIELD_AUTO_ADD_TO_LIST_QUANTITY: 2,
            FIELD_TODO_LIST: "",
        },
    )
    await repo.create_item(
        "inv1",
        {
            FIELD_NAME: "TooMuchQty",
            FIELD_QUANTITY: 10,
            FIELD_AUTO_ADD_ENABLED: True,
            FIELD_AUTO_ADD_TO_LIST_QUANTITY: 2,
            FIELD_TODO_LIST: "todo.shopping",
        },
    )

    rows = await repo.list_items_with_auto_add_condition(inventory_id="inv1")
    assert [r[FIELD_NAME] for r in rows] == ["Eligible"]


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
async def test_schema_version_mismatch_raises(hass_with_tmp_config: HomeAssistant) -> None:
    # Create a fresh DB file and manually set schema_version to something else
    repository = InventoryRepository(hass_with_tmp_config, db_filename="bad_schema.db")
    await repository.async_initialize()

    conn = repository._connection()
    await conn.execute(
        "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
        ("schema_version", "999"),
    )
    await conn.commit()

    await repository.async_close()

    # Re-open; ensure_schema_version should raise
    repository2 = InventoryRepository(hass_with_tmp_config, db_filename="bad_schema.db")
    with pytest.raises(RuntimeError, match="Database schema version"):
        await repository2.async_initialize()
    await repository2.async_close()


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
async def test_get_location_item_counts_aggregates(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    item_a = await repo.create_item("inv1", {FIELD_NAME: "Milk", FIELD_QUANTITY: 5})
    item_b = await repo.create_item("inv1", {FIELD_NAME: "Bread", FIELD_QUANTITY: 2})

    fridge = await repo.ensure_location("inv1", "Fridge")
    pantry = await repo.ensure_location("inv1", "Pantry")

    await repo.set_item_locations(item_a, [fridge, pantry])
    await repo.set_item_locations(item_b, [fridge])

    counts = await repo.get_location_item_counts("inv1")
    assert counts == {"Fridge": 2, "Pantry": 1}


@pytest.mark.asyncio
async def test_decimal_quantity_round_trip(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)

    item_id = await repo.create_item(
        "inv1",
        {
            FIELD_NAME: "Bacon",
            FIELD_QUANTITY: 0.5,
            FIELD_UNIT: "packs",
            FIELD_AUTO_ADD_TO_LIST_QUANTITY: 1.5,
        },
    )

    item = await repo.get_item_by_name("inv1", "Bacon")
    assert item is not None
    assert item[FIELD_QUANTITY] == 0.5
    assert item[FIELD_AUTO_ADD_TO_LIST_QUANTITY] == 1.5

    # Update with decimal
    ok = await repo.update_item(item_id, {FIELD_QUANTITY: 2.75})
    assert ok is True

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
async def test_get_category_counts_aggregates(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    a = await repo.create_item("inv1", {FIELD_NAME: "Milk", FIELD_QUANTITY: 1})
    b = await repo.create_item("inv1", {FIELD_NAME: "Bread", FIELD_QUANTITY: 1})

    dairy = await repo.ensure_category("Dairy")
    bakery = await repo.ensure_category("Bakery")

    await repo.set_item_categories(a, [dairy])
    await repo.set_item_categories(b, [bakery])

    counts = await repo.get_category_counts("inv1")
    assert counts == {"Dairy": 1, "Bakery": 1}


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

    # list_items_with_auto_add_condition
    auto_items = await repo.list_items_with_auto_add_condition(inventory_id="inv1")
    assert len(auto_items) == 1
    assert auto_items[0][FIELD_DESIRED_QUANTITY] == 10.0

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
    item_id = await repo.create_item("inv1", {FIELD_NAME: "Milk", FIELD_QUANTITY: 2})

    await repo.add_item_barcode(item_id, "inv1", "123456789012")

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

    await repo.add_item_barcode(item1, "inv1", "SAME-BARCODE")
    await repo.add_item_barcode(item2, "inv2", "SAME-BARCODE")

    result1 = await repo.get_item_by_barcode("inv1", "SAME-BARCODE")
    result2 = await repo.get_item_by_barcode("inv2", "SAME-BARCODE")

    assert result1 is not None
    assert result2 is not None
    assert result1["id"] == item1
    assert result2["id"] == item2


@pytest.mark.asyncio
async def test_barcode_duplicate_in_same_inventory_fails(repo: InventoryRepository) -> None:
    """Same barcode on two different items in one inventory should fail."""
    import aiosqlite

    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    item1 = await repo.create_item("inv1", {FIELD_NAME: "Milk", FIELD_QUANTITY: 1})
    item2 = await repo.create_item("inv1", {FIELD_NAME: "Bread", FIELD_QUANTITY: 1})

    await repo.add_item_barcode(item1, "inv1", "DUPE-BC")

    with pytest.raises(aiosqlite.IntegrityError):
        await repo.add_item_barcode(item2, "inv1", "DUPE-BC")


@pytest.mark.asyncio
async def test_multiple_barcodes_per_item(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    item_id = await repo.create_item("inv1", {FIELD_NAME: "Milk", FIELD_QUANTITY: 1})

    await repo.add_item_barcode(item_id, "inv1", "BC-001")
    await repo.add_item_barcode(item_id, "inv1", "BC-002")

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

    await repo.add_item_barcode(item_id, "inv1", "BC-A")
    await repo.add_item_barcode(item_id, "inv1", "BC-B")

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

    await repo.add_item_barcode(item_id, "inv1", "CASCADE-BC")

    await repo.delete_item(item_id)

    # Barcode should be gone
    result = await repo.get_item_by_barcode("inv1", "CASCADE-BC")
    assert result is None


@pytest.mark.asyncio
async def test_get_barcodes_for_item(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    item_id = await repo.create_item("inv1", {FIELD_NAME: "Milk", FIELD_QUANTITY: 1})

    await repo.add_item_barcode(item_id, "inv1", "ZZZ")
    await repo.add_item_barcode(item_id, "inv1", "AAA")

    barcodes = await repo.get_barcodes_for_item(item_id)
    assert barcodes == ["AAA", "ZZZ"]  # sorted


@pytest.mark.asyncio
async def test_get_barcodes_for_item_empty(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    item_id = await repo.create_item("inv1", {FIELD_NAME: "Bread", FIELD_QUANTITY: 1})

    barcodes = await repo.get_barcodes_for_item(item_id)
    assert barcodes == []


@pytest.mark.asyncio
async def test_remove_item_barcode(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    item_id = await repo.create_item("inv1", {FIELD_NAME: "Milk", FIELD_QUANTITY: 1})

    await repo.add_item_barcode(item_id, "inv1", "REMOVE-ME")

    barcodes = await repo.get_barcodes_for_item(item_id)
    assert "REMOVE-ME" in barcodes

    await repo.remove_item_barcode(item_id, "REMOVE-ME")

    barcodes = await repo.get_barcodes_for_item(item_id)
    assert "REMOVE-ME" not in barcodes


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
    import aiosqlite

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
        # Verify schema version is now 3
        conn = repo._connection()
        cursor = await conn.execute("SELECT value FROM metadata WHERE key = 'schema_version'")
        row = await cursor.fetchone()
        await cursor.close()
        assert row is not None
        assert int(row[0]) == 3

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
    finally:
        await repo.async_close()


# --- Feature: Global barcode lookup and set_item_barcodes ---


@pytest.mark.asyncio
async def test_get_item_by_barcode_global(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    await repo.upsert_inventory("inv2", "Pantry", "", "", "", None)

    item1 = await repo.create_item("inv1", {FIELD_NAME: "Milk", FIELD_QUANTITY: 1})
    item2 = await repo.create_item("inv2", {FIELD_NAME: "Milk 2L", FIELD_QUANTITY: 2})

    await repo.add_item_barcode(item1, "inv1", "GLOBAL-BC")
    await repo.add_item_barcode(item2, "inv2", "GLOBAL-BC")

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


@pytest.mark.asyncio
async def test_set_item_barcodes_replaces_all(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    item_id = await repo.create_item("inv1", {FIELD_NAME: "Milk", FIELD_QUANTITY: 1})

    await repo.add_item_barcode(item_id, "inv1", "OLD-BC-1")
    await repo.add_item_barcode(item_id, "inv1", "OLD-BC-2")

    barcodes = await repo.get_barcodes_for_item(item_id)
    assert len(barcodes) == 2

    await repo.set_item_barcodes(item_id, "inv1", ["NEW-BC-A", "NEW-BC-B", "NEW-BC-C"])

    barcodes = await repo.get_barcodes_for_item(item_id)
    assert sorted(barcodes) == ["NEW-BC-A", "NEW-BC-B", "NEW-BC-C"]


@pytest.mark.asyncio
async def test_set_item_barcodes_empty_clears(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    item_id = await repo.create_item("inv1", {FIELD_NAME: "Milk", FIELD_QUANTITY: 1})

    await repo.add_item_barcode(item_id, "inv1", "BC-1")
    assert len(await repo.get_barcodes_for_item(item_id)) == 1

    await repo.set_item_barcodes(item_id, "inv1", [])
    assert await repo.get_barcodes_for_item(item_id) == []


@pytest.mark.asyncio
async def test_set_item_aliases_replaces_all(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    item_id = await repo.create_item("inv1", {FIELD_NAME: "Oatmeal", FIELD_QUANTITY: 1})

    await repo.set_item_aliases(item_id, "inv1", ["oats", "hot cereal"])
    aliases = await repo.get_aliases_for_item(item_id)
    assert sorted(aliases) == ["hot cereal", "oats"]

    await repo.set_item_aliases(item_id, "inv1", ["steel-cut oats"])
    aliases = await repo.get_aliases_for_item(item_id)
    assert aliases == ["steel-cut oats"]


@pytest.mark.asyncio
async def test_set_item_aliases_empty_clears(repo: InventoryRepository) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    item_id = await repo.create_item("inv1", {FIELD_NAME: "Oatmeal", FIELD_QUANTITY: 1})

    await repo.set_item_aliases(item_id, "inv1", ["oats"])
    assert len(await repo.get_aliases_for_item(item_id)) == 1

    await repo.set_item_aliases(item_id, "inv1", [])
    assert await repo.get_aliases_for_item(item_id) == []


@pytest.mark.asyncio
async def test_set_item_aliases_duplicate_across_items_raises(repo: InventoryRepository) -> None:
    """Two different items in the same inventory cannot share an alias."""
    import aiosqlite

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

    assert await repo.get_aliases_for_item(item_id) == []

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
async def test_adjust_item_quantity_concurrent_increments_are_atomic(
    repo: InventoryRepository,
) -> None:
    """Concurrent adjust_item_quantity calls on the same item must not lose
    updates: the single-lock critical section serializes the read-modify-write,
    so N concurrent +1 deltas must land as N distinct, non-overlapping steps.
    """
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "", None)
    item_id = await repo.create_item("inv1", {FIELD_NAME: "Milk", FIELD_QUANTITY: 10})

    results = await asyncio.gather(*(repo.adjust_item_quantity(item_id, 1) for _ in range(10)))

    assert all(result is not None for result in results)
    pairs = sorted((before, after) for before, after in results)  # type: ignore[misc]
    for (_before, after), (next_before, _next_after) in zip(pairs, pairs[1:]):
        assert after == next_before

    item = await repo.get_item_by_name("inv1", "milk")
    assert item is not None
    assert item[FIELD_QUANTITY] == 20  # 10 + 10 * 1, no lost updates
