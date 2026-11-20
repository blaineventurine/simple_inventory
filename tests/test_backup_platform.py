"""HA backup platform hooks: WAL checkpoint before a full-system backup."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import patch

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
    wal = Path(f"{repo._db_path}-wal")
    await repo.upsert_inventory("inv1", "Kitchen", "", "", "inventory", None)
    assert wal.stat().st_size > 0  # the write landed in the WAL, not the main file

    await async_pre_backup(hass_with_tmp_config)

    # TRUNCATE folds the WAL into the main file and empties it, so a file-level copy
    # of simple_inventory.db alone (what a tar-based backup captures) is complete.
    assert wal.stat().st_size == 0


async def test_pre_backup_does_not_raise_when_the_checkpoint_fails(
    hass_with_tmp_config: HomeAssistant,
    repo: InventoryRepository,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with patch.object(
        InventoryRepository,
        "async_checkpoint",
        side_effect=OSError("database table is locked"),
    ):
        await async_pre_backup(hass_with_tmp_config)

    assert "Could not checkpoint" in caplog.text


async def test_pre_backup_is_a_no_op_when_nothing_is_loaded(
    hass_with_tmp_config: HomeAssistant,
) -> None:
    # No repository set up at all: must not raise.
    await async_pre_backup(hass_with_tmp_config)


async def test_post_backup_is_a_no_op(hass_with_tmp_config: HomeAssistant) -> None:
    await async_post_backup(hass_with_tmp_config)
