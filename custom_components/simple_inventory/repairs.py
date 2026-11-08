"""Repair issues (detection) and their fix flows for Simple Inventory.

Issues:
- ``missing_todo_list_{entry_id}_{entity_id}``: items point at a todo entity that no
  longer exists. Fixable: pick a replacement list or clear the list (disables auto-add).
- ``database_from_newer_version``: the database was written by a newer release.
  Not fixable from here; setup fails with ``ConfigEntryError``.
- ``orphaned_inventory_data``: inventories whose config entry no longer exists.
  Fixable: delete their data.
- ``voice_sentences_outdated``: an edited custom_sentences file still lets any words name
  an inventory (raised by voice_sentences.py). Not fixable from here.

Issues are re-evaluated at every entry setup; a resolved condition deletes its issue.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow, RepairsFlowResult
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.selector import EntitySelector, EntitySelectorConfig
from homeassistant.helpers.start import async_at_started

from .const import (
    DOMAIN,
    EVENT_UPDATED,
    FIELD_AUTO_ADD_ENABLED,
    FIELD_NAME,
    FIELD_TODO_LIST,
    SERVICE_UPDATE_ITEM,
)
from .data import get_coordinators, get_hub, get_repository
from .storage.images import async_delete_inventory_with_images
from .storage.repository import (
    DatabaseFromNewerVersionError,
    InventoryRepository,
    SchemaMigrationError,
)

_LOGGER = logging.getLogger(__name__)

ISSUE_DATABASE_FROM_NEWER_VERSION = "database_from_newer_version"
ISSUE_ORPHANED_INVENTORY_DATA = "orphaned_inventory_data"
ISSUE_MISSING_TODO_LIST = "missing_todo_list"
ISSUE_MIGRATION_FAILED = "migration_failed"
ISSUE_PANEL_BUNDLE_MISSING = "panel_bundle_missing"
ISSUE_VOICE_SENTENCES_OUTDATED = "voice_sentences_outdated"

_TODO_PREFIX = "todo."
CONF_TODO_LIST = "todo_list"


def missing_todo_list_issue_id(entry_id: str, entity_id: str) -> str:
    return f"{ISSUE_MISSING_TODO_LIST}_{entry_id}_{entity_id}"


def todo_list_exists(hass: HomeAssistant, entity_id: str) -> bool:
    """A todo entity exists if it has a state or a registry entry.

    The registry entry covers startup, before the todo integration restores its state.
    """
    return (
        hass.states.get(entity_id) is not None
        or er.async_get(hass).async_get(entity_id) is not None
    )


# --- database from a newer version ---------------------------------------------------


@callback
def async_create_newer_database_issue(
    hass: HomeAssistant, error: DatabaseFromNewerVersionError
) -> None:
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_DATABASE_FROM_NEWER_VERSION,
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key=ISSUE_DATABASE_FROM_NEWER_VERSION,
        translation_placeholders={
            "found_version": str(error.found),
            "supported_version": str(error.expected),
        },
    )


@callback
def async_delete_newer_database_issue(hass: HomeAssistant) -> None:
    ir.async_delete_issue(hass, DOMAIN, ISSUE_DATABASE_FROM_NEWER_VERSION)


# --- schema migration failed ----------------------------------------------------------


@callback
def async_create_migration_failed_issue(hass: HomeAssistant, error: SchemaMigrationError) -> None:
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_MIGRATION_FAILED,
        is_fixable=True,
        severity=ir.IssueSeverity.ERROR,
        translation_key=ISSUE_MIGRATION_FAILED,
        translation_placeholders={
            "found_version": str(error.found),
            "supported_version": str(error.expected),
        },
    )


@callback
def async_delete_migration_failed_issue(hass: HomeAssistant) -> None:
    ir.async_delete_issue(hass, DOMAIN, ISSUE_MIGRATION_FAILED)


# --- sidebar panel bundle missing --------------------------------------------------


@callback
def async_create_panel_bundle_missing_issue(hass: HomeAssistant, path: str) -> None:
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_PANEL_BUNDLE_MISSING,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_PANEL_BUNDLE_MISSING,
        translation_placeholders={"path": path},
    )


@callback
def async_delete_panel_bundle_missing_issue(hass: HomeAssistant) -> None:
    ir.async_delete_issue(hass, DOMAIN, ISSUE_PANEL_BUNDLE_MISSING)


# --- edited custom sentences in the old (wildcard inventory) format -----------------


@callback
def async_create_voice_sentences_outdated_issue(hass: HomeAssistant, paths: list[str]) -> None:
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_VOICE_SENTENCES_OUTDATED,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_VOICE_SENTENCES_OUTDATED,
        translation_placeholders={"paths": ", ".join(paths)},
    )


@callback
def async_delete_voice_sentences_outdated_issue(hass: HomeAssistant) -> None:
    ir.async_delete_issue(hass, DOMAIN, ISSUE_VOICE_SENTENCES_OUTDATED)


# --- detection at setup and on entity registry changes -------------------------------


@callback
def async_setup_issue_detection(
    hass: HomeAssistant, entry: ConfigEntry, repository: InventoryRepository
) -> None:
    """Evaluate this entry's issues once HA has started; watch for todo entity removals.

    Waiting for startup lets todo entities without a registry entry appear first.
    Everything is torn down with the entry.
    """

    @callback
    def _evaluate(_hass: HomeAssistant) -> None:
        entry.async_create_task(
            hass,
            _async_evaluate_issues(hass, entry, repository),
            f"{DOMAIN} issue evaluation {entry.entry_id}",
        )

    entry.async_on_unload(async_at_started(hass, _evaluate))

    @callback
    def _is_todo_change(data: er.EventEntityRegistryUpdatedData) -> bool:
        if data["action"] == "update":
            return data.get("old_entity_id", "").startswith(_TODO_PREFIX)
        return data["entity_id"].startswith(_TODO_PREFIX)

    async def _on_todo_change(event: Event[er.EventEntityRegistryUpdatedData]) -> None:
        data = event.data
        if data["action"] == "create":
            ir.async_delete_issue(
                hass, DOMAIN, missing_todo_list_issue_id(entry.entry_id, data["entity_id"])
            )
            return
        # "remove", or "update" renaming the entity: the old id is gone.
        gone = data["entity_id"] if data["action"] == "remove" else data["old_entity_id"]
        count = (await repository.get_todo_list_references(entry.entry_id)).get(gone, 0)
        if count:
            _async_create_missing_todo_issue(hass, entry, gone, count)

    entry.async_on_unload(
        hass.bus.async_listen(
            er.EVENT_ENTITY_REGISTRY_UPDATED, _on_todo_change, event_filter=_is_todo_change
        )
    )


async def _async_evaluate_issues(
    hass: HomeAssistant, entry: ConfigEntry, repository: InventoryRepository
) -> None:
    await _async_check_missing_todo_lists(hass, entry, repository)
    await _async_check_orphaned_inventories(hass, repository)


async def _async_check_missing_todo_lists(
    hass: HomeAssistant, entry: ConfigEntry, repository: InventoryRepository
) -> None:
    references = await repository.get_todo_list_references(entry.entry_id)
    missing = {
        entity_id: count
        for entity_id, count in references.items()
        if not todo_list_exists(hass, entity_id)
    }

    prefix = missing_todo_list_issue_id(entry.entry_id, "")
    for domain, issue_id in list(ir.async_get(hass).issues):
        if (
            domain == DOMAIN
            and issue_id.startswith(prefix)
            and issue_id[len(prefix) :] not in missing
        ):
            ir.async_delete_issue(hass, DOMAIN, issue_id)

    for entity_id, count in missing.items():
        _async_create_missing_todo_issue(hass, entry, entity_id, count)


@callback
def _async_create_missing_todo_issue(
    hass: HomeAssistant, entry: ConfigEntry, entity_id: str, count: int
) -> None:
    ir.async_create_issue(
        hass,
        DOMAIN,
        missing_todo_list_issue_id(entry.entry_id, entity_id),
        data={"entry_id": entry.entry_id, "entity_id": entity_id},
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_MISSING_TODO_LIST,
        translation_placeholders={
            "entity_id": entity_id,
            "inventory": entry.title,
            "count": str(count),
        },
    )


async def _async_check_orphaned_inventories(
    hass: HomeAssistant, repository: InventoryRepository
) -> None:
    known_ids = {entry.entry_id for entry in hass.config_entries.async_entries(DOMAIN)}
    orphans = await repository.list_orphaned_inventories(known_ids)
    if not orphans:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_ORPHANED_INVENTORY_DATA)
        return

    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_ORPHANED_INVENTORY_DATA,
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_ORPHANED_INVENTORY_DATA,
        translation_placeholders={
            "inventories": "\n".join(
                f"- {orphan['name']}: {orphan['item_count']}" for orphan in orphans
            )
        },
    )


@callback
def async_delete_entry_issues(hass: HomeAssistant, entry_id: str) -> None:
    """Drop the issues tied to a removed config entry."""
    prefix = missing_todo_list_issue_id(entry_id, "")
    for domain, issue_id in list(ir.async_get(hass).issues):
        if domain == DOMAIN and issue_id.startswith(prefix):
            ir.async_delete_issue(hass, DOMAIN, issue_id)


# --- fix flows -----------------------------------------------------------------------


class MissingTodoListRepairFlow(RepairsFlow):
    """Point the affected items at another todo list, or clear their list.

    Items are changed through the ``update_item`` service so the coordinator records the
    change, fires its events, and the todo list is resynced exactly as for a user edit.
    """

    def __init__(self, entry_id: str, entity_id: str) -> None:
        self._entry_id = entry_id
        self._entity_id = entity_id

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> RepairsFlowResult:
        affected = await self._affected_item_names()
        if affected is None:
            return self.async_abort(
                reason="inventory_not_loaded", description_placeholders=self._placeholders()
            )
        if not affected:
            return self.async_create_entry(data={})  # resolved meanwhile
        return self.async_show_menu(
            step_id="init",
            menu_options=["replace", "clear"],
            description_placeholders=self._placeholders(len(affected)),
        )

    async def async_step_replace(
        self, user_input: dict[str, Any] | None = None
    ) -> RepairsFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            replacement = str(user_input[CONF_TODO_LIST])
            if replacement != self._entity_id and todo_list_exists(self.hass, replacement):
                return await self._async_update_items({FIELD_TODO_LIST: replacement})
            errors[CONF_TODO_LIST] = "invalid_todo_list"

        return self.async_show_form(
            step_id="replace",
            data_schema=vol.Schema(
                {vol.Required(CONF_TODO_LIST): EntitySelector(EntitySelectorConfig(domain="todo"))}
            ),
            errors=errors,
            description_placeholders=self._placeholders(),
        )

    async def async_step_clear(self, user_input: dict[str, Any] | None = None) -> RepairsFlowResult:
        if user_input is not None:
            return await self._async_update_items(
                {FIELD_TODO_LIST: "", FIELD_AUTO_ADD_ENABLED: False}
            )
        return self.async_show_form(
            step_id="clear",
            data_schema=vol.Schema({}),
            description_placeholders=self._placeholders(),
        )

    async def _async_update_items(self, changes: dict[str, Any]) -> RepairsFlowResult:
        affected = await self._affected_item_names()
        if affected is None:
            return self.async_abort(
                reason="inventory_not_loaded", description_placeholders=self._placeholders()
            )
        for name in affected:
            await self.hass.services.async_call(
                DOMAIN,
                SERVICE_UPDATE_ITEM,
                {"inventory_id": self._entry_id, "old_name": name, FIELD_NAME: name, **changes},
                blocking=True,
            )
        return self.async_create_entry(data={})

    async def _affected_item_names(self) -> list[str] | None:
        """Names of the items still pointing at the missing list; None if not loaded."""
        coordinator = get_coordinators(self.hass).get(self._entry_id)
        if coordinator is None:
            return None
        items = await coordinator.async_list_items(self._entry_id)
        return [
            str(item[FIELD_NAME]) for item in items if item.get(FIELD_TODO_LIST) == self._entity_id
        ]

    def _placeholders(self, count: int | None = None) -> dict[str, str]:
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        placeholders = {
            "entity_id": self._entity_id,
            "inventory": entry.title if entry else self._entry_id,
        }
        if count is not None:
            placeholders["count"] = str(count)
        return placeholders


class OrphanedInventoryRepairFlow(ConfirmRepairFlow):
    """Confirm, then delete every inventory that has no config entry."""

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        repository = get_repository(self.hass)
        if repository is None:
            return self.async_abort(reason="not_loaded")
        if user_input is None:
            return await super().async_step_confirm()

        known_ids = {entry.entry_id for entry in self.hass.config_entries.async_entries(DOMAIN)}
        for orphan in await repository.list_orphaned_inventories(known_ids):
            await async_delete_inventory_with_images(self.hass, repository, orphan["id"])
            _LOGGER.info("Deleted data of removed inventory %s", orphan["name"])
        # Deleted through the repository, not a coordinator: drop the hub's cached
        # all-inventories entries too. Global sensors and unfiltered WS subscribers may list
        # the deleted items until the event.
        if (hub := get_hub(self.hass)) is not None:
            hub.invalidate(None)
        self.hass.bus.async_fire(EVENT_UPDATED)
        return self.async_create_entry(data={})


class MigrationFailedRepairFlow(ConfirmRepairFlow):
    """Confirm, then restore the newest pre-migration snapshot and reload every entry."""

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        repository = InventoryRepository(self.hass)
        await repository.async_initialize()
        try:
            snapshots = sorted(
                repository._backups_dir().glob("pre_migration_v*.db"),
                key=lambda p: int(p.stem.rpartition("_")[2]),
            )
            if not snapshots:
                return self.async_abort(reason="no_snapshot_available")
            if user_input is None:
                return await super().async_step_confirm()

            await repository.async_restore(snapshots[-1].name)
        finally:
            await repository.async_close()

        async_delete_migration_failed_issue(self.hass)
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            self.hass.config_entries.async_schedule_reload(entry.entry_id)
        return self.async_create_entry(data={})


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create the fix flow for a fixable Simple Inventory issue."""
    if issue_id == ISSUE_MIGRATION_FAILED:
        return MigrationFailedRepairFlow()
    if issue_id == ISSUE_ORPHANED_INVENTORY_DATA:
        return OrphanedInventoryRepairFlow()
    if issue_id.startswith(f"{ISSUE_MISSING_TODO_LIST}_") and data:
        return MissingTodoListRepairFlow(str(data["entry_id"]), str(data["entity_id"]))
    return ConfirmRepairFlow()
