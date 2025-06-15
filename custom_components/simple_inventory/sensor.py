"""Sensor platform for Simple Inventory."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .sensors import (
    ExpiryNotificationSensor,
    GlobalExpiryNotificationSensor,
    InventorySensor,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors based on config entry type."""
    coordinator = hass.data[DOMAIN]["coordinator"]
    entry_type = config_entry.data.get("entry_type", "inventory")

    if entry_type == "global":
        global_sensor = GlobalExpiryNotificationSensor(hass, coordinator)
        async_add_entities([global_sensor])
    else:
        inventory_name = config_entry.data.get("name", "Inventory")
        icon = config_entry.data.get("icon", "mdi:package-variant")
        entry_id = config_entry.entry_id

        sensors_to_add = [
            InventorySensor(hass, coordinator, inventory_name, icon, entry_id),
            ExpiryNotificationSensor(hass, coordinator, entry_id, inventory_name),
        ]
        async_add_entities(sensors_to_add)
