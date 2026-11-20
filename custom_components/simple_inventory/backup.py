"""HA backup platform hooks (loaded by filename via Integration.async_get_platform).

WAL-mode SQLite needs its write-ahead log folded into the main file before a
file-level backup copies it, or the copy can miss recent writes. HA's full-system
backup already includes `<config>/simple_inventory.db` and
`<config>/simple_inventory/` (images, snapshots) since both sit under `/config`;
this checkpoints immediately before the backup so writes already made land in the
main file rather than the WAL. Writes made DURING the backup still go to the WAL,
which HA also captures, so the file pair stays restorable either way.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant

from .data import get_repository

_LOGGER = logging.getLogger(__name__)


async def async_pre_backup(hass: HomeAssistant) -> None:
    """Checkpoint the WAL so the on-disk DB file is more complete before a backup.

    Never raises: HA aborts the whole backup when any platform's hook fails, and a
    backup that still carries ``simple_inventory.db`` plus its ``-wal`` file beats no
    backup at all.
    """
    repository = get_repository(hass)
    if repository is None:
        return
    try:
        await repository.async_checkpoint()
    except Exception:  # the checkpoint is best-effort; never veto HA's backup
        _LOGGER.warning(
            "Could not checkpoint the Simple Inventory database before the backup; "
            "the backup still contains the database and its WAL file",
            exc_info=True,
        )


async def async_post_backup(hass: HomeAssistant) -> None:
    """Nothing to undo: WAL mode resumes normally on the next write."""
