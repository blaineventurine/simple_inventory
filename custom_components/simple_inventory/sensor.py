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
    """Set up the inventory sensor."""
    coordinator = hass.data[DOMAIN]["coordinator"]
    inventory_name = config_entry.data.get("name", "Inventory")
    icon = config_entry.data.get("icon", "mdi:package-variant")
    entry_id = config_entry.entry_id

    sensors_to_add = []

    inventory_sensor = InventorySensor(
        hass, coordinator, inventory_name, icon, entry_id
    )
    sensors_to_add.append(inventory_sensor)
    per_inventory_expiry_sensor = ExpiryNotificationSensor(
        hass, coordinator, entry_id, inventory_name
    )

    sensors_to_add.append(per_inventory_expiry_sensor)

    # Create global expiry sensor (only once)
    all_entries = hass.config_entries.async_entries(DOMAIN)
    if entry_id == all_entries[0].entry_id:
        global_expiry_sensor = GlobalExpiryNotificationSensor(hass, coordinator)
        sensors_to_add.append(global_expiry_sensor)

    async_add_entities(sensors_to_add)
