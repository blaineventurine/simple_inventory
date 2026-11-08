"""backup_database / restore_database services, against a real config-entry setup."""

from __future__ import annotations

from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from custom_components.simple_inventory.const import DOMAIN

from ..error_assertions import assert_translated_error
from ..harness import add_entry, integration_env, setup_entry

KITCHEN = "kitchen_entry"


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


async def test_restore_database_round_trips(
    hass: HomeAssistant, tmp_path: Path, enable_custom_integrations: None
) -> None:
    async with integration_env(hass, tmp_path) as env:
        entry = add_entry(env, KITCHEN, "Kitchen")
        await setup_entry(env, entry)

        backup = await env.services.async_call(
            DOMAIN, "backup_database", {}, blocking=True, return_response=True
        )

        result = await env.services.async_call(
            DOMAIN, "restore_database", {}, blocking=True, return_response=True
        )

        assert result is not None
        assert backup is not None
        assert result["restored_from"] == backup["snapshot"]
