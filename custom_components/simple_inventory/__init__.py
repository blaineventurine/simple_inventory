"""Simple Inventory integration."""

from __future__ import annotations

import asyncio
import logging

import homeassistant.helpers.config_validation as cv
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady

from .const import (
    CONF_CREATE_GLOBAL,
    CONF_DESCRIPTION,
    CONF_ENTRY_TYPE,
    CONF_ICON,
    CONF_NAME,
    DOMAIN,
    ENTRY_TYPE_GLOBAL,
    EVENT_UPDATED,
    GLOBAL_ENTRY_DESCRIPTION,
    GLOBAL_ENTRY_ICON,
    GLOBAL_ENTRY_TITLE,
)
from .coordinator import SimpleInventoryCoordinator
from .data import DATA_KEY, SimpleInventoryData, get_hub
from .entries import entry_type, is_global_entry
from .http import async_register_image_views
from .hub import InventoryHub
from .intents import async_register_intents, async_unregister_intents
from .panel import async_register_panel_loader_view, async_sync_panel, async_unload_panel
from .repairs import (
    async_create_newer_database_issue,
    async_delete_entry_issues,
    async_delete_newer_database_issue,
    async_setup_issue_detection,
)
from .schemas.service_schemas import SERVICES
from .services import ServiceHandler
from .storage.images import async_delete_inventory_with_images, async_sweep_orphan_images
from .storage.repository import DatabaseFromNewerVersionError, InventoryRepository
from .todo_manager import TodoManager
from .voice_sentences import async_sync_voice_sentences
from .websocket_api import async_register_websocket_commands

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Simple Inventory from a config entry."""
    if (domain_data := hass.data.get(DATA_KEY)) is None:
        domain_data = hass.data[DATA_KEY] = SimpleInventoryData()

    hub = await _async_get_hub(hass, domain_data)
    repository = hub.repository

    # Registered before any fallible await so a concurrent unload of another entry never
    # sees an idle domain and closes the repository underneath this setup; popped on failure.
    coordinator = SimpleInventoryCoordinator(hass, entry, repository, hub)
    domain_data.coordinators[entry.entry_id] = coordinator

    try:
        await coordinator.async_initialize()

        if not domain_data.services_registered:
            _register_services(hass, domain_data)

        await coordinator.async_upsert_inventory_metadata(
            inventory_id=entry.entry_id,
            name=entry.data.get(CONF_NAME, entry.title or entry.entry_id),
            description=entry.data.get(CONF_DESCRIPTION, ""),
            icon=entry.data.get(CONF_ICON, ""),
            entry_type=entry_type(entry),
            metadata=None,
        )

        if entry.data.get(CONF_CREATE_GLOBAL):
            await _ensure_global_entry(hass)
            # One-shot request: drop it so a user-deleted global entry is not recreated
            # on every restart.
            hass.config_entries.async_update_entry(
                entry,
                data={key: value for key, value in entry.data.items() if key != CONF_CREATE_GLOBAL},
            )

        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        domain_data.coordinators.pop(entry.entry_id, None)
        await coordinator.async_unload()
        await _async_release_domain_if_idle(hass, domain_data)
        raise

    # Name/icon/description edits from the options flow are applied by reloading the entry,
    # which recreates the entities/device and mirrors the metadata into the repository.
    entry.async_on_unload(entry.add_update_listener(_async_reload_on_update))
    if is_global_entry(entry):
        entry.async_on_unload(lambda: async_unload_panel(hass))
        await async_sync_panel(hass, entry)
    async_setup_issue_detection(hass, entry, repository)
    # Setup is where an entry's (new) name first takes effect, after an add or a rename.
    await async_sync_voice_sentences(hass)
    return True


async def _async_get_hub(hass: HomeAssistant, domain_data: SimpleInventoryData) -> InventoryHub:
    """Return the shared hub over the initialised repository, opening it on first use.

    The hub and the repository are created, and dropped, together. A failed open is
    not cached: the repository is closed and discarded so the next setup attempt
    (ConfigEntryNotReady retry) opens it again. A database from a newer release raises
    ConfigEntryError instead (retrying cannot help) and opens a repair issue, deleted
    again once the database opens.
    """
    hub = domain_data.hub
    repo_task = domain_data.repository_task

    if domain_data.repository is None or hub is None:
        repository = InventoryRepository(hass)
        hub = InventoryHub(hass, repository)
        domain_data.repository = repository
        domain_data.hub = hub
        repo_task = hass.async_create_task(_async_open_repository(hass, repository))
        domain_data.repository_task = repo_task

    if repo_task is None:
        return hub

    opened: InventoryHub = hub
    task: asyncio.Task[None] = repo_task
    try:
        await task
    except Exception as err:
        if domain_data.hub is opened:
            domain_data.repository = None
            domain_data.hub = None
            await opened.repository.async_close()
        if isinstance(err, DatabaseFromNewerVersionError):
            async_create_newer_database_issue(hass, err)
            raise ConfigEntryError(str(err)) from err
        raise ConfigEntryNotReady(f"Unable to open the Simple Inventory database: {err}") from err
    finally:
        if domain_data.repository_task is task and task.done():
            domain_data.repository_task = None

    async_delete_newer_database_issue(hass)
    return opened


async def _async_open_repository(hass: HomeAssistant, repository: InventoryRepository) -> None:
    """Open the shared database, then drop image files no item owns (spec I9)."""
    await repository.async_initialize()
    await async_sweep_orphan_images(hass, repository)


def _register_services(hass: HomeAssistant, domain_data: SimpleInventoryData) -> None:
    """Register services, WebSocket commands and intents (once per domain lifetime)."""
    todo_manager = TodoManager(hass)
    service_handler = ServiceHandler(hass, todo_manager)
    for spec in SERVICES:
        hass.services.async_register(
            DOMAIN,
            spec.name,
            getattr(service_handler, spec.handler),
            schema=spec.schema,
            supports_response=spec.response,
        )

    async_register_websocket_commands(hass)
    async_register_intents(hass)

    domain_data.services_registered = True
    domain_data.todo_manager = todo_manager
    domain_data.service_handler = service_handler


async def _async_reload_on_update(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry after its data changes (options-flow rename/icon/description)."""
    hass.config_entries.async_schedule_reload(entry.entry_id)


