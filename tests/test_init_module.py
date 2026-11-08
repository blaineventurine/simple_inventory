"""Tests for custom_components.simple_inventory.__init__ (integration setup/unload)."""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady

from custom_components.simple_inventory import (
    async_remove_entry,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.simple_inventory.const import (
    DOMAIN,
    SERVICE_ADD_ITEM,
    SERVICE_BACKUP_DATABASE,
    SERVICE_CLEAR_ITEM_IMAGE,
    SERVICE_DECREMENT_ITEM,
    SERVICE_EXPORT,
    SERVICE_GET_ALL_ITEMS,
    SERVICE_GET_INVENTORY_CONSUMPTION_RATES,
    SERVICE_GET_ITEM_CONSUMPTION_RATES,
    SERVICE_GET_ITEMS,
    SERVICE_INCREMENT_ITEM,
    SERVICE_LOOKUP_BARCODE_PRODUCT,
    SERVICE_LOOKUP_BY_BARCODE,
    SERVICE_REMOVE_BATCH,
    SERVICE_REMOVE_ITEM,
    SERVICE_RESTORE_DATABASE,
    SERVICE_SCAN_BARCODE,
    SERVICE_SET_ITEM_IMAGE_FROM_BARCODE,
    SERVICE_SET_ITEM_IMAGE_FROM_MEDIA,
    SERVICE_TRANSFER_ITEM,
    SERVICE_UPDATE_BATCH,
    SERVICE_UPDATE_ITEM,
)
from custom_components.simple_inventory.data import SimpleInventoryData, get_repository
from custom_components.simple_inventory.storage.repository import DatabaseFromNewerVersionError


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


@pytest.fixture(autouse=True)
def issue_hooks() -> Generator[SimpleNamespace, None, None]:
    """Issue-registry hooks need a real hass; the mocked-hass tests assert on the calls."""
    module = "custom_components.simple_inventory"
    with (
        patch(f"{module}.async_create_newer_database_issue") as create_newer,
        patch(f"{module}.async_delete_newer_database_issue") as delete_newer,
        patch(f"{module}.async_setup_issue_detection") as setup_detection,
        patch(f"{module}.async_delete_entry_issues") as delete_entry_issues,
    ):
        yield SimpleNamespace(
            create_newer=create_newer,
            delete_newer=delete_newer,
            setup_detection=setup_detection,
            delete_entry_issues=delete_entry_issues,
        )


@pytest.fixture(autouse=True)
def sweep_images() -> Generator[AsyncMock, None, None]:
    """The startup image sweep needs a real repository; mocked-repo tests assert the call."""
    with patch(
        "custom_components.simple_inventory.async_sweep_orphan_images", new=AsyncMock()
    ) as sweep:
        yield sweep


@pytest.fixture(autouse=True)
def sync_voice_sentences() -> Generator[AsyncMock, None, None]:
    """The voice-sentence files need a real hass (test_voice_sentences.py covers them)."""
    with patch(
        "custom_components.simple_inventory.async_sync_voice_sentences", new=AsyncMock()
    ) as sync:
        yield sync


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
        patch("custom_components.simple_inventory.async_register_intents") as register_intents_mock,
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
        assert hass_mock.data[DOMAIN].repository_task is None

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
            SERVICE_UPDATE_BATCH,
            SERVICE_REMOVE_BATCH,
            SERVICE_TRANSFER_ITEM,
            SERVICE_SET_ITEM_IMAGE_FROM_BARCODE,
            SERVICE_SET_ITEM_IMAGE_FROM_MEDIA,
            SERVICE_CLEAR_ITEM_IMAGE,
            SERVICE_BACKUP_DATABASE,
            SERVICE_RESTORE_DATABASE,
            SERVICE_EXPORT,
        }

        # Intents registered
        register_intents_mock.assert_called_once_with(hass_mock)

        # Domain data contains coordinator
        assert DOMAIN in hass_mock.data
        assert entry1.entry_id in hass_mock.data[DOMAIN].coordinators


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

    hass_mock.data[DOMAIN] = SimpleInventoryData(
        coordinators={entry1.entry_id: coord1, entry2.entry_id: coord2},
        services_registered=True,
        repository=repo,
    )

    with patch(
        "custom_components.simple_inventory.async_unregister_intents"
    ) as unregister_intents_mock:
        ok = await async_unload_entry(hass_mock, entry1)
        assert ok is True

        hass_mock.services.async_remove.assert_not_called()
        repo.async_close.assert_not_awaited()
        assert entry2.entry_id in hass_mock.data[DOMAIN].coordinators
        unregister_intents_mock.assert_not_called()


