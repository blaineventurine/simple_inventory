"""Sensor platform for Simple Inventory."""
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .sensors import InventorySensor, ExpiryNotificationSensor

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

    async_add_entities(
        [InventorySensor(hass, coordinator, inventory_name, icon, entry_id)])

    # Add the expiry notification sensor (only once)
    all_entries = hass.config_entries.async_entries(DOMAIN)
    if entry_id == all_entries[0].entry_id:
        # Get threshold from options or use default
        threshold_days = config_entry.options.get("expiry_threshold", 7)
        expiry_sensor = ExpiryNotificationSensor(
            hass, coordinator, threshold_days)
        async_add_entities([expiry_sensor])
