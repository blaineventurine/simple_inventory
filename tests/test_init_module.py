"""Tests for custom_components.simple_inventory.__init__ (integration setup/unload)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.simple_inventory import async_setup_entry, async_unload_entry
from custom_components.simple_inventory.const import (
    DOMAIN,
    SERVICE_ADD_ITEM,
    SERVICE_DECREMENT_ITEM,
    SERVICE_GET_ALL_ITEMS,
    SERVICE_GET_INVENTORY_CONSUMPTION_RATES,
    SERVICE_GET_ITEM_CONSUMPTION_RATES,
    SERVICE_GET_ITEMS,
    SERVICE_INCREMENT_ITEM,
    SERVICE_LOOKUP_BARCODE_PRODUCT,
    SERVICE_LOOKUP_BY_BARCODE,
    SERVICE_REMOVE_ITEM,
    SERVICE_SCAN_BARCODE,
    SERVICE_UPDATE_ITEM,
)


@pytest.fixture
def hass_mock() -> MagicMock:
    hass = MagicMock()
    hass.data = {}

    hass.services = MagicMock()
    hass.services.async_register = MagicMock()
    hass.services.async_remove = MagicMock()
    hass.services.has_service = MagicMock(return_value=True)

    hass.config_entries = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.config_entries.async_entries = MagicMock(return_value=[])

    hass.config_entries.flow = MagicMock()
    hass.config_entries.flow.async_init = AsyncMock()

    # default; individual tests override when needed
    hass.async_create_task = MagicMock(side_effect=lambda coro: asyncio.create_task(coro))
    return hass


@pytest.fixture
def entry1() -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "inv_1"
    entry.title = "Kitchen"
    entry.data = {"name": "Kitchen", "entry_type": "inventory", "create_global": False}
    return entry


@pytest.fixture
def entry2() -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "inv_2"
    entry.title = "Pantry"
    entry.data = {"name": "Pantry", "entry_type": "inventory", "create_global": False}
    return entry


@pytest.mark.asyncio
async def test_async_setup_entry_first_creates_repo_and_registers_services(
    hass_mock: MagicMock, entry1: MagicMock
) -> None:
    hass_mock.async_create_task = MagicMock(side_effect=lambda coro: asyncio.create_task(coro))

    with (
        patch("custom_components.simple_inventory.InventoryRepository") as repo_cls,
        patch("custom_components.simple_inventory.SimpleInventoryCoordinator") as coord_cls,
        patch("custom_components.simple_inventory.TodoManager") as todo_cls,
        patch("custom_components.simple_inventory.ServiceHandler") as handler_cls,
    ):
        repo = repo_cls.return_value
        repo.async_initialize = AsyncMock()
        repo.async_close = AsyncMock()

        coord = coord_cls.return_value
        coord.async_initialize = AsyncMock()
        coord.async_unload = AsyncMock()
        coord.async_upsert_inventory_metadata = AsyncMock()

        todo_cls.return_value = MagicMock()

        handler = handler_cls.return_value
        handler.async_update_item = AsyncMock()
        handler.async_add_item = AsyncMock()
        handler.async_remove_item = AsyncMock()
        handler.async_increment_item = AsyncMock()
        handler.async_decrement_item = AsyncMock()
        handler.async_get_items = AsyncMock()
        handler.async_get_items_from_all_inventories = AsyncMock()

        ok = await async_setup_entry(hass_mock, entry1)
        assert ok is True

        # Repo created and scheduled
        repo_cls.assert_called_once_with(hass_mock)
        repo.async_initialize.assert_called_once()
        hass_mock.async_create_task.assert_called_once()

        # repository_task should be cleared after awaiting
        assert hass_mock.data[DOMAIN]["repository_task"] is None

        # Coordinator created and initialized
        coord_cls.assert_called_once()
        coord.async_initialize.assert_awaited_once()
        coord.async_upsert_inventory_metadata.assert_awaited_once()

        # Services registered once
        registered_names = {c.args[1] for c in hass_mock.services.async_register.call_args_list}
        assert registered_names == {
            SERVICE_UPDATE_ITEM,
            SERVICE_ADD_ITEM,
            SERVICE_REMOVE_ITEM,
            SERVICE_INCREMENT_ITEM,
            SERVICE_DECREMENT_ITEM,
            SERVICE_GET_ITEMS,
            SERVICE_GET_ALL_ITEMS,
            SERVICE_GET_INVENTORY_CONSUMPTION_RATES,
            SERVICE_GET_ITEM_CONSUMPTION_RATES,
            SERVICE_LOOKUP_BARCODE_PRODUCT,
            SERVICE_LOOKUP_BY_BARCODE,
            SERVICE_SCAN_BARCODE,
        }

        # Domain data contains coordinator
        assert DOMAIN in hass_mock.data
        assert entry1.entry_id in hass_mock.data[DOMAIN]["coordinators"]


@pytest.mark.asyncio
async def test_async_setup_entry_second_does_not_reregister_services(
    hass_mock: MagicMock, entry1: MagicMock, entry2: MagicMock
) -> None:
    hass_mock.async_create_task = MagicMock(side_effect=lambda coro: asyncio.create_task(coro))

    with (
        patch("custom_components.simple_inventory.InventoryRepository") as repo_cls,
        patch("custom_components.simple_inventory.SimpleInventoryCoordinator") as coord_cls,
        patch("custom_components.simple_inventory.TodoManager"),
        patch("custom_components.simple_inventory.ServiceHandler") as handler_cls,
    ):
        repo = repo_cls.return_value
        repo.async_initialize = AsyncMock()

        coord = coord_cls.return_value
        coord.async_initialize = AsyncMock()
        coord.async_upsert_inventory_metadata = AsyncMock()

        handler = handler_cls.return_value
        handler.async_update_item = AsyncMock()
        handler.async_add_item = AsyncMock()
        handler.async_remove_item = AsyncMock()
        handler.async_increment_item = AsyncMock()
        handler.async_decrement_item = AsyncMock()
        handler.async_get_items = AsyncMock()
        handler.async_get_items_from_all_inventories = AsyncMock()

        await async_setup_entry(hass_mock, entry1)
        calls_after_first = hass_mock.services.async_register.call_count

        await async_setup_entry(hass_mock, entry2)
        calls_after_second = hass_mock.services.async_register.call_count

        assert calls_after_second == calls_after_first


@pytest.mark.asyncio
async def test_async_setup_entry_create_global_triggers_flow(
    hass_mock: MagicMock, entry1: MagicMock
) -> None:
    entry1.data["create_global"] = True
    hass_mock.async_create_task = MagicMock(side_effect=lambda coro: asyncio.create_task(coro))

    hass_mock.config_entries.async_entries = MagicMock(return_value=[])

    with (
        patch("custom_components.simple_inventory.InventoryRepository") as repo_cls,
        patch("custom_components.simple_inventory.SimpleInventoryCoordinator") as coord_cls,
        patch("custom_components.simple_inventory.TodoManager"),
        patch("custom_components.simple_inventory.ServiceHandler"),
    ):
        repo_cls.return_value.async_initialize = AsyncMock()
        coord_cls.return_value.async_initialize = AsyncMock()
        coord_cls.return_value.async_upsert_inventory_metadata = AsyncMock()

        await async_setup_entry(hass_mock, entry1)

        hass_mock.config_entries.flow.async_init.assert_awaited_once()
        _, kwargs = hass_mock.config_entries.flow.async_init.call_args
        assert kwargs["data"]["entry_type"] == "global"


@pytest.mark.asyncio
async def test_async_unload_entry_non_last_keeps_services_and_repo(
    hass_mock: MagicMock, entry1: MagicMock, entry2: MagicMock
) -> None:
    coord1 = MagicMock()
    coord1.async_unload = AsyncMock()
    coord2 = MagicMock()
    coord2.async_unload = AsyncMock()
    repo = MagicMock()
    repo.async_close = AsyncMock()

    hass_mock.data[DOMAIN] = {
        "coordinators": {entry1.entry_id: coord1, entry2.entry_id: coord2},
        "services_registered": True,
        "repository": repo,
    }

    ok = await async_unload_entry(hass_mock, entry1)
    assert ok is True

    hass_mock.services.async_remove.assert_not_called()
    repo.async_close.assert_not_awaited()
    assert entry2.entry_id in hass_mock.data[DOMAIN]["coordinators"]


@pytest.mark.asyncio
async def test_async_unload_entry_last_removes_services_and_closes_repo(
    hass_mock: MagicMock, entry1: MagicMock
) -> None:
    coord = MagicMock()
    coord.async_unload = AsyncMock()
    repo = MagicMock()
    repo.async_close = AsyncMock()

    hass_mock.data[DOMAIN] = {
        "coordinators": {entry1.entry_id: coord},
        "services_registered": True,
        "repository": repo,
    }

    ok = await async_unload_entry(hass_mock, entry1)
    assert ok is True

    removed_names = {c.args[1] for c in hass_mock.services.async_remove.call_args_list}
    assert removed_names == {
        SERVICE_ADD_ITEM,
        SERVICE_DECREMENT_ITEM,
        SERVICE_INCREMENT_ITEM,
        SERVICE_REMOVE_ITEM,
        SERVICE_UPDATE_ITEM,
        SERVICE_GET_ITEMS,
        SERVICE_GET_ALL_ITEMS,
        SERVICE_GET_INVENTORY_CONSUMPTION_RATES,
        SERVICE_GET_ITEM_CONSUMPTION_RATES,
        SERVICE_LOOKUP_BARCODE_PRODUCT,
        SERVICE_LOOKUP_BY_BARCODE,
        SERVICE_SCAN_BARCODE,
    }

    repo.async_close.assert_awaited_once()
    assert DOMAIN not in hass_mock.data