@pytest.mark.asyncio
async def test_async_unload_entry_last_removes_services_and_closes_repo(
    hass_mock: MagicMock, entry1: MagicMock
) -> None:
    coord = MagicMock()
    coord.async_unload = AsyncMock()
    repo = MagicMock()
    repo.async_close = AsyncMock()

    hass_mock.data[DOMAIN] = SimpleInventoryData(
        coordinators={entry1.entry_id: coord},
        services_registered=True,
        repository=repo,
    )

    with patch(
        "custom_components.simple_inventory.async_unregister_intents"
    ) as unregister_intents_mock:
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
            SERVICE_UPDATE_BATCH,
            SERVICE_REMOVE_BATCH,
            SERVICE_TRANSFER_ITEM,
            SERVICE_SET_ITEM_IMAGE_FROM_BARCODE,
            SERVICE_SET_ITEM_IMAGE_FROM_MEDIA,
            SERVICE_CLEAR_ITEM_IMAGE,
            SERVICE_BACKUP_DATABASE,
            SERVICE_RESTORE_DATABASE,
            SERVICE_EXPORT,
        }

        repo.async_close.assert_awaited_once()
        assert DOMAIN not in hass_mock.data
        unregister_intents_mock.assert_called_once_with(hass_mock)


@pytest.mark.asyncio
async def test_async_remove_entry_deletes_inventory_and_closes_repo(
    entry1: MagicMock,
) -> None:
    """async_remove_entry must delete the inventory row and close the repo."""
    hass = MagicMock()
    mock_repo = MagicMock()
    mock_repo.async_initialize = AsyncMock()
    mock_repo.delete_inventory = AsyncMock(return_value=True)
    mock_repo.list_item_ids_with_images = AsyncMock(return_value=set())
    mock_repo.async_close = AsyncMock()

    with patch("custom_components.simple_inventory.InventoryRepository", return_value=mock_repo):
        await async_remove_entry(hass, entry1)

    mock_repo.async_initialize.assert_awaited_once()
    mock_repo.list_item_ids_with_images.assert_awaited_once_with(entry1.entry_id)
    mock_repo.delete_inventory.assert_awaited_once_with(entry1.entry_id)
    mock_repo.async_close.assert_awaited_once()


@pytest.mark.asyncio
async def test_async_remove_entry_closes_repo_even_on_error(
    entry1: MagicMock,
) -> None:
    """async_remove_entry must close the repo even if delete_inventory raises."""
    hass = MagicMock()
    mock_repo = MagicMock()
    mock_repo.async_initialize = AsyncMock()
    mock_repo.delete_inventory = AsyncMock(side_effect=RuntimeError("db error"))
    mock_repo.list_item_ids_with_images = AsyncMock(return_value=set())
    mock_repo.async_close = AsyncMock()

    with (
        patch("custom_components.simple_inventory.InventoryRepository", return_value=mock_repo),
        pytest.raises(RuntimeError, match="db error"),
    ):
        await async_remove_entry(hass, entry1)

    mock_repo.async_close.assert_awaited_once()


