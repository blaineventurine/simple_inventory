"""Simple Inventory integration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

import homeassistant.helpers.config_validation as cv
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse

from .const import (
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
from .coordinator import SimpleInventoryCoordinator
from .schemas.service_schemas import (
    ADD_ITEM_SCHEMA,
    GET_ALL_ITEMS_SCHEMA,
    GET_INVENTORY_CONSUMPTION_RATES_SCHEMA,
    GET_ITEM_CONSUMPTION_RATES_SCHEMA,
    GET_ITEMS_SCHEMA,
    LOOKUP_BARCODE_PRODUCT_SCHEMA,
    LOOKUP_BY_BARCODE_SCHEMA,
    QUANTITY_UPDATE_SCHEMA,
    REMOVE_ITEM_SCHEMA,
    SCAN_BARCODE_SCHEMA,
    UPDATE_ITEM_SCHEMA,
)
from .services import ServiceHandler
from .storage.repository import InventoryRepository
from .todo_manager import TodoManager
from .websocket_api import async_register_websocket_commands

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# All service names registered by this integration.  Keep in sync with the
# registration table in async_setup_entry and with services.yaml.
_SERVICE_NAMES = (
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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Simple Inventory from a config entry."""
    domain_data = hass.data.setdefault(
        DOMAIN,
        {
            "coordinators": {},
            "services_registered": False,
            "repository": None,
            "repository_task": None,
            "todo_manager": None,
            "service_handler": None,
        },
    )

    repository: InventoryRepository | None = domain_data.get("repository")
    repo_task: asyncio.Task | None = domain_data.get("repository_task")

    if repository is None:
        repository = InventoryRepository(hass)
        domain_data["repository"] = repository
        repo_task = hass.async_create_task(repository.async_initialize())
        domain_data["repository_task"] = repo_task

    if repo_task is not None:
        try:
            await repo_task
        finally:
            if domain_data.get("repository_task") is repo_task and repo_task.done():
                domain_data["repository_task"] = None

    coordinator = SimpleInventoryCoordinator(hass, entry, repository)
    await coordinator.async_initialize()
    domain_data["coordinators"][entry.entry_id] = coordinator

    if not domain_data.get("services_registered"):
        todo_manager = TodoManager(hass)
        service_handler = ServiceHandler(hass, todo_manager)

        _OPT = SupportsResponse.OPTIONAL
        _NONE = SupportsResponse.NONE
        for svc_name, handler, schema, response_type in (
            (SERVICE_ADD_ITEM, service_handler.async_add_item, ADD_ITEM_SCHEMA, _NONE),
            (SERVICE_REMOVE_ITEM, service_handler.async_remove_item, REMOVE_ITEM_SCHEMA, _NONE),
            (SERVICE_UPDATE_ITEM, service_handler.async_update_item, UPDATE_ITEM_SCHEMA, _NONE),
            (
                SERVICE_INCREMENT_ITEM,
                service_handler.async_increment_item,
                QUANTITY_UPDATE_SCHEMA,
                _NONE,
            ),
            (
                SERVICE_DECREMENT_ITEM,
                service_handler.async_decrement_item,
                QUANTITY_UPDATE_SCHEMA,
                _NONE,
            ),
            (SERVICE_GET_ITEMS, service_handler.async_get_items, GET_ITEMS_SCHEMA, _OPT),
            (
                SERVICE_GET_ALL_ITEMS,
                service_handler.async_get_items_from_all_inventories,
                GET_ALL_ITEMS_SCHEMA,
                _OPT,
            ),
            (
                SERVICE_GET_INVENTORY_CONSUMPTION_RATES,
                service_handler.async_get_inventory_consumption_rates,
                GET_INVENTORY_CONSUMPTION_RATES_SCHEMA,
                _OPT,
            ),
            (
                SERVICE_GET_ITEM_CONSUMPTION_RATES,
                service_handler.async_get_item_consumption_rates,
                GET_ITEM_CONSUMPTION_RATES_SCHEMA,
                _OPT,
            ),
            (
                SERVICE_LOOKUP_BY_BARCODE,
                service_handler.async_lookup_by_barcode,
                LOOKUP_BY_BARCODE_SCHEMA,
                _OPT,
            ),
            (
                SERVICE_LOOKUP_BARCODE_PRODUCT,
                service_handler.async_lookup_barcode_product,
                LOOKUP_BARCODE_PRODUCT_SCHEMA,
                _OPT,
            ),
            (SERVICE_SCAN_BARCODE, service_handler.async_scan_barcode, SCAN_BARCODE_SCHEMA, _OPT),
        ):
            _register_service(hass, svc_name, handler, schema, supports_response=response_type)

        async_register_websocket_commands(hass)

        domain_data["services_registered"] = True
        domain_data["todo_manager"] = todo_manager
        domain_data["service_handler"] = service_handler

    await coordinator.async_upsert_inventory_metadata(
        inventory_id=entry.entry_id,
        name=entry.data.get("name", entry.title or entry.entry_id),
        description=entry.data.get("description", ""),
        icon=entry.data.get("icon", ""),
        entry_type=entry.data.get("entry_type", "inventory"),
        metadata=None,
    )

    domain_data[entry.entry_id] = {
        "config": entry.data,
    }

    if entry.data.get("create_global"):
        await _ensure_global_entry(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def _register_service(
    hass: HomeAssistant,
    name: str,
    handler: Callable[[ServiceCall], Coroutine[Any, Any, Any]],
    schema: Any,
    supports_response: SupportsResponse = SupportsResponse.NONE,
) -> None:
    hass.services.async_register(
        DOMAIN,
        name,
        handler,
        schema=schema,
        supports_response=supports_response,
    )


async def _ensure_global_entry(hass: HomeAssistant) -> None:
    """Create the global config entry if none exists."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.data.get("entry_type") == "global":
            return

    await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "internal"},
        data={
            "name": "All Items Expiring Soon",
            "icon": "mdi:calendar-alert",
            "description": "Tracks expiring items across all inventories",
            "entry_type": "global",
        },
    )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    domain_data = hass.data.get(DOMAIN)
    if not domain_data:
        return True

    coordinators: dict[str, SimpleInventoryCoordinator] = domain_data.get("coordinators", {})
    coordinator = coordinators.pop(entry.entry_id, None)
    if coordinator:
        await coordinator.async_unload()

    domain_data.pop(entry.entry_id, None)

    if coordinators:
        return True

    if domain_data.get("services_registered"):
        for svc_name in _SERVICE_NAMES:
            _remove_service(hass, svc_name)
        domain_data["services_registered"] = False

    repository: InventoryRepository | None = domain_data.get("repository")
    if repository:
        await repository.async_close()

    hass.data.pop(DOMAIN, None)
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete all data for this entry when the user removes the integration."""
    repository = InventoryRepository(hass)
    try:
        await repository.async_initialize()
        await repository.delete_inventory(entry.entry_id)
    finally:
        await repository.async_close()


def _remove_service(hass: HomeAssistant, name: str) -> None:
    if hass.services.has_service(DOMAIN, name):
        hass.services.async_remove(DOMAIN, name)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Legacy YAML setup hook (no-op)."""
    return True
