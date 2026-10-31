"""Tests for GlobalExpiredItemsSensor."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.simple_inventory.const import DOMAIN
from custom_components.simple_inventory.sensors import GlobalExpiredItemsSensor

SENSOR_MODULE = "custom_components.simple_inventory.sensors.global_expired_items_sensor"


@pytest.fixture
def mock_hub() -> MagicMock:
    hub = MagicMock()
    hub.async_items_expiring_soon = AsyncMock(return_value=[])
    return hub


@pytest.fixture
def global_expired_sensor(hass: HomeAssistant, mock_hub: MagicMock) -> GlobalExpiredItemsSensor:
    return GlobalExpiredItemsSensor(hass, mock_hub)


def test_init(global_expired_sensor: GlobalExpiredItemsSensor) -> None:
    assert global_expired_sensor._attr_name == "All Expired Items"
    assert global_expired_sensor._attr_unique_id == "simple_inventory_all_expired_items"
    assert global_expired_sensor._attr_native_unit_of_measurement == "items"
    assert global_expired_sensor._attr_icon == "mdi:calendar-remove"


@pytest.mark.asyncio
async def test_update_state_multiple_inventories(
    global_expired_sensor: GlobalExpiredItemsSensor,
    mock_hub: MagicMock,
) -> None:
    test_items = [
        {
            "inventory_id": "kitchen_inventory",
            "name": "milk",
            "days_until_expiry": 5,
            "quantity": 1,
        },
        {
            "inventory_id": "pantry_inventory",
            "name": "cereal",
            "days_until_expiry": -2,
            "quantity": 1,
        },
        {
            "inventory_id": "kitchen_inventory",
            "name": "yogurt",
            "days_until_expiry": -10,
            "quantity": 2,
        },
    ]

    mock_hub.async_items_expiring_soon.return_value = test_items

    with (
        patch(f"{SENSOR_MODULE}.inventory_display_name", return_value="Test Inventory"),
        patch.object(global_expired_sensor, "async_write_ha_state"),
    ):
        await global_expired_sensor._async_update_state()

    # milk (days=5) is excluded; cereal and yogurt are expired
    assert global_expired_sensor._attr_native_value == 2

    attributes = global_expired_sensor._attr_extra_state_attributes
    assert attributes["total_expired"] == 2
    # Two distinct inventories have expired items
    assert attributes["inventories_count"] == 2

    expired = attributes["expired_items"]
    assert len(expired) == 2
    names = {item["name"] for item in expired}
    assert names == {"cereal", "yogurt"}


@pytest.mark.asyncio
async def test_update_state_no_expired_items(
    global_expired_sensor: GlobalExpiredItemsSensor,
    mock_hub: MagicMock,
) -> None:
    test_items = [
        {"inventory_id": "kitchen_inventory", "name": "milk", "days_until_expiry": 3, "quantity": 1}
    ]
    mock_hub.async_items_expiring_soon.return_value = test_items

    with (
        patch(f"{SENSOR_MODULE}.inventory_display_name", return_value="Test"),
        patch.object(global_expired_sensor, "async_write_ha_state"),
    ):
        await global_expired_sensor._async_update_state()

    assert global_expired_sensor._attr_native_value == 0
    assert global_expired_sensor._attr_extra_state_attributes["total_expired"] == 0
    assert global_expired_sensor._attr_extra_state_attributes["oldest_expired"] is None


@pytest.mark.asyncio
async def test_hub_called_without_inventory_id(
    global_expired_sensor: GlobalExpiredItemsSensor,
    mock_hub: MagicMock,
) -> None:
    with patch.object(global_expired_sensor, "async_write_ha_state"):
        await global_expired_sensor._async_update_state()

    mock_hub.async_items_expiring_soon.assert_awaited_once_with()


def test_icon_is_always_calendar_remove(global_expired_sensor: GlobalExpiredItemsSensor) -> None:
    assert global_expired_sensor._attr_icon == "mdi:calendar-remove"


def test_handle_update_schedules_task(global_expired_sensor: GlobalExpiredItemsSensor) -> None:
    with patch.object(
        global_expired_sensor.hass, "async_create_task", side_effect=lambda coro: coro.close()
    ) as mock_create_task:
        global_expired_sensor._handle_update(None)
        mock_create_task.assert_called_once()


async def test_refreshes_only_on_general_event(
    hass: HomeAssistant,
    global_expired_sensor: GlobalExpiredItemsSensor,
    mock_hub: MagicMock,
    attach_sensor: Callable[[Any], Awaitable[Any]],
) -> None:
    await attach_sensor(global_expired_sensor)
    mock_hub.async_items_expiring_soon.reset_mock()

    hass.bus.async_fire(f"{DOMAIN}_updated")
    await hass.async_block_till_done()

    mock_hub.async_items_expiring_soon.assert_awaited_once_with()


async def test_local_midnight_recomputes_and_evicts_cache(
    global_expired_sensor: GlobalExpiredItemsSensor,
    mock_hub: MagicMock,
    attach_sensor: Callable[[Any], Awaitable[Any]],
    fire_next_local_midnight: Callable[[], Awaitable[None]],
) -> None:
    await attach_sensor(global_expired_sensor)
    mock_hub.invalidate.reset_mock()
    mock_hub.async_items_expiring_soon.reset_mock()

    await fire_next_local_midnight()

    mock_hub.async_items_expiring_soon.assert_awaited_once_with()
    mock_hub.invalidate.assert_called_once_with(None)