def _patch_setup_dependencies() -> ExitStack:
    """Patch the heavy collaborators of async_setup_entry; returns the entered stack."""
    stack = ExitStack()
    stack.enter_context(patch("custom_components.simple_inventory.TodoManager"))
    stack.enter_context(patch("custom_components.simple_inventory.ServiceHandler"))
    stack.enter_context(patch("custom_components.simple_inventory.async_register_intents"))
    stack.enter_context(patch("custom_components.simple_inventory.async_unregister_intents"))
    stack.enter_context(
        patch("custom_components.simple_inventory.async_register_websocket_commands")
    )
    return stack


@pytest.mark.asyncio
async def test_repository_init_failure_is_not_ready_and_retry_reinitialises(
    hass_mock: MagicMock, entry1: MagicMock
) -> None:
    """A failed DB open must not poison hass.data: the retry opens the DB again."""
    with (
        _patch_setup_dependencies(),
        patch("custom_components.simple_inventory.InventoryRepository") as repo_cls,
        patch("custom_components.simple_inventory.SimpleInventoryCoordinator") as coord_cls,
    ):
        failing_repo = MagicMock()
        failing_repo.async_initialize = AsyncMock(side_effect=RuntimeError("database is locked"))
        failing_repo.async_close = AsyncMock()
        working_repo = MagicMock()
        working_repo.async_initialize = AsyncMock()
        repo_cls.side_effect = [failing_repo, working_repo]

        coord = coord_cls.return_value
        coord.async_initialize = AsyncMock()
        coord.async_upsert_inventory_metadata = AsyncMock()

        with pytest.raises(ConfigEntryNotReady, match="database is locked"):
            await async_setup_entry(hass_mock, entry1)

        failing_repo.async_close.assert_awaited_once()
        assert get_repository(hass_mock) is None
        assert hass_mock.data[DOMAIN].hub is None
        assert hass_mock.data[DOMAIN].coordinators == {}
        coord_cls.assert_not_called()

        assert await async_setup_entry(hass_mock, entry1) is True

        working_repo.async_initialize.assert_awaited_once()
        domain_data = hass_mock.data[DOMAIN]
        assert domain_data.repository is working_repo
        assert domain_data.hub is not None
        assert domain_data.hub.repository is working_repo
        assert entry1.entry_id in domain_data.coordinators
        assert coord_cls.call_args.args == (hass_mock, entry1, working_repo, domain_data.hub)


@pytest.mark.asyncio
async def test_setup_sweeps_orphan_images_once_after_opening_the_database(
    hass_mock: MagicMock, entry1: MagicMock, entry2: MagicMock, sweep_images: AsyncMock
) -> None:
    with (
        _patch_setup_dependencies(),
        patch("custom_components.simple_inventory.InventoryRepository") as repo_cls,
        patch("custom_components.simple_inventory.SimpleInventoryCoordinator") as coord_cls,
    ):
        repo = repo_cls.return_value
        repo.async_initialize = AsyncMock()
        coord = coord_cls.return_value
        coord.async_initialize = AsyncMock()
        coord.async_upsert_inventory_metadata = AsyncMock()

        await async_setup_entry(hass_mock, entry1)
        await async_setup_entry(hass_mock, entry2)

    repo.async_initialize.assert_awaited_once()
    sweep_images.assert_awaited_once_with(hass_mock, repo)


