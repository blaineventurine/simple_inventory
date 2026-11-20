"""Item icons in storage: schema v5 column, v4 -> v5 migration, read/write payloads."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import aiosqlite
import pytest
from homeassistant.core import HomeAssistant

from custom_components.simple_inventory.const import FIELD_ICON, FIELD_NAME
from custom_components.simple_inventory.storage.repository import (
    SCHEMA_VERSION,
    InventoryRepository,
)


@pytest.fixture
async def repo(hass_with_tmp_config: HomeAssistant) -> AsyncGenerator[InventoryRepository, None]:
    repository = InventoryRepository(hass_with_tmp_config, db_filename="icons.db")
    await repository.async_initialize()
    await repository.upsert_inventory("inv", "Kitchen")
    try:
        yield repository
    finally:
        await repository.async_close()


async def _icon_column(conn: aiosqlite.Connection) -> tuple[Any, ...] | None:
    """The ``PRAGMA table_info`` row of items.icon: (cid, name, type, notnull, default, pk)."""
    cursor = await conn.execute("PRAGMA table_info(items)")
    rows = await cursor.fetchall()
    await cursor.close()
    return next((tuple(row) for row in rows if row[1] == "icon"), None)


async def _stored_icon(repo: InventoryRepository, item_id: str) -> str:
    item = await repo.get_item_by_id(item_id)
    assert item is not None
    return str(item[FIELD_ICON])


async def test_fresh_database_has_icon_column(repo: InventoryRepository) -> None:
    column = await _icon_column(repo._connection())
    assert column is not None
    assert column[2:5] == ("TEXT", 1, "''")
    assert await repo.get_metadata_value("schema_version") == str(SCHEMA_VERSION)


async def test_v4_database_migrates_to_v5_with_empty_icons(
    hass_with_tmp_config: HomeAssistant,
) -> None:
    path = Path(hass_with_tmp_config.config.path("v4.db"))
    repo = InventoryRepository(hass_with_tmp_config, db_filename="v4.db")
    await repo.async_initialize()
    await repo.upsert_inventory("inv", "Kitchen")
    milk_id = await repo.create_item("inv", {FIELD_NAME: "Milk"})
    await repo.async_close()

    # Recreate a schema-4 database: items has no icon column.
    async with aiosqlite.connect(path) as db:
        await db.execute("ALTER TABLE items DROP COLUMN icon")
        await db.execute("UPDATE metadata SET value = '4' WHERE key = 'schema_version'")
        await db.commit()
        assert await _icon_column(db) is None

    repo = InventoryRepository(hass_with_tmp_config, db_filename="v4.db")
    await repo.async_initialize()
    try:
        assert await repo.get_metadata_value("schema_version") == str(SCHEMA_VERSION)
        column = await _icon_column(repo._connection())
        assert column is not None
        assert column[2:5] == ("TEXT", 1, "''")
        assert await _stored_icon(repo, milk_id) == ""
        [listed] = await repo.list_items_with_details("inv")
        assert listed[FIELD_ICON] == ""

        # Re-running the migration is a no-op and keeps stored icons.
        assert await repo.update_item(milk_id, {FIELD_ICON: "mdi:cup"})
        await repo._migrate_to_v5()
        await repo._migrate_to_v5()
        assert await _stored_icon(repo, milk_id) == "mdi:cup"
    finally:
        await repo.async_close()


async def test_create_item_without_icon_stores_empty_string(repo: InventoryRepository) -> None:
    item_id = await repo.create_item("inv", {FIELD_NAME: "Rice"})
    assert await _stored_icon(repo, item_id) == ""


async def test_update_item_sets_and_clears_icon(repo: InventoryRepository) -> None:
    item_id = await repo.create_item("inv", {FIELD_NAME: "Rice"})

    assert await repo.update_item(item_id, {FIELD_ICON: "mdi:rice"})
    assert await _stored_icon(repo, item_id) == "mdi:rice"

    assert await repo.update_item(item_id, {FIELD_ICON: ""})
    assert await _stored_icon(repo, item_id) == ""


async def test_every_item_reader_returns_icon(repo: InventoryRepository) -> None:
    item_id = await repo.create_item("inv", {FIELD_NAME: "Milk", FIELD_ICON: "mdi:cup"})
    await repo.set_item_barcodes(item_id, "inv", ["0123456789012"])

    by_name = await repo.get_item_by_name("inv", "milk")
    by_id = await repo.get_item_by_id(item_id)
    by_barcode = await repo.get_item_by_barcode("inv", "0123456789012")
    [global_hit] = await repo.get_item_by_barcode_global("0123456789012")
    [listed] = await repo.list_items_with_details("inv")

    for item in (by_name, by_id, by_barcode, global_hit, listed):
        assert item is not None
        assert item[FIELD_ICON] == "mdi:cup"
    # The barcode readers keep their column mapping intact around the new column.
    assert by_barcode is not None and by_barcode["updated_at"] == listed["updated_at"]
    assert global_hit["inventory_name"] == "Kitchen"
    assert global_hit["updated_at"] == listed["updated_at"]
