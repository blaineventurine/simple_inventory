"""Tests for ExpiredItemsSensor."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import EventBus, HomeAssistant

from custom_components.simple_inventory.sensors import ExpiredItemsSensor


@pytest.fixture
def mock_sensor_coordinator() -> MagicMock:
    coordinator = MagicMock()
    coordinator.async_get_items_expiring_soon = AsyncMock(return_value=[])
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)
    return coordinator


@pytest.fixture
def expired_sensor(hass: HomeAssistant, mock_sensor_coordinator: MagicMock) -> ExpiredItemsSensor:
    return ExpiredItemsSensor(hass, mock_sensor_coordinator, "kitchen_inventory", "Kitchen")


def test_init(expired_sensor: ExpiredItemsSensor) -> None:
    assert expired_sensor._attr_name == "Kitchen Expired Items"
    assert expired_sensor._attr_unique_id == "simple_inventory_expired_items_kitchen_inventory"
    assert expired_sensor._attr_native_unit_of_measurement == "items"
    assert expired_sensor._attr_icon == "mdi:calendar-remove"
    assert expired_sensor.inventory_id == "kitchen_inventory"
    assert expired_sensor.inventory_name == "Kitchen"


@pytest.mark.asyncio
async def test_async_added_to_hass(expired_sensor: ExpiredItemsSensor) -> None:
    with (
        patch.object(expired_sensor, "_async_update_state", new=AsyncMock()) as mock_update,
        patch.object(EventBus, "async_listen") as mock_listen,
        patch.object(expired_sensor, "async_on_remove") as mock_on_remove,
    ):
        await expired_sensor.async_added_to_hass()

        mock_update.assert_awaited_once()
        assert mock_listen.call_count >= 2
        mock_on_remove.assert_called()


@pytest.mark.asyncio
async def test_update_state_with_expired_items(
    expired_sensor: ExpiredItemsSensor, mock_sensor_coordinator: MagicMock
) -> None:
    test_items = [
        {
            "inventory_id": "kitchen_inventory",
            "name": "milk",
            "expiry_date": "2024-06-20",
            "days_until_expiry": 5,
            "threshold": 7,
            "quantity": 1,
        },
        {
            "inventory_id": "kitchen_inventory",
            "name": "yogurt",
            "expiry_date": "2024-06-14",
            "days_until_expiry": -1,
            "threshold": 7,
            "quantity": 1,
        },
        {
            "inventory_id": "kitchen_inventory",
            "name": "cheese",
            "expiry_date": "2024-06-10",
            "days_until_expiry": -5,
            "threshold": 7,
            "quantity": 2,
        },
    ]

    mock_sensor_coordinator.async_get_items_expiring_soon.return_value = test_items

    with patch.object(expired_sensor, "async_write_ha_state"):
        await expired_sensor._async_update_state()

    # Only the two expired items count; the expiring-soon item (milk) is excluded
    assert expired_sensor._attr_native_value == 2

    attributes = expired_sensor._attr_extra_state_attributes
    assert attributes["inventory_id"] == "kitchen_inventory"
    assert attributes["inventory_name"] == "Kitchen"
    assert attributes["total_expired"] == 2

    expired = attributes["expired_items"]
    assert len(expired) == 2
    names = {item["name"] for item in expired}
    assert names == {"yogurt", "cheese"}
    assert "milk" not in names


@pytest.mark.asyncio
async def test_update_state_no_expired_items(
    expired_sensor: ExpiredItemsSensor, mock_sensor_coordinator: MagicMock
) -> None:
    test_items = [
        {
            "inventory_id": "kitchen_inventory",
            "name": "milk",
            "expiry_date": "2024-06-20",
            "days_until_expiry": 5,
            "quantity": 1,
        }
    ]
    mock_sensor_coordinator.async_get_items_expiring_soon.return_value = test_items

    with patch.object(expired_sensor, "async_write_ha_state"):
        await expired_sensor._async_update_state()

    assert expired_sensor._attr_native_value == 0
    assert expired_sensor._attr_extra_state_attributes["total_expired"] == 0
    assert len(expired_sensor._attr_extra_state_attributes["expired_items"]) == 0


@pytest.mark.asyncio
async def test_update_state_empty(
    expired_sensor: ExpiredItemsSensor, mock_sensor_coordinator: MagicMock
) -> None:
    mock_sensor_coordinator.async_get_items_expiring_soon.return_value = []

    with patch.object(expired_sensor, "async_write_ha_state"):
        await expired_sensor._async_update_state()

    assert expired_sensor._attr_native_value == 0


@pytest.mark.asyncio
async def test_coordinator_called_with_inventory_id(
    expired_sensor: ExpiredItemsSensor, mock_sensor_coordinator: MagicMock
) -> None:
    with patch.object(expired_sensor, "async_write_ha_state"):
        await expired_sensor._async_update_state()

    mock_sensor_coordinator.async_get_items_expiring_soon.assert_awaited_once_with(
        "kitchen_inventory"
    )


def test_handle_update_schedules_task(expired_sensor: ExpiredItemsSensor) -> None:
    with patch.object(expired_sensor.hass, "async_create_task") as mock_create_task:
        expired_sensor._handle_update(None)
        mock_create_task.assert_called_once()


def test_handle_update_invalidates_cache(expired_sensor: ExpiredItemsSensor) -> None:
    """_handle_update must evict the per-inventory cache key so the next refresh is fresh."""
    cache: dict = {"kitchen_inventory": (0.0, [{"name": "stale"}]), None: (0.0, [])}
    expired_sensor.coordinator._expiry_cache = cache

    with patch.object(expired_sensor.hass, "async_create_task"):
        expired_sensor._handle_update(None)

    assert "kitchen_inventory" not in cache
    # global (None) key must be left untouched by the per-inventory sensor
    assert None in cache