@pytest.mark.asyncio
async def test_failed_database_open_skips_the_image_sweep(
    hass_mock: MagicMock, entry1: MagicMock, sweep_images: AsyncMock
) -> None:
    with (
        _patch_setup_dependencies(),
        patch("custom_components.simple_inventory.InventoryRepository") as repo_cls,
        patch("custom_components.simple_inventory.SimpleInventoryCoordinator"),
    ):
        repo = repo_cls.return_value
        repo.async_initialize = AsyncMock(side_effect=RuntimeError("database is locked"))
        repo.async_close = AsyncMock()

        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass_mock, entry1)

    sweep_images.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_setup_after_registration_releases_coordinator_and_domain(
    hass_mock: MagicMock, entry1: MagicMock
) -> None:
    """If a later setup await fails, the coordinator must not leak (HA never unloads a
    SETUP_ERROR entry), and the domain must be torn down when it was the only entry."""
    with (
        _patch_setup_dependencies(),
        patch("custom_components.simple_inventory.InventoryRepository") as repo_cls,
        patch("custom_components.simple_inventory.SimpleInventoryCoordinator") as coord_cls,
    ):
        repo = repo_cls.return_value
        repo.async_initialize = AsyncMock()
        repo.async_close = AsyncMock()

        coord = coord_cls.return_value
        coord.async_initialize = AsyncMock()
        coord.async_unload = AsyncMock()
        coord.async_upsert_inventory_metadata = AsyncMock(
            side_effect=RuntimeError("UNIQUE constraint failed: inventories.name")
        )

        with pytest.raises(RuntimeError, match="UNIQUE constraint"):
            await async_setup_entry(hass_mock, entry1)

        coord.async_unload.assert_awaited_once()
        repo.async_close.assert_awaited_once()
        assert DOMAIN not in hass_mock.data
        removed = {c.args[1] for c in hass_mock.services.async_remove.call_args_list}
        assert SERVICE_ADD_ITEM in removed


@pytest.mark.asyncio
async def test_failed_setup_keeps_domain_when_other_entries_loaded(
    hass_mock: MagicMock, entry1: MagicMock, entry2: MagicMock
) -> None:
    with (
        _patch_setup_dependencies(),
        patch("custom_components.simple_inventory.InventoryRepository") as repo_cls,
        patch("custom_components.simple_inventory.SimpleInventoryCoordinator") as coord_cls,
    ):
        repo = repo_cls.return_value
        repo.async_initialize = AsyncMock()
        repo.async_close = AsyncMock()

        coord = coord_cls.return_value
        coord.async_initialize = AsyncMock()
        coord.async_unload = AsyncMock()
        coord.async_upsert_inventory_metadata = AsyncMock()
        await async_setup_entry(hass_mock, entry1)

        hass_mock.config_entries.async_forward_entry_setups = AsyncMock(
            side_effect=RuntimeError("platform failed")
        )
        with pytest.raises(RuntimeError, match="platform failed"):
            await async_setup_entry(hass_mock, entry2)

        assert set(hass_mock.data[DOMAIN].coordinators) == {entry1.entry_id}
        repo.async_close.assert_not_awaited()
        hass_mock.services.async_remove.assert_not_called()


@pytest.mark.asyncio
async def test_create_global_is_one_shot(hass_mock: MagicMock, entry1: MagicMock) -> None:
    """After ensuring the global entry once, the request is dropped from the entry data so a
    global entry the user deletes is not recreated on every restart."""
    entry1.data["create_global"] = True

    with (
        _patch_setup_dependencies(),
        patch("custom_components.simple_inventory.InventoryRepository") as repo_cls,
        patch("custom_components.simple_inventory.SimpleInventoryCoordinator") as coord_cls,
    ):
        repo_cls.return_value.async_initialize = AsyncMock()
        coord_cls.return_value.async_initialize = AsyncMock()
        coord_cls.return_value.async_upsert_inventory_metadata = AsyncMock()

        await async_setup_entry(hass_mock, entry1)

    hass_mock.config_entries.flow.async_init.assert_awaited_once()
    hass_mock.config_entries.async_update_entry.assert_called_once_with(
        entry1, data={"name": "Kitchen", "entry_type": "inventory"}
    )


@pytest.mark.asyncio
async def test_entry_update_schedules_reload(hass_mock: MagicMock, entry1: MagicMock) -> None:
    """Options-flow edits (rename/icon) reach entities and the device via an entry reload."""
    with (
        _patch_setup_dependencies(),
        patch("custom_components.simple_inventory.InventoryRepository") as repo_cls,
        patch("custom_components.simple_inventory.SimpleInventoryCoordinator") as coord_cls,
    ):
        repo_cls.return_value.async_initialize = AsyncMock()
        coord_cls.return_value.async_initialize = AsyncMock()
        coord_cls.return_value.async_upsert_inventory_metadata = AsyncMock()

        await async_setup_entry(hass_mock, entry1)

    entry1.add_update_listener.assert_called_once()
    entry1.async_on_unload.assert_called_once_with(entry1.add_update_listener.return_value)

    listener = entry1.add_update_listener.call_args.args[0]
    await listener(hass_mock, entry1)
    hass_mock.config_entries.async_schedule_reload.assert_called_once_with(entry1.entry_id)


