"""Tests for GlobalExpiredItemsSensor."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.simple_inventory.sensors import GlobalExpiredItemsSensor


@pytest.fixture
def mock_sensor_coordinator() -> MagicMock:
    coordinator = MagicMock()
    coordinator.async_get_items_expiring_soon = AsyncMock(return_value=[])
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)
    return coordinator


@pytest.fixture
def global_expired_sensor(
    hass: HomeAssistant, mock_sensor_coordinator: MagicMock
) -> GlobalExpiredItemsSensor:
    return GlobalExpiredItemsSensor(hass, mock_sensor_coordinator)


def test_init(global_expired_sensor: GlobalExpiredItemsSensor) -> None:
    assert global_expired_sensor._attr_name == "All Expired Items"
    assert global_expired_sensor._attr_unique_id == "simple_inventory_all_expired_items"
    assert global_expired_sensor._attr_native_unit_of_measurement == "items"
    assert global_expired_sensor._attr_icon == "mdi:calendar-remove"


@pytest.mark.asyncio
async def test_update_state_multiple_inventories(
    global_expired_sensor: GlobalExpiredItemsSensor,
    mock_sensor_coordinator: MagicMock,
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

    mock_sensor_coordinator.async_get_items_expiring_soon.return_value = test_items

    with (
        patch.object(global_expired_sensor, "_get_inventory_name", return_value="Test Inventory"),
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
    mock_sensor_coordinator: MagicMock,
) -> None:
    test_items = [
        {"inventory_id": "kitchen_inventory", "name": "milk", "days_until_expiry": 3, "quantity": 1}
    ]
    mock_sensor_coordinator.async_get_items_expiring_soon.return_value = test_items

    with (
        patch.object(global_expired_sensor, "_get_inventory_name", return_value="Test"),
        patch.object(global_expired_sensor, "async_write_ha_state"),
    ):
        await global_expired_sensor._async_update_state()

    assert global_expired_sensor._attr_native_value == 0
    assert global_expired_sensor._attr_extra_state_attributes["total_expired"] == 0
    assert global_expired_sensor._attr_extra_state_attributes["oldest_expired"] is None


@pytest.mark.asyncio
async def test_coordinator_called_without_inventory_id(
    global_expired_sensor: GlobalExpiredItemsSensor,
    mock_sensor_coordinator: MagicMock,
) -> None:
    with patch.object(global_expired_sensor, "async_write_ha_state"):
        await global_expired_sensor._async_update_state()

    mock_sensor_coordinator.async_get_items_expiring_soon.assert_awaited_once_with()


def test_icon_is_always_calendar_remove(global_expired_sensor: GlobalExpiredItemsSensor) -> None:
    assert global_expired_sensor._attr_icon == "mdi:calendar-remove"


def test_handle_update_schedules_task(global_expired_sensor: GlobalExpiredItemsSensor) -> None:
    with patch.object(global_expired_sensor.hass, "async_create_task") as mock_create_task:
        global_expired_sensor._handle_update(None)
        mock_create_task.assert_called_once()
