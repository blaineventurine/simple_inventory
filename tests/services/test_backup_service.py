"""backup_database / restore_database services, against a real config-entry setup."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from custom_components.simple_inventory.const import DOMAIN, FIELD_NAME
from custom_components.simple_inventory.storage.repository import InventoryRepository

from ..error_assertions import assert_translated_error
from ..harness import add_entry, integration_env, open_database, setup_entry

KITCHEN = "kitchen_entry"


async def _items(hass: HomeAssistant, inventory_id: str = KITCHEN) -> dict[str, dict[str, Any]]:
    async with open_database(hass) as repository:
        return {
            item[FIELD_NAME]: item
            for item in await repository.list_items_with_details(inventory_id)
        }


async def test_backup_database_returns_the_snapshot_name(
    hass: HomeAssistant, tmp_path: Path, enable_custom_integrations: None
) -> None:
    async with integration_env(hass, tmp_path) as env:
        entry = add_entry(env, KITCHEN, "Kitchen")
        await setup_entry(env, entry)

        result = await env.services.async_call(
            DOMAIN, "backup_database", {}, blocking=True, return_response=True
        )

        assert result is not None
        snapshot = result["snapshot"]
        assert isinstance(snapshot, str)
        assert snapshot.startswith("manual_")


async def test_restore_database_with_unknown_snapshot_raises(
    hass: HomeAssistant, tmp_path: Path, enable_custom_integrations: None
) -> None:
    async with integration_env(hass, tmp_path) as env:
        entry = add_entry(env, KITCHEN, "Kitchen")
        await setup_entry(env, entry)

        with pytest.raises(ServiceValidationError) as exc_info:
            await env.services.async_call(
                DOMAIN,
                "restore_database",
                {"snapshot": "no_such_file.db"},
                blocking=True,
                return_response=True,
            )
        assert_translated_error(exc_info.value, "snapshot_not_found", snapshot="no_such_file.db")


async def test_restore_database_with_empty_string_snapshot_restores_newest(
    hass: HomeAssistant, tmp_path: Path, enable_custom_integrations: None
) -> None:
    async with integration_env(hass, tmp_path) as env:
        entry = add_entry(env, KITCHEN, "Kitchen")
        await setup_entry(env, entry)
        backup = await env.services.async_call(
            DOMAIN, "backup_database", {}, blocking=True, return_response=True
        )

        result = await env.services.async_call(
            DOMAIN,
            "restore_database",
            {"snapshot": ""},
            blocking=True,
            return_response=True,
        )

        assert result is not None
        assert backup is not None
        assert result["restored_from"] == backup["snapshot"]


async def test_restore_database_round_trips(
    hass: HomeAssistant, tmp_path: Path, enable_custom_integrations: None
) -> None:
    async with integration_env(hass, tmp_path) as env:
        entry = add_entry(env, KITCHEN, "Kitchen")
        await setup_entry(env, entry)

        await env.services.async_call(
            DOMAIN,
            "add_item",
            {"inventory_id": KITCHEN, "name": "Milk", "quantity": 2},
            blocking=True,
        )
        await env.async_block_till_done()

        backup = await env.services.async_call(
            DOMAIN, "backup_database", {}, blocking=True, return_response=True
        )

        await env.services.async_call(
            DOMAIN,
            "add_item",
            {"inventory_id": KITCHEN, "name": "Eggs", "quantity": 1},
            blocking=True,
        )
        await env.async_block_till_done()
        assert "Eggs" in await _items(env, KITCHEN)

        result = await env.services.async_call(
            DOMAIN, "restore_database", {}, blocking=True, return_response=True
        )

        assert result is not None
        assert backup is not None
        assert result["restored_from"] == backup["snapshot"]

        await env.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED

        items = await _items(env, KITCHEN)
        assert "Milk" in items
        assert "Eggs" not in items


async def test_restore_database_reopen_failure_reloads_every_entry(
    hass: HomeAssistant, tmp_path: Path, enable_custom_integrations: None
) -> None:
    async with integration_env(hass, tmp_path) as env:
        entry = add_entry(env, KITCHEN, "Kitchen")
        await setup_entry(env, entry)

        await env.services.async_call(
            DOMAIN, "backup_database", {}, blocking=True, return_response=True
        )

        with (
            patch.object(
                InventoryRepository,
                "async_initialize",
                side_effect=RuntimeError("reopen boom"),
            ),
            patch.object(env.config_entries, "async_schedule_reload") as mock_reload,
            pytest.raises(ServiceValidationError) as exc_info,
        ):
            await env.services.async_call(
                DOMAIN,
                "restore_database",
                {},
                blocking=True,
                return_response=True,
            )

        assert_translated_error(exc_info.value, "restore_reopen_failed", error="reopen boom")
        assert mock_reload.call_count == len(env.config_entries.async_entries(DOMAIN))
        assert mock_reload.call_count >= 1
