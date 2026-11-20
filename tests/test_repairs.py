"""Issue registry detectors and repair flows, against a real config-entry setup."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import aiosqlite
import pytest
from homeassistant.components.repairs import repairs_flow_manager
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component

from custom_components.simple_inventory.const import (
    DOMAIN,
    FIELD_AUTO_ADD_ENABLED,
    FIELD_AUTO_ADD_TO_LIST_QUANTITY,
    FIELD_NAME,
    FIELD_QUANTITY,
    FIELD_TODO_LIST,
)
from custom_components.simple_inventory.storage.repository import SCHEMA_VERSION

from .harness import (
    FakeTodo,
    add_entry,
    integration_env,
    open_database,
    seed_items,
    setup_entry,
)

KITCHEN = "kitchen_entry"
MISSING = "todo.gone"


def _missing_issue_id(entity_id: str = MISSING, entry_id: str = KITCHEN) -> str:
    return f"missing_todo_list_{entry_id}_{entity_id}"


def _issue(hass: HomeAssistant, issue_id: str) -> ir.IssueEntry | None:
    return ir.async_get(hass).async_get_issue(DOMAIN, issue_id)


def _state(entry: ConfigEntry) -> ConfigEntryState:
    """Read through a call so mypy does not keep the attribute narrowed across awaits."""
    return entry.state


def _item(name: str, todo_list: str = MISSING, **extra: Any) -> dict[str, Any]:
    return {
        FIELD_NAME: name,
        FIELD_QUANTITY: 0,
        FIELD_AUTO_ADD_ENABLED: True,
        FIELD_AUTO_ADD_TO_LIST_QUANTITY: 1,
        FIELD_TODO_LIST: todo_list,
        **extra,
    }


@pytest.fixture
async def env(
    hass: HomeAssistant, tmp_path: Path, enable_custom_integrations: None
) -> AsyncGenerator[HomeAssistant, None]:
    async with integration_env(hass, tmp_path) as hass_env:
        assert await async_setup_component(hass_env, "repairs", {})
        yield hass_env


@pytest.fixture
def todo(env: HomeAssistant) -> FakeTodo:
    fake = FakeTodo(env)
    fake.register()
    fake.add_list("todo.grocery")
    return fake


async def _start_fix(hass: HomeAssistant, issue_id: str) -> dict[str, Any]:
    manager = repairs_flow_manager(hass)
    assert manager is not None
    return dict(await manager.async_init(DOMAIN, data={"issue_id": issue_id}))


async def _configure(hass: HomeAssistant, flow_id: str, user_input: dict[str, Any]) -> dict:
    manager = repairs_flow_manager(hass)
    assert manager is not None
    return dict(await manager.async_configure(flow_id, user_input))


async def _items(hass: HomeAssistant, inventory_id: str = KITCHEN) -> dict[str, dict[str, Any]]:
    async with open_database(hass) as repository:
        return {
            item[FIELD_NAME]: item
            for item in await repository.list_items_with_details(inventory_id)
        }


# --- missing todo list: detection ----------------------------------------------------


async def test_missing_todo_list_issue_created_at_setup(env: HomeAssistant, todo: FakeTodo) -> None:
    await seed_items(
        env,
        KITCHEN,
        "Kitchen",
        [_item("Milk"), _item("Eggs"), _item("Bread", todo_list="todo.grocery")],
    )
    entry = add_entry(env, KITCHEN, "Kitchen")

    await setup_entry(env, entry)

    issue = _issue(env, _missing_issue_id())
    assert issue is not None
    assert issue.is_fixable is True
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_key == "missing_todo_list"
    assert issue.translation_placeholders == {
        "entity_id": MISSING,
        "inventory": "Kitchen",
        "count": "2",
    }
    assert issue.data == {"entry_id": KITCHEN, "entity_id": MISSING}
    assert _issue(env, _missing_issue_id("todo.grocery")) is None


async def test_missing_todo_list_issue_names_the_entry_by_its_title(
    env: HomeAssistant, todo: FakeTodo
) -> None:
    """Renaming an entry in HA's UI changes only its title; the issue shows that title."""
    await seed_items(env, KITCHEN, "Kitchen", [_item("Milk")])
    entry = add_entry(env, KITCHEN, "Kitchen")
    env.config_entries.async_update_entry(entry, title="Main Kitchen")

    await setup_entry(env, entry)

    issue = _issue(env, _missing_issue_id())
    assert issue is not None
    assert issue.translation_placeholders is not None
    assert issue.translation_placeholders["inventory"] == "Main Kitchen"


