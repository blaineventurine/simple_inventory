"""Tests for GlobalItemsExpiringSoonSensor."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.simple_inventory.sensors import GlobalItemsExpiringSoonSensor


@pytest.fixture
def mock_sensor_coordinator() -> MagicMock:
    coordinator = MagicMock()
    coordinator.async_get_items_expiring_soon = AsyncMock(return_value=[])
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)
    return coordinator


@pytest.fixture
def global_expiry_sensor(
    hass: HomeAssistant, mock_sensor_coordinator: MagicMock
) -> GlobalItemsExpiringSoonSensor:
    return GlobalItemsExpiringSoonSensor(hass, mock_sensor_coordinator)


def test_init(global_expiry_sensor: GlobalItemsExpiringSoonSensor) -> None:
    assert global_expiry_sensor._attr_name == "All Items Expiring Soon"
    assert global_expiry_sensor._attr_unique_id == "simple_inventory_all_expiring_items"
    assert global_expiry_sensor._attr_native_unit_of_measurement == "items"


@pytest.mark.asyncio
async def test_update_state_multiple_inventories(
    global_expiry_sensor: GlobalItemsExpiringSoonSensor,
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
    ]

    mock_sensor_coordinator.async_get_items_expiring_soon.return_value = test_items

    # Avoid config entry lookups during the test
    with (
        patch.object(global_expiry_sensor, "_get_inventory_name", return_value="Test Inventory"),
        patch.object(global_expiry_sensor, "async_write_ha_state"),
    ):
        await global_expiry_sensor._async_update_state()

    assert global_expiry_sensor._attr_native_value == 1

    attributes = global_expiry_sensor._attr_extra_state_attributes
    assert attributes["inventories_count"] == 2
    assert len(attributes["expiring_items"]) == 1
    assert len(attributes["expired_items"]) == 1


@pytest.mark.asyncio
async def test_coordinator_called_without_inventory_id(
    global_expiry_sensor: GlobalItemsExpiringSoonSensor,
    mock_sensor_coordinator: MagicMock,
) -> None:
    with patch.object(global_expiry_sensor, "async_write_ha_state"):
        await global_expiry_sensor._async_update_state()

    mock_sensor_coordinator.async_get_items_expiring_soon.assert_awaited_once_with()


@pytest.mark.parametrize(
    ("most_urgent_days", "expected_icon"),
    [
        (0, "mdi:calendar-alert"),  # Most urgent expires today
        (1, "mdi:calendar-alert"),  # Most urgent expires tomorrow
        (2, "mdi:calendar-clock"),  # Most urgent expires in 2 days
        (3, "mdi:calendar-clock"),  # Most urgent expires in 3 days
        (4, "mdi:calendar-week"),  # Most urgent expires in 4+ days
    ],
)
@pytest.mark.asyncio
async def test_global_icon_selection(
    global_expiry_sensor: GlobalItemsExpiringSoonSensor,
    mock_sensor_coordinator: MagicMock,
    most_urgent_days: int,
    expected_icon: str,
) -> None:
    test_items = [{"days_until_expiry": most_urgent_days, "inventory_id": "test", "name": "x"}]
    mock_sensor_coordinator.async_get_items_expiring_soon.return_value = test_items

    with (
        patch.object(global_expiry_sensor, "_get_inventory_name", return_value="Test"),
        patch.object(global_expiry_sensor, "async_write_ha_state"),
    ):
        await global_expiry_sensor._async_update_state()

    assert global_expiry_sensor._attr_icon == expected_icon


@pytest.mark.asyncio
async def test_global_icon_no_items(
    global_expiry_sensor: GlobalItemsExpiringSoonSensor,
    mock_sensor_coordinator: MagicMock,
) -> None:
    mock_sensor_coordinator.async_get_items_expiring_soon.return_value = []

    with patch.object(global_expiry_sensor, "async_write_ha_state"):
        await global_expiry_sensor._async_update_state()

    assert global_expiry_sensor._attr_icon == "mdi:calendar-check"
