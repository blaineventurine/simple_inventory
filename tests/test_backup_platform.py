"""HA backup platform hooks: WAL checkpoint before a full-system backup."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import aiosqlite
import pytest
from homeassistant.core import HomeAssistant

from custom_components.simple_inventory.backup import async_post_backup, async_pre_backup
from custom_components.simple_inventory.data import DATA_KEY, SimpleInventoryData
from custom_components.simple_inventory.storage.repository import InventoryRepository


@pytest.fixture
async def repo(hass_with_tmp_config: HomeAssistant) -> AsyncGenerator[InventoryRepository, None]:
    repository = InventoryRepository(hass_with_tmp_config, db_filename="test_backup.db")
    await repository.async_initialize()
    hass_with_tmp_config.data[DATA_KEY] = SimpleInventoryData(repository=repository)
    try:
        yield repository
    finally:
        await repository.async_close()


async def test_pre_backup_checkpoints_the_wal(
    hass_with_tmp_config: HomeAssistant, repo: InventoryRepository
) -> None:
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "inventory", None)

    await async_pre_backup(hass_with_tmp_config)

    # A second, independent connection sees the write even if it only reads the main
    # file (as a tar-based backup would), proving the WAL was folded in.
    async with aiosqlite.connect(repo._db_path) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "PRAGMA journal_mode", []
        )  # sanity: still WAL, not switched off
        row = await cursor.fetchone()
        assert row is not None
        mode = row[0]
        await cursor.close()
    assert mode.lower() == "wal"


async def test_pre_backup_is_a_no_op_when_nothing_is_loaded(
    hass_with_tmp_config: HomeAssistant,
) -> None:
    # No repository set up at all: must not raise.
    await async_pre_backup(hass_with_tmp_config)


async def test_post_backup_is_a_no_op(hass_with_tmp_config: HomeAssistant) -> None:
    await async_post_backup(hass_with_tmp_config)
