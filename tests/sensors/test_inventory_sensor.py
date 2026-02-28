"""Tests for InventorySensor."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import EventBus, HomeAssistant

from custom_components.simple_inventory.sensors import InventorySensor


@pytest.fixture
def mock_sensor_coordinator() -> MagicMock:
    coordinator = MagicMock()
    coordinator.async_get_inventory_statistics = AsyncMock(
        return_value={
            "total_quantity": 0,
            "total_items": 0,
            "categories": {},
            "locations": {},
            "below_threshold": [],
            "expiring_items": [],
        }
    )
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)
    return coordinator


@pytest.fixture
def inventory_sensor(
    hass: HomeAssistant,
    mock_sensor_coordinator: MagicMock,
) -> InventorySensor:
    return InventorySensor(
        hass,
        mock_sensor_coordinator,
        "Kitchen",
        "mdi:fridge",
        "kitchen_123",
    )


def test_init(inventory_sensor: InventorySensor) -> None:
    assert inventory_sensor._attr_name == "Kitchen Inventory"
    assert inventory_sensor._attr_unique_id == "inventory_kitchen_123"
    assert inventory_sensor._attr_icon == "mdi:fridge"
    assert inventory_sensor._attr_native_unit_of_measurement == "items"
    assert inventory_sensor._entry_id == "kitchen_123"


@pytest.mark.asyncio
async def test_async_added_to_hass(inventory_sensor: InventorySensor) -> None:
    with (
        patch.object(inventory_sensor, "_async_update_state", new=AsyncMock()) as mock_update,
        patch.object(EventBus, "async_listen") as mock_listen,
        patch.object(inventory_sensor, "async_on_remove") as mock_on_remove,
    ):
        await inventory_sensor.async_added_to_hass()

        mock_update.assert_awaited_once()
        assert mock_listen.call_count >= 2
        mock_on_remove.assert_called()


def test_handle_update_schedules_task(inventory_sensor: InventorySensor) -> None:
    with patch.object(inventory_sensor.hass, "async_create_task") as mock_create_task:
        inventory_sensor._handle_update(None)
        mock_create_task.assert_called_once()


@pytest.mark.asyncio
async def test_update_state_comprehensive(
    inventory_sensor: InventorySensor,
    mock_sensor_coordinator: MagicMock,
    sample_inventory_data: dict,
) -> None:
    mock_sensor_coordinator.async_get_inventory_statistics.return_value = {
        "total_quantity": 4,
        "total_items": 3,
        "categories": {"dairy": 2, "bakery": 1},
        "locations": {"fridge": 3, "pantry": 1},
        "below_threshold": [],
        "expiring_items": [
            {"name": "milk", "expiry_date": "2024-06-20", "days_until_expiry": 5},
            {"name": "expired_yogurt", "expiry_date": "2024-06-14", "days_until_expiry": -1},
        ],
    }

    with patch.object(inventory_sensor, "async_write_ha_state"):
        await inventory_sensor._async_update_state()

    assert inventory_sensor._attr_native_value == 4

    attrs = inventory_sensor._attr_extra_state_attributes
    assert attrs["inventory_id"] == "kitchen_123"
    assert "items" not in attrs
    assert attrs["total_items"] == 3
    assert attrs["total_quantity"] == 4
    assert attrs["expiring_soon"] == 2


@pytest.mark.asyncio
async def test_update_state_empty_inventory(
    inventory_sensor: InventorySensor,
    mock_sensor_coordinator: MagicMock,
) -> None:
    mock_sensor_coordinator.async_get_inventory_statistics.return_value = {
        "total_quantity": 0,
        "total_items": 0,
        "categories": {},
        "locations": {},
        "below_threshold": [],
        "expiring_items": [],
    }

    with patch.object(inventory_sensor, "async_write_ha_state"):
        await inventory_sensor._async_update_state()

    assert inventory_sensor._attr_native_value == 0
    attrs = inventory_sensor._attr_extra_state_attributes
    assert attrs["inventory_id"] == "kitchen_123"
    assert "items" not in attrs
    assert attrs["total_items"] == 0
    assert attrs["total_quantity"] == 0
    assert attrs["expiring_soon"] == 0


@pytest.mark.asyncio
async def test_coordinator_interaction(
    inventory_sensor: InventorySensor,
    mock_sensor_coordinator: MagicMock,
) -> None:
    with patch.object(inventory_sensor, "async_write_ha_state"):
        await inventory_sensor._async_update_state()

    mock_sensor_coordinator.async_get_inventory_statistics.assert_awaited_once_with("kitchen_123")


@pytest.mark.parametrize(
    ("inventory_name", "expected_attr_name"),
    [
        ("Kitchen", "Kitchen Inventory"),
        ("Main Pantry", "Main Pantry Inventory"),
        ("Garage Storage", "Garage Storage Inventory"),
        ("", " Inventory"),
    ],
)
def test_dynamic_sensor_names(
    hass: HomeAssistant,
    mock_sensor_coordinator: MagicMock,
    inventory_name: str,
    expected_attr_name: str,
) -> None:
    sensor = InventorySensor(
        hass,
        mock_sensor_coordinator,
        inventory_name,
        "mdi:test",
        "test_123",
    )

    assert sensor._attr_name == expected_attr_name