@pytest.mark.asyncio
async def test_async_remove_entry_signals_global_refresh(entry1: MagicMock) -> None:
    """Global sensors / unfiltered WS subscribers must drop the deleted inventory's items."""
    hass = MagicMock()
    mock_repo = MagicMock()
    mock_repo.async_initialize = AsyncMock()
    mock_repo.delete_inventory = AsyncMock(return_value=True)
    mock_repo.list_item_ids_with_images = AsyncMock(return_value=set())
    mock_repo.async_close = AsyncMock()

    with patch("custom_components.simple_inventory.InventoryRepository", return_value=mock_repo):
        await async_remove_entry(hass, entry1)

    hass.bus.async_fire.assert_called_once_with(f"{DOMAIN}_updated")


@pytest.mark.asyncio
async def test_newer_database_is_config_entry_error_with_issue(
    hass_mock: MagicMock, entry1: MagicMock, issue_hooks: SimpleNamespace
) -> None:
    """Retrying cannot fix a downgrade: ConfigEntryError (not NotReady) plus a repair issue."""
    with (
        _patch_setup_dependencies(),
        patch("custom_components.simple_inventory.InventoryRepository") as repo_cls,
        patch("custom_components.simple_inventory.SimpleInventoryCoordinator") as coord_cls,
    ):
        error = DatabaseFromNewerVersionError(9, 3)
        repo = repo_cls.return_value
        repo.async_initialize = AsyncMock(side_effect=error)
        repo.async_close = AsyncMock()

        with pytest.raises(ConfigEntryError, match="newer"):
            await async_setup_entry(hass_mock, entry1)

    issue_hooks.create_newer.assert_called_once_with(hass_mock, error)
    issue_hooks.delete_newer.assert_not_called()
    repo.async_close.assert_awaited_once()
    assert hass_mock.data[DOMAIN].repository is None
    assert hass_mock.data[DOMAIN].hub is None
    coord_cls.assert_not_called()


@pytest.mark.asyncio
async def test_setup_clears_newer_database_issue_and_starts_issue_detection(
    hass_mock: MagicMock, entry1: MagicMock, issue_hooks: SimpleNamespace
) -> None:
    with (
        _patch_setup_dependencies(),
        patch("custom_components.simple_inventory.InventoryRepository") as repo_cls,
        patch("custom_components.simple_inventory.SimpleInventoryCoordinator") as coord_cls,
    ):
        repo = repo_cls.return_value
        repo.async_initialize = AsyncMock()
        coord_cls.return_value.async_initialize = AsyncMock()
        coord_cls.return_value.async_upsert_inventory_metadata = AsyncMock()

        await async_setup_entry(hass_mock, entry1)

    issue_hooks.delete_newer.assert_called_once_with(hass_mock)
    issue_hooks.create_newer.assert_not_called()
    issue_hooks.setup_detection.assert_called_once_with(hass_mock, entry1, repo)


@pytest.mark.asyncio
async def test_async_remove_entry_deletes_entry_issues(
    entry1: MagicMock, issue_hooks: SimpleNamespace
) -> None:
    hass = MagicMock()
    mock_repo = MagicMock()
    mock_repo.async_initialize = AsyncMock()
    mock_repo.delete_inventory = AsyncMock(return_value=True)
    mock_repo.list_item_ids_with_images = AsyncMock(return_value=set())
    mock_repo.async_close = AsyncMock()

    with patch("custom_components.simple_inventory.InventoryRepository", return_value=mock_repo):
        await async_remove_entry(hass, entry1)

    issue_hooks.delete_entry_issues.assert_called_once_with(hass, entry1.entry_id)