def _register_todo(hass: HomeAssistant, object_id: str) -> str:
    """Registry-only todo entity (no state), as a todo integration has at startup."""
    entry = er.async_get(hass).async_get_or_create(
        "todo", "local_todo", object_id, suggested_object_id=object_id
    )
    assert entry.entity_id == f"todo.{object_id}"
    return entry.entity_id


async def test_registered_todo_entity_without_state_is_not_missing(env: HomeAssistant) -> None:
    """At startup a todo integration may not have restored its state yet."""
    chores = _register_todo(env, "chores")
    await seed_items(env, KITCHEN, "Kitchen", [_item("Soap", todo_list=chores)])
    entry = add_entry(env, KITCHEN, "Kitchen")

    await setup_entry(env, entry)

    assert list(ir.async_get(env).issues) == []


async def test_missing_todo_list_issue_cleared_at_setup_when_resolved(
    env: HomeAssistant, todo: FakeTodo
) -> None:
    await seed_items(env, KITCHEN, "Kitchen", [_item("Milk")])
    entry = add_entry(env, KITCHEN, "Kitchen")
    await setup_entry(env, entry)
    assert _issue(env, _missing_issue_id()) is not None

    todo.add_list(MISSING)
    await env.config_entries.async_reload(entry.entry_id)
    await env.async_block_till_done()

    assert _issue(env, _missing_issue_id()) is None


async def test_todo_entity_registry_removal_creates_issue_and_recreate_clears_it(
    env: HomeAssistant,
) -> None:
    registry = er.async_get(env)
    chores = _register_todo(env, "chores")
    spare = _register_todo(env, "spare")
    registry.async_get_or_create("sensor", "demo", "temp", suggested_object_id="temp")
    await seed_items(env, KITCHEN, "Kitchen", [_item("Soap", todo_list=chores)])
    entry = add_entry(env, KITCHEN, "Kitchen")
    await setup_entry(env, entry)
    assert list(ir.async_get(env).issues) == []

    registry.async_remove("sensor.temp")
    registry.async_remove(spare)  # referenced by no item
    await env.async_block_till_done()
    assert list(ir.async_get(env).issues) == []

    registry.async_remove(chores)
    await env.async_block_till_done()
    issue = _issue(env, _missing_issue_id(chores))
    assert issue is not None
    assert issue.translation_placeholders is not None
    assert issue.translation_placeholders["count"] == "1"

    _register_todo(env, "chores")
    await env.async_block_till_done()
    assert _issue(env, _missing_issue_id(chores)) is None


async def test_todo_entity_rename_flags_the_old_entity_id(env: HomeAssistant) -> None:
    chores = _register_todo(env, "chores")
    await seed_items(env, KITCHEN, "Kitchen", [_item("Soap", todo_list=chores)])
    entry = add_entry(env, KITCHEN, "Kitchen")
    await setup_entry(env, entry)

    er.async_get(env).async_update_entity(chores, new_entity_id="todo.housework")
    await env.async_block_till_done()

    assert _issue(env, _missing_issue_id(chores)) is not None


async def test_unloaded_entry_stops_listening_for_registry_removals(env: HomeAssistant) -> None:
    chores = _register_todo(env, "chores")
    await seed_items(env, KITCHEN, "Kitchen", [_item("Soap", todo_list=chores)])
    entry = add_entry(env, KITCHEN, "Kitchen")
    await setup_entry(env, entry)
    await env.config_entries.async_unload(entry.entry_id)

    er.async_get(env).async_remove(chores)
    await env.async_block_till_done()

    assert list(ir.async_get(env).issues) == []


