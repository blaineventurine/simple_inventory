"""Settings management service handler."""
import logging
from homeassistant.core import ServiceCall
from .base_service import BaseServiceHandler
from ..const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class SettingsService(BaseServiceHandler):
    """Handle settings operations."""

    async def async_update_item_settings(self, call: ServiceCall):
        """Update item auto-add settings."""
        inventory_id, name = self._get_inventory_and_name(call)
        settings = self._extract_item_kwargs(
            call.data, ["name", "inventory_id"])

        try:
            if self.coordinator.update_item_settings(inventory_id, name, **settings):
                await self._save_and_log_success(inventory_id, f"Updated settings for item", name)
            else:
                self._log_item_not_found(
                    "Update item settings", name, inventory_id)
        except Exception as e:
            _LOGGER.error(f"Failed to update settings for item {
                          name} in inventory {inventory_id}: {e}")

    async def _update_expiry_sensor_threshold(self, threshold_days: int):
        """Update the expiry sensor threshold and refresh its data."""
        expiry_sensor_entity_id = None

        for entity_id in self.hass.states.async_entity_ids("sensor"):
            state = self.hass.states.get(entity_id)
            if (state and
                    state.attributes.get("unique_id") == "simple_inventory_expiring_items"):
                expiry_sensor_entity_id = entity_id
                break

        if not expiry_sensor_entity_id:
            _LOGGER.warning("Could not find expiry sensor to update")
            return

        entity_registry = await self.hass.helpers.entity_registry.async_get(
            self.hass)

        for entity in entity_registry.entities.values():
            if entity.entity_id == expiry_sensor_entity_id:
                platform = entity.platform
                if platform == DOMAIN:
                    self.hass.bus.async_fire(f"{DOMAIN}_threshold_updated", {
                        "new_threshold": threshold_days
                    })
                    break

        _LOGGER.debug(f"Updated expiry sensor threshold to {
                      threshold_days} days")

    def get_current_expiry_threshold(self) -> int:
        """Get the current expiry threshold from config entries."""
        config_entries = self.hass.config_entries.async_entries(DOMAIN)
        if config_entries:
            return config_entries[0].options.get("expiry_threshold", 7)
        return 7
