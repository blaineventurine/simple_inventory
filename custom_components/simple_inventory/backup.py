"""HA backup platform hooks (loaded by filename via Integration.async_get_platform).

WAL-mode SQLite needs its write-ahead log folded into the main file before a
file-level backup copies it, or the copy can miss recent writes. HA's full-system
backup already includes `<config>/simple_inventory.db` and
`<config>/simple_inventory/` (images, snapshots) since both sit under `/config` -
this just makes that capture consistent.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from .data import get_repository


async def async_pre_backup(hass: HomeAssistant) -> None:
    """Checkpoint the WAL so the on-disk DB file is self-contained before a backup."""
    repository = get_repository(hass)
    if repository is not None:
        await repository.async_checkpoint()


async def async_post_backup(hass: HomeAssistant) -> None:
    """Nothing to undo: WAL mode resumes normally on the next write."""
