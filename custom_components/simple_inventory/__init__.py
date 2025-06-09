import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import (
    DOMAIN,
    SERVICE_ADD_ITEM,
    SERVICE_REMOVE_ITEM,
    SERVICE_INCREMENT_ITEM,
    SERVICE_DECREMENT_ITEM,
    SERVICE_UPDATE_ITEM_SETTINGS,
)
from .coordinator import SimpleInventoryCoordinator
from .todo_manager import TodoManager
from .services import (
    ServiceHandler,
    ITEM_SCHEMA,
    UPDATE_SCHEMA,
    UPDATE_SETTINGS_SCHEMA,
    REMOVE_SCHEMA,
    UPDATE_ITEM_SCHEMA,
    SET_EXPIRY_THRESHOLD_SCHEMA
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Simple Inventory from a config entry."""

    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    if "coordinator" not in hass.data[DOMAIN]:
        coordinator = SimpleInventoryCoordinator(hass)
        todo_manager = TodoManager(hass)
        service_handler = ServiceHandler(hass, coordinator, todo_manager)

        # Load data
        await coordinator.async_load_data()

        # Register services
        hass.services.async_register(
            DOMAIN, "set_expiry_threshold", service_handler.async_set_expiry_threshold, schema=SET_EXPIRY_THRESHOLD_SCHEMA
        )
        hass.services.async_register(
            DOMAIN, "update_item", service_handler.async_update_item, schema=UPDATE_ITEM_SCHEMA
        )
        hass.services.async_register(
            DOMAIN, SERVICE_ADD_ITEM, service_handler.async_add_item, schema=ITEM_SCHEMA
        )
        hass.services.async_register(
            DOMAIN, SERVICE_REMOVE_ITEM, service_handler.async_remove_item, schema=REMOVE_SCHEMA
        )
        hass.services.async_register(
            DOMAIN, SERVICE_INCREMENT_ITEM, service_handler.async_increment_item, schema=UPDATE_SCHEMA
        )
        hass.services.async_register(
            DOMAIN, SERVICE_DECREMENT_ITEM, service_handler.async_decrement_item, schema=UPDATE_SCHEMA
        )
        hass.services.async_register(
            DOMAIN, SERVICE_UPDATE_ITEM_SETTINGS, service_handler.async_update_item_settings, schema=UPDATE_SETTINGS_SCHEMA
        )

        hass.data[DOMAIN]["coordinator"] = coordinator
        hass.data[DOMAIN]["todo_manager"] = todo_manager
    else:
        coordinator = hass.data[DOMAIN]["coordinator"]
        todo_manager = hass.data[DOMAIN]["todo_manager"]

    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "todo_manager": todo_manager,
        "config": entry.data
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

        remaining_entries = [
            entry_id for entry_id in hass.data[DOMAIN]
            if entry_id not in ["coordinator", "todo_manager"]
        ]

        if not remaining_entries:
            hass.services.async_remove(DOMAIN, SERVICE_ADD_ITEM)
            hass.services.async_remove(DOMAIN, SERVICE_REMOVE_ITEM)
            hass.services.async_remove(DOMAIN, SERVICE_INCREMENT_ITEM)
            hass.services.async_remove(DOMAIN, SERVICE_DECREMENT_ITEM)
            hass.services.async_remove(DOMAIN, SERVICE_UPDATE_ITEM_SETTINGS)
            hass.services.async_remove(DOMAIN, "update_item")
            hass.data[DOMAIN].clear()
            hass.data.pop(DOMAIN)

    return unload_ok


# Support for legacy YAML configuration
async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the component via YAML (legacy support)."""
    return True
