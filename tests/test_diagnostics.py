"""Config entry diagnostics: shape, counts, and household-data redaction."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from custom_components.simple_inventory.const import (
    API_VERSION,
    DOMAIN,
    FIELD_AUTO_ADD_ENABLED,
    FIELD_AUTO_ADD_TO_LIST_QUANTITY,
    FIELD_DESCRIPTION,
    FIELD_NAME,
    FIELD_PRICE,
    FIELD_TODO_LIST,
)
from custom_components.simple_inventory.diagnostics import async_get_config_entry_diagnostics
from custom_components.simple_inventory.storage.repository import SCHEMA_VERSION

from .harness import FakeTodo, add_entry, integration_env, open_database, setup_entry

KITCHEN = "kitchen_entry"
SECRET = "ZZQSECRET"
SECRET_PRICE = 4242.17


@pytest.fixture
async def env(
    hass: HomeAssistant, tmp_path: Path, enable_custom_integrations: None
) -> AsyncGenerator[HomeAssistant, None]:
    async with integration_env(hass, tmp_path) as hass_env:
        yield hass_env


async def _seed_household(hass: HomeAssistant) -> None:
    """Items whose every free-text field carries SECRET; none may leak into diagnostics."""
    async with open_database(hass) as repository:
        await repository.upsert_inventory(KITCHEN, "Kitchen", entry_type="inventory")
        milk = await repository.create_item(
            KITCHEN,
            {
                FIELD_NAME: f"{SECRET} Milk",
                FIELD_DESCRIPTION: f"{SECRET} organic description",
                FIELD_PRICE: SECRET_PRICE,
                FIELD_AUTO_ADD_ENABLED: True,
                FIELD_AUTO_ADD_TO_LIST_QUANTITY: 1,
                FIELD_TODO_LIST: "todo.grocery",
            },
        )
        eggs = await repository.create_item(
            KITCHEN,
            {
                FIELD_NAME: f"{SECRET} Eggs",
                FIELD_PRICE: SECRET_PRICE,
                FIELD_TODO_LIST: "todo.gone",
            },
        )
        await repository.add_stock(eggs, KITCHEN, 6, purchased_at="2026-10-01")
        await repository.set_item_barcodes(milk, KITCHEN, [f"{SECRET}0001", f"{SECRET}0002"])
        await repository.set_item_aliases(eggs, KITCHEN, [f"{SECRET} alias"])
        fridge = await repository.ensure_location(KITCHEN, "Fridge")
        await repository.set_item_locations(milk, [fridge])
        await repository.set_item_categories(milk, [await repository.ensure_category("Dairy")])
        await repository.record_history_event(
            milk, KITCHEN, "increment", 1, 0, 1, price=SECRET_PRICE
        )
        await repository.set_barcode_provider_config({"provider": "openfoodfacts"})


async def test_inventory_diagnostics(env: HomeAssistant) -> None:
    todo = FakeTodo(env)
    todo.register()
    todo.add_list("todo.grocery")
    await _seed_household(env)
    entry = add_entry(env, KITCHEN, "Kitchen")
    env.config_entries.async_update_entry(
        entry,
        data={**entry.data, "icon": "mdi:fridge", "description": f"{SECRET} kitchen notes"},
    )
    await setup_entry(env, entry)

    diagnostics = await async_get_config_entry_diagnostics(env, entry)

    integration = await async_get_integration(env, DOMAIN)
    assert diagnostics == {
        "integration_version": str(integration.version),
        "api_version": API_VERSION,
        "schema_version": SCHEMA_VERSION,
        "legacy_migrated": True,
        "entry": {
            "entry_type": "inventory",
            "name": "Kitchen",
            "icon": "mdi:fridge",
            "has_description": True,
            "options": {},
            "state": "loaded",
        },
        "counts": {
            "items": 2,
            "items_out_of_stock": 1,
            "locations": 1,
            "categories": 1,
            "barcodes": 2,
            "aliases": 1,
            "history_events": 1,
        },
        "auto_add": {
            "enabled_items": 1,
            "todo_lists": [
                {
                    "entity_id": "todo.gone",
                    "items": 1,
                    "exists": False,
                    "supports_description": False,
                },
                {
                    "entity_id": "todo.grocery",
                    "items": 1,
                    "exists": True,
                    "supports_description": True,
                },
            ],
        },
        "barcode_provider": "openfoodfacts",
        "backups_count": 0,
        "newest_backup_age_seconds": None,
    }


async def test_diagnostics_never_contain_household_data(env: HomeAssistant) -> None:
    await _seed_household(env)
    entry = add_entry(env, KITCHEN, "Kitchen")
    await setup_entry(env, entry)

    dumped = json.dumps(await async_get_config_entry_diagnostics(env, entry))

    assert SECRET not in dumped
    assert str(SECRET_PRICE) not in dumped


async def test_global_diagnostics_list_inventory_entries(env: HomeAssistant) -> None:
    kitchen = add_entry(env, KITCHEN, "Kitchen")
    pantry = add_entry(env, "pantry_entry", "Pantry")
    global_entry = add_entry(env, "global_entry", "All Items Expiring Soon", "global")
    await setup_entry(env, kitchen)  # loads the domain: every entry is set up
    await env.config_entries.async_unload(pantry.entry_id)

    diagnostics: dict[str, Any] = await async_get_config_entry_diagnostics(env, global_entry)

    assert diagnostics["entry"]["entry_type"] == "global"
    assert diagnostics["inventories"] == [
        {"entry_id": KITCHEN, "name": "Kitchen", "state": "loaded"},
        {"entry_id": pantry.entry_id, "name": "Pantry", "state": "not_loaded"},
    ]
    assert "inventories" not in await async_get_config_entry_diagnostics(env, kitchen)


async def test_diagnostics_without_open_database(env: HomeAssistant) -> None:
    entry = add_entry(env, KITCHEN, "Kitchen")

    diagnostics = await async_get_config_entry_diagnostics(env, entry)

    assert diagnostics["entry"]["state"] == "not_loaded"
    assert diagnostics["schema_version"] is None
    assert diagnostics["counts"] is None
    assert diagnostics["auto_add"] is None
    assert diagnostics["barcode_provider"] is None
    assert diagnostics["backups_count"] is None
    assert diagnostics["newest_backup_age_seconds"] is None


async def test_diagnostics_report_backup_counts_without_filenames(env: HomeAssistant) -> None:
    entry = add_entry(env, KITCHEN, "Kitchen")
    await setup_entry(env, entry)
    from custom_components.simple_inventory.data import get_repository

    repository = get_repository(env)
    assert repository is not None
    await repository.async_snapshot("manual")
    await repository.async_snapshot("manual")

    result = await async_get_config_entry_diagnostics(env, entry)

    assert result["backups_count"] == 2
    assert result["newest_backup_age_seconds"] >= 0
    dumped = json.dumps(result)
    assert "manual_" not in dumped