async def test_removing_entry_deletes_its_missing_todo_issues(
    env: HomeAssistant, todo: FakeTodo
) -> None:
    await seed_items(env, KITCHEN, "Kitchen", [_item("Milk")])
    entry = add_entry(env, KITCHEN, "Kitchen")
    await setup_entry(env, entry)
    assert _issue(env, _missing_issue_id()) is not None

    await env.config_entries.async_remove(entry.entry_id)
    await env.async_block_till_done()

    assert _issue(env, _missing_issue_id()) is None


# --- missing todo list: repair flow --------------------------------------------------


async def test_missing_todo_fix_flow_replaces_list_and_resyncs(
    env: HomeAssistant, todo: FakeTodo
) -> None:
    await seed_items(
        env,
        KITCHEN,
        "Kitchen",
        [_item("Milk"), _item("Eggs"), _item("Salt", todo_list="todo.grocery", quantity=5)],
    )
    entry = add_entry(env, KITCHEN, "Kitchen")
    await setup_entry(env, entry)

    result = await _start_fix(env, _missing_issue_id())
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "init"
    assert result["menu_options"] == ["replace", "clear"]
    assert result["description_placeholders"] == {
        "entity_id": MISSING,
        "inventory": "Kitchen",
        "count": "2",
    }

    result = await _configure(env, result["flow_id"], {"next_step_id": "replace"})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "replace"

    result = await _configure(env, result["flow_id"], {"todo_list": "todo.grocery"})
    assert result["type"] is FlowResultType.CREATE_ENTRY

    items = await _items(env)
    assert {name: item[FIELD_TODO_LIST] for name, item in items.items()} == {
        "Milk": "todo.grocery",
        "Eggs": "todo.grocery",
        "Salt": "todo.grocery",
    }
    assert items["Milk"][FIELD_AUTO_ADD_ENABLED] is True
    # Out-of-stock auto-add items land on the replacement list (todo sync ran).
    assert sorted(todo.summaries("todo.grocery")) == ["Eggs (x2)", "Milk (x2)"]
    assert _issue(env, _missing_issue_id()) is None


async def test_missing_todo_fix_flow_rejects_missing_replacement(
    env: HomeAssistant, todo: FakeTodo
) -> None:
    await seed_items(env, KITCHEN, "Kitchen", [_item("Milk")])
    entry = add_entry(env, KITCHEN, "Kitchen")
    await setup_entry(env, entry)

    result = await _start_fix(env, _missing_issue_id())
    result = await _configure(env, result["flow_id"], {"next_step_id": "replace"})
    result = await _configure(env, result["flow_id"], {"todo_list": "todo.nowhere"})

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"todo_list": "invalid_todo_list"}
    assert (await _items(env))["Milk"][FIELD_TODO_LIST] == MISSING