async def _ensure_global_entry(hass: HomeAssistant) -> None:
    """Create the global config entry if none exists."""
    if any(is_global_entry(entry) for entry in hass.config_entries.async_entries(DOMAIN)):
        return

    await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "internal"},
        data={
            CONF_NAME: GLOBAL_ENTRY_TITLE,
            CONF_ICON: GLOBAL_ENTRY_ICON,
            CONF_DESCRIPTION: GLOBAL_ENTRY_DESCRIPTION,
            CONF_ENTRY_TYPE: ENTRY_TYPE_GLOBAL,
        },
    )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    domain_data = hass.data.get(DATA_KEY)
    if domain_data is None:
        return True

    coordinator = domain_data.coordinators.pop(entry.entry_id, None)
    if coordinator:
        await coordinator.async_unload()

    await _async_release_domain_if_idle(hass, domain_data)
    # A disabled entry is unloaded and leaves the enabled inventories.
    await async_sync_voice_sentences(hass)
    return True


async def _async_release_domain_if_idle(
    hass: HomeAssistant, domain_data: SimpleInventoryData
) -> None:
    """Tear down shared services and the repository once no coordinator remains.

    Everything before the final await is synchronous so a setup racing with this
    teardown either registered its coordinator first (domain stays up) or starts
    from fresh domain data.
    """
    if domain_data.coordinators:
        return

    if hass.data.get(DATA_KEY) is domain_data:
        hass.data.pop(DATA_KEY)

    if domain_data.services_registered:
        for spec in SERVICES:
            _remove_service(hass, spec.name)
        async_unregister_intents(hass)
        domain_data.services_registered = False

    if domain_data.repository:
        await domain_data.repository.async_close()


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete all data for this entry when the user removes the integration."""
    async_delete_entry_issues(hass, entry.entry_id)

    repository = InventoryRepository(hass)
    try:
        await repository.async_initialize()
        await async_delete_inventory_with_images(hass, repository, entry.entry_id)
    finally:
        await repository.async_close()

    # Written through its own repository, not a coordinator: drop the hub's cached
    # all-inventories entries too. Global sensors and unfiltered WS subscribers still list
    # the deleted items until the event.
    if (hub := get_hub(hass)) is not None:
        hub.invalidate(None)
    hass.bus.async_fire(EVENT_UPDATED)
    await async_sync_voice_sentences(hass)


def _remove_service(hass: HomeAssistant, name: str) -> None:
    if hass.services.has_service(DOMAIN, name):
        hass.services.async_remove(DOMAIN, name)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register the HTTP views once per Home Assistant run (they cannot be removed)."""
    async_register_image_views(hass)
    async_register_panel_loader_view(hass)
    return True
