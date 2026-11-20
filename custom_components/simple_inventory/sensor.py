"""Sensor platform for Simple Inventory."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ICON, CONF_NAME, DEFAULT_INVENTORY_ICON
from .data import get_domain_data
from .entries import is_global_entry
from .sensors import (
    ExpiredItemsSensor,
    GlobalExpiredItemsSensor,
    GlobalItemsExpiringSoonSensor,
    InventorySensor,
    ItemsExpiringSoonSensor,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors based on config entry type."""
    coordinator = get_domain_data(hass).coordinators.get(config_entry.entry_id)
    if coordinator is None:
        _LOGGER.error(
            "No coordinator found for entry %s; skipping sensor setup",
            config_entry.entry_id,
        )
        return

    hub = coordinator.hub
    if is_global_entry(config_entry):
        async_add_entities(
            [
                GlobalItemsExpiringSoonSensor(hass, hub),
                GlobalExpiredItemsSensor(hass, hub),
            ]
        )
        return

    inventory_name = config_entry.data.get(CONF_NAME, "Inventory")
    icon = config_entry.data.get(CONF_ICON, DEFAULT_INVENTORY_ICON)
    entry_id = config_entry.entry_id

    sensors = [
        InventorySensor(hass, hub, coordinator, inventory_name, icon, entry_id),
        ItemsExpiringSoonSensor(hass, hub, entry_id, inventory_name),
        ExpiredItemsSensor(hass, hub, entry_id, inventory_name),
    ]
    async_add_entities(sensors)
