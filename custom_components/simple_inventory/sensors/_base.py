"""Refresh wiring shared by every Simple Inventory sensor."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change

from ..hub import InventoryHub

_LOGGER = logging.getLogger(__name__)


class InventoryRefreshSensor(SensorEntity):
    """Recomputes its state on an update event and after the local date changes.

    Subclasses set their names/ids in ``__init__`` and implement ``_async_refresh``.
    """

    _attr_native_unit_of_measurement = "items"

    def __init__(
        self,
        hass: HomeAssistant,
        hub: InventoryHub,
        *,
        cache_key: str | None,
        update_event: str,
    ) -> None:
        """``cache_key`` is the expiry-cache entry to drop before refreshing
        (an inventory id, or None for the all-inventories entry)."""
        self.hass = hass
        self.hub = hub
        self._cache_key = cache_key
        self._update_event = update_event
        self._attr_extra_state_attributes: dict[str, Any] = {}

    async def async_added_to_hass(self) -> None:
        """Refresh now, then on every update event and the daily date rollover."""
        await self._async_update_state()

        self.async_on_remove(self.hass.bus.async_listen(self._update_event, self._handle_update))
        # Days until expiry (and so every expiry figure) depend on today's date.
        self.async_on_remove(
            async_track_time_change(self.hass, self._handle_midnight, hour=0, minute=0, second=5)
        )

    @callback
    def _handle_midnight(self, _now: datetime) -> None:
        """Recompute date-dependent values after the local date changes."""
        self._handle_update()

    @callback
    def _handle_update(self, _event: Event | None = None) -> None:
        """Drop the stale expiry entries and schedule a refresh."""
        self.hub.invalidate(self._cache_key)
        self.hass.async_create_task(self._async_update_state())

    async def _async_update_state(self) -> None:
        """Refresh and write the state; a failed refresh keeps the previous state."""
        try:
            await self._async_refresh()
        except Exception as err:
            _LOGGER.error("Failed to refresh sensor %s: %s", self._attr_unique_id, err)
            return
        self.async_write_ha_state()

    async def _async_refresh(self) -> None:
        """Set the native value and attributes."""
        raise NotImplementedError
