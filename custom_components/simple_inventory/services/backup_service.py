"""Domain-wide (non-inventory-scoped) backup/restore services.

Unlike every other service, these act on the single shared SQLite database, not one
inventory's coordinator - there is one repository for the whole integration.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util.json import JsonObjectType

from ..const import DOMAIN
from ..data import get_repository


class BackupService:
    """Handlers for backup_database and restore_database."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def async_backup_database(self, call: ServiceCall) -> JsonObjectType:
        """Snapshot the database on demand."""
        repository = get_repository(self.hass)
        if repository is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="no_inventories_configured"
            )
        path = await repository.async_snapshot("manual")
        return {"snapshot": path.name}

    async def async_restore_database(self, call: ServiceCall) -> JsonObjectType:
        """Restore a snapshot on demand, then reload every config entry."""
        repository = get_repository(self.hass)
        if repository is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="no_inventories_configured"
            )
        filename = call.data.get("snapshot") or None
        try:
            restored = await repository.async_restore(filename)
        except FileNotFoundError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="snapshot_not_found",
                translation_placeholders={"snapshot": filename or ""},
            ) from err
        except Exception as err:
            # The live file may already be replaced at this point (async_restore copies
            # before reopening) - reload every entry so the new repair issue (raised by
            # setup, e.g. migration_failed) actually reaches the user instead of leaving
            # coordinators silently stuck on a half-restored database.
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                self.hass.config_entries.async_schedule_reload(entry.entry_id)
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="restore_reopen_failed",
                translation_placeholders={"error": str(err)},
            ) from err

        for entry in self.hass.config_entries.async_entries(DOMAIN):
            self.hass.config_entries.async_schedule_reload(entry.entry_id)
        return {"restored_from": restored.name}