async def test_missing_todo_fix_flow_clear_disables_auto_add(
    env: HomeAssistant, todo: FakeTodo
) -> None:
    await seed_items(
        env, KITCHEN, "Kitchen", [_item("Milk"), _item("Bread", todo_list="todo.grocery")]
    )
    entry = add_entry(env, KITCHEN, "Kitchen")
    await setup_entry(env, entry)

    result = await _start_fix(env, _missing_issue_id())
    result = await _configure(env, result["flow_id"], {"next_step_id": "clear"})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "clear"
    result = await _configure(env, result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY

    items = await _items(env)
    assert items["Milk"][FIELD_TODO_LIST] == ""
    assert items["Milk"][FIELD_AUTO_ADD_ENABLED] is False
    assert items["Bread"][FIELD_TODO_LIST] == "todo.grocery"
    assert items["Bread"][FIELD_AUTO_ADD_ENABLED] is True
    assert _issue(env, _missing_issue_id()) is None


async def test_missing_todo_fix_flow_finishes_when_already_resolved(
    env: HomeAssistant, todo: FakeTodo
) -> None:
    await seed_items(env, KITCHEN, "Kitchen", [_item("Milk")])
    entry = add_entry(env, KITCHEN, "Kitchen")
    await setup_entry(env, entry)
    await env.services.async_call(
        DOMAIN,
        "update_item",
        {"inventory_id": KITCHEN, "old_name": "Milk", "name": "Milk", "todo_list": "todo.grocery"},
        blocking=True,
    )

    result = await _start_fix(env, _missing_issue_id())

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert _issue(env, _missing_issue_id()) is None


async def test_missing_todo_fix_flow_aborts_when_inventory_not_loaded(
    env: HomeAssistant, todo: FakeTodo
) -> None:
    await seed_items(env, KITCHEN, "Kitchen", [_item("Milk")])
    entry = add_entry(env, KITCHEN, "Kitchen")
    await setup_entry(env, entry)
    await env.config_entries.async_unload(entry.entry_id)

    result = await _start_fix(env, _missing_issue_id())

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "inventory_not_loaded"
    assert _issue(env, _missing_issue_id()) is not None


# --- database from a newer version ---------------------------------------------------


async def _set_schema_version(hass: HomeAssistant, version: int) -> None:
    """Raw write: the repository refuses to open a database from a newer version."""
    async with aiosqlite.connect(hass.config.path("simple_inventory.db")) as conn:
        await conn.execute(
            "UPDATE metadata SET value = ? WHERE key = 'schema_version'", (str(version),)
        )
        await conn.commit()


async def test_newer_database_fails_setup_with_issue_then_clears(env: HomeAssistant) -> None:
    await seed_items(env, KITCHEN, "Kitchen", [_item("Milk", todo_list="")])
    await _set_schema_version(env, SCHEMA_VERSION + 1)
    entry = add_entry(env, KITCHEN, "Kitchen")

    await setup_entry(env, entry)

    assert _state(entry) is ConfigEntryState.SETUP_ERROR
    issue = _issue(env, "database_from_newer_version")
    assert issue is not None
    assert issue.is_fixable is False
    assert issue.severity is ir.IssueSeverity.ERROR
    assert issue.translation_key == "database_from_newer_version"
    assert issue.translation_placeholders == {
        "found_version": str(SCHEMA_VERSION + 1),
        "supported_version": str(SCHEMA_VERSION),
    }

    await _set_schema_version(env, SCHEMA_VERSION)
    await env.config_entries.async_reload(entry.entry_id)
    await env.async_block_till_done()

    assert _state(entry) is ConfigEntryState.LOADED
    assert _issue(env, "database_from_newer_version") is None
    assert "Milk" in await _items(env)


async def test_migration_failure_fails_setup_with_issue(env: HomeAssistant) -> None:
    await seed_items(env, KITCHEN, "Kitchen", [_item("Milk", todo_list="")])
    await _set_schema_version(env, 2)
    entry = add_entry(env, KITCHEN, "Kitchen")

    with patch(
        "custom_components.simple_inventory.storage.repository."
        "InventoryRepository._migrate_to_v3",
        side_effect=RuntimeError("boom"),
    ):
        await setup_entry(env, entry)

    assert _state(entry) is ConfigEntryState.SETUP_ERROR
    issue = _issue(env, "migration_failed")
    assert issue is not None
    assert issue.is_fixable is True
    assert issue.severity is ir.IssueSeverity.ERROR
    assert issue.translation_key == "migration_failed"
    assert issue.translation_placeholders == {
        "found_version": "2",
        "supported_version": str(SCHEMA_VERSION),
    }


async def test_migration_failed_repair_flow_restores_and_reloads(env: HomeAssistant) -> None:
    await seed_items(env, KITCHEN, "Kitchen", [_item("Milk", todo_list="")])
    await _set_schema_version(env, 2)
    entry = add_entry(env, KITCHEN, "Kitchen")

    with patch(
        "custom_components.simple_inventory.storage.repository."
        "InventoryRepository._migrate_to_v3",
        side_effect=RuntimeError("boom"),
    ):
        await setup_entry(env, entry)
    assert _state(entry) is ConfigEntryState.SETUP_ERROR

    flow = await _start_fix(env, "migration_failed")
    result = await _configure(env, flow["flow_id"], {})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert _issue(env, "migration_failed") is None

    await env.async_block_till_done()
    assert _state(entry) is ConfigEntryState.LOADED
    assert "Milk" in await _items(env)


async def test_migration_failed_repair_flow_handles_a_repeat_failure(env: HomeAssistant) -> None:
    """A still-failing migration must not crash the flow before the confirm form is shown.

    Regression test: ``async_step_confirm`` used to reopen the repository via
    ``async_initialize()`` (which re-runs the migration) just to list snapshots. With a
    deterministic migration failure, that raised ``SchemaMigrationError`` again, crashing
    the repair flow before the user ever saw the confirm form. The patch stays active
    through both setup AND the flow calls below to pin that it no longer does: the first
    call must show the confirm form (not crash), and confirming - where the restore's
    reopen hits the still-failing migration again - must abort with a translated reason
    instead of crashing.
    """
    await seed_items(env, KITCHEN, "Kitchen", [_item("Milk", todo_list="")])
    await _set_schema_version(env, 2)
    entry = add_entry(env, KITCHEN, "Kitchen")

    with patch(
        "custom_components.simple_inventory.storage.repository."
        "InventoryRepository._migrate_to_v3",
        side_effect=RuntimeError("boom"),
    ):
        await setup_entry(env, entry)
        assert _state(entry) is ConfigEntryState.SETUP_ERROR

        flow = await _start_fix(env, "migration_failed")
        assert flow["type"] is FlowResultType.FORM
        assert flow["step_id"] == "confirm"

        result = await _configure(env, flow["flow_id"], {})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "restore_failed"


async def test_migration_failed_repair_flow_aborts_with_no_snapshot(env: HomeAssistant) -> None:
    # Directly create the issue without a real failed migration, so backups/ is empty. A
    # normal, successful setup first loads the integration so its repairs platform (and
    # thus this fix flow) is registered.
    await seed_items(env, KITCHEN, "Kitchen", [_item("Milk", todo_list="")])
    entry = add_entry(env, KITCHEN, "Kitchen")
    await setup_entry(env, entry)

    from custom_components.simple_inventory.repairs import async_create_migration_failed_issue
    from custom_components.simple_inventory.storage.repository import SchemaMigrationError

    async_create_migration_failed_issue(env, SchemaMigrationError(2, 6, RuntimeError("boom")))

    flow = await _start_fix(env, "migration_failed")

    assert flow["type"] is FlowResultType.ABORT
    assert flow["reason"] == "no_snapshot_available"


async def test_migration_failed_repair_flow_aborts_cleanly_when_listing_snapshots_fails(
    env: HomeAssistant,
) -> None:
    """Listing pre-migration snapshots is pure filesystem access (mkdir + glob) and can
    raise ``OSError`` on a corrupted/unwritable backups directory. That must abort the
    flow with the same translated ``restore_failed`` reason as a failed restore, not
    crash with an unhandled exception before the confirm form (or on confirm) is shown.
    """
    await seed_items(env, KITCHEN, "Kitchen", [_item("Milk", todo_list="")])
    entry = add_entry(env, KITCHEN, "Kitchen")
    await setup_entry(env, entry)

    from custom_components.simple_inventory.repairs import async_create_migration_failed_issue
    from custom_components.simple_inventory.storage.repository import SchemaMigrationError

    async_create_migration_failed_issue(env, SchemaMigrationError(2, 6, RuntimeError("boom")))

    with patch(
        "custom_components.simple_inventory.storage.repository."
        "InventoryRepository.pre_migration_snapshots",
        side_effect=OSError("backups/ is not writable"),
    ):
        flow = await _start_fix(env, "migration_failed")

    assert flow["type"] is FlowResultType.ABORT
    assert flow["reason"] == "restore_failed"
    assert "backups/ is not writable" in flow["description_placeholders"]["error"]


# --- orphaned inventory data ---------------------------------------------------------


async def _seed_orphans(hass: HomeAssistant) -> None:
    await seed_items(hass, "ghost", "Old Garage", [{FIELD_NAME: "Oil"}, {FIELD_NAME: "Rags"}])
    await seed_items(hass, "ghost_2", "Attic", [])


async def test_orphaned_inventory_issue_created_at_setup(env: HomeAssistant) -> None:
    await _seed_orphans(env)
    entry = add_entry(env, KITCHEN, "Kitchen")

    await setup_entry(env, entry)

    issue = _issue(env, "orphaned_inventory_data")
    assert issue is not None
    assert issue.is_fixable is True
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_key == "orphaned_inventory_data"
    assert issue.translation_placeholders == {"inventories": "- Attic: 0\n- Old Garage: 2"}


async def test_no_orphan_issue_for_configured_inventories(env: HomeAssistant) -> None:
    await seed_items(env, KITCHEN, "Kitchen", [{FIELD_NAME: "Salt"}])
    kitchen = add_entry(env, KITCHEN, "Kitchen")
    global_entry = add_entry(env, "global_entry", "All Items Expiring Soon", "global")

    await setup_entry(env, kitchen)
    await setup_entry(env, global_entry)

    assert _issue(env, "orphaned_inventory_data") is None


async def test_orphaned_inventory_issue_cleared_at_setup_when_resolved(
    env: HomeAssistant,
) -> None:
    await seed_items(env, "ghost", "Old Garage", [{FIELD_NAME: "Oil"}])
    kitchen = add_entry(env, KITCHEN, "Kitchen")
    await setup_entry(env, kitchen)
    assert _issue(env, "orphaned_inventory_data") is not None

    await setup_entry(env, add_entry(env, "ghost", "Old Garage"))

    assert _issue(env, "orphaned_inventory_data") is None


async def test_orphaned_inventory_fix_flow_deletes_orphans_only(env: HomeAssistant) -> None:
    await _seed_orphans(env)
    await seed_items(env, KITCHEN, "Kitchen", [{FIELD_NAME: "Salt"}])
    entry = add_entry(env, KITCHEN, "Kitchen")
    await setup_entry(env, entry)

    result = await _start_fix(env, "orphaned_inventory_data")
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm"
    assert result["description_placeholders"] == {"inventories": "- Attic: 0\n- Old Garage: 2"}

    result = await _configure(env, result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY

    async with open_database(env) as repository:
        assert [inv["id"] for inv in await repository.list_inventories()] == [KITCHEN]
        assert await repository.list_items_with_details("ghost") == []
    assert "Salt" in await _items(env)
    assert _issue(env, "orphaned_inventory_data") is None


async def test_orphaned_inventory_fix_flow_aborts_without_loaded_inventory(
    env: HomeAssistant,
) -> None:
    await _seed_orphans(env)
    entry = add_entry(env, KITCHEN, "Kitchen")
    await setup_entry(env, entry)
    await env.config_entries.async_unload(entry.entry_id)

    result = await _start_fix(env, "orphaned_inventory_data")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_loaded"
    assert _issue(env, "orphaned_inventory_data") is not None


# --- translations --------------------------------------------------------------------

_TRANSLATIONS = Path(__file__).parent.parent / "custom_components" / DOMAIN / "translations"


def _flatten(node: Any, prefix: str = "") -> dict[str, str]:
    if isinstance(node, dict):
        flat: dict[str, str] = {}
        for key, value in node.items():
            flat.update(_flatten(value, f"{prefix}.{key}" if prefix else key))
        return flat
    return {prefix: node}


@pytest.mark.parametrize("locale", ["es", "fr", "sl"])
def test_issue_translations_match_english(locale: str) -> None:
    """Same keys as en.json, and every string keeps exactly the English placeholders."""

    def issues(name: str) -> dict[str, str]:
        return _flatten(json.loads((_TRANSLATIONS / f"{name}.json").read_text())["issues"])

    english, translated = issues("en"), issues(locale)

    assert translated.keys() == english.keys()
    for key, text in english.items():
        assert set(re.findall(r"{(\w+)}", translated[key])) == set(
            re.findall(r"{(\w+)}", text)
        ), key


def test_issue_translations_cover_every_issue_and_step() -> None:
    issues = json.loads((_TRANSLATIONS / "en.json").read_text())["issues"]

    assert issues["database_from_newer_version"].keys() == {"title", "description"}
    missing = issues["missing_todo_list"]["fix_flow"]
    assert missing["step"].keys() == {"init", "replace", "clear"}
    assert missing["step"]["init"]["menu_options"].keys() == {"replace", "clear"}
    assert missing["error"].keys() == {"invalid_todo_list"}
    assert missing["abort"].keys() == {"inventory_not_loaded"}
    orphaned = issues["orphaned_inventory_data"]["fix_flow"]
    assert orphaned["step"].keys() == {"confirm"}
    assert orphaned["abort"].keys() == {"not_loaded"}
