"""Shared harness for exercising sensor refresh wiring against a real hass."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable
from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (  # type: ignore[import-untyped]
    async_fire_time_changed,
)

AttachSensor = Callable[[SensorEntity], Awaitable[SensorEntity]]


@pytest.fixture
async def attach_sensor(hass: HomeAssistant) -> AsyncGenerator[AttachSensor, None]:
    """Run a sensor's async_added_to_hass for real; tear its subscriptions down afterwards."""
    attached: list[SensorEntity] = []

    async def _attach(sensor: SensorEntity) -> SensorEntity:
        sensor.hass = hass
        sensor.entity_id = "sensor.under_test"
        sensor.async_write_ha_state = MagicMock()  # type: ignore[misc,method-assign]
        await sensor.async_added_to_hass()
        attached.append(sensor)
        return sensor

    yield _attach

    for sensor in attached:
        sensor._call_on_remove_callbacks()


@pytest.fixture
def fire_next_local_midnight(hass: HomeAssistant) -> Callable[[], Awaitable[None]]:
    """Return a coroutine that advances to 00:00:05 local time tomorrow and drains callbacks."""

    async def _fire() -> None:
        tomorrow = dt_util.now() + timedelta(days=1)
        async_fire_time_changed(hass, dt_util.start_of_local_day(tomorrow) + timedelta(seconds=5))
        await hass.async_block_till_done()

    return _fire
