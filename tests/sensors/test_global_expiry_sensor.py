"""Tests for GlobalItemsExpiringSoonSensor."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.simple_inventory.const import DOMAIN
from custom_components.simple_inventory.sensors import GlobalItemsExpiringSoonSensor

SENSOR_MODULE = "custom_components.simple_inventory.sensors.global_expiry_sensor"


@pytest.fixture
def mock_hub() -> MagicMock:
    hub = MagicMock()
    hub.async_items_expiring_soon = AsyncMock(return_value=[])
    return hub


@pytest.fixture
def global_expiry_sensor(hass: HomeAssistant, mock_hub: MagicMock) -> GlobalItemsExpiringSoonSensor:
    return GlobalItemsExpiringSoonSensor(hass, mock_hub)


def test_init(global_expiry_sensor: GlobalItemsExpiringSoonSensor) -> None:
    assert global_expiry_sensor._attr_name == "All Items Expiring Soon"
    assert global_expiry_sensor._attr_unique_id == "simple_inventory_all_expiring_items"
    assert global_expiry_sensor._attr_native_unit_of_measurement == "items"


@pytest.mark.asyncio
async def test_update_state_multiple_inventories(
    global_expiry_sensor: GlobalItemsExpiringSoonSensor,
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
    ]

    mock_hub.async_items_expiring_soon.return_value = test_items

    # Avoid config entry lookups during the test
    with (
        patch(f"{SENSOR_MODULE}.inventory_display_name", return_value="Test Inventory"),
        patch.object(global_expiry_sensor, "async_write_ha_state"),
    ):
        await global_expiry_sensor._async_update_state()

    assert global_expiry_sensor._attr_native_value == 1

    attributes = global_expiry_sensor._attr_extra_state_attributes
    assert attributes["inventories_count"] == 2
    assert len(attributes["expiring_items"]) == 1
    assert len(attributes["expired_items"]) == 1


@pytest.mark.asyncio
async def test_hub_called_without_inventory_id(
    global_expiry_sensor: GlobalItemsExpiringSoonSensor,
    mock_hub: MagicMock,
) -> None:
    with patch.object(global_expiry_sensor, "async_write_ha_state"):
        await global_expiry_sensor._async_update_state()

    mock_hub.async_items_expiring_soon.assert_awaited_once_with()


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
    mock_hub: MagicMock,
    most_urgent_days: int,
    expected_icon: str,
) -> None:
    test_items = [{"days_until_expiry": most_urgent_days, "inventory_id": "test", "name": "x"}]
    mock_hub.async_items_expiring_soon.return_value = test_items

    with (
        patch(f"{SENSOR_MODULE}.inventory_display_name", return_value="Test"),
        patch.object(global_expiry_sensor, "async_write_ha_state"),
    ):
        await global_expiry_sensor._async_update_state()

    assert global_expiry_sensor._attr_icon == expected_icon


@pytest.mark.asyncio
async def test_global_icon_no_items(
    global_expiry_sensor: GlobalItemsExpiringSoonSensor,
    mock_hub: MagicMock,
) -> None:
    mock_hub.async_items_expiring_soon.return_value = []

    with patch.object(global_expiry_sensor, "async_write_ha_state"):
        await global_expiry_sensor._async_update_state()

    assert global_expiry_sensor._attr_icon == "mdi:calendar-check"


async def test_refreshes_only_on_general_event(
    hass: HomeAssistant,
    global_expiry_sensor: GlobalItemsExpiringSoonSensor,
    mock_hub: MagicMock,
    attach_sensor: Callable[[Any], Awaitable[Any]],
) -> None:
    await attach_sensor(global_expiry_sensor)
    mock_hub.async_items_expiring_soon.reset_mock()

    hass.bus.async_fire(f"{DOMAIN}_updated")
    await hass.async_block_till_done()

    mock_hub.async_items_expiring_soon.assert_awaited_once_with()


async def test_local_midnight_recomputes_and_evicts_cache(
    global_expiry_sensor: GlobalItemsExpiringSoonSensor,
    mock_hub: MagicMock,
    attach_sensor: Callable[[Any], Awaitable[Any]],
    fire_next_local_midnight: Callable[[], Awaitable[None]],
) -> None:
    await attach_sensor(global_expiry_sensor)
    mock_hub.invalidate.reset_mock()
    mock_hub.async_items_expiring_soon.reset_mock()

    await fire_next_local_midnight()

    mock_hub.async_items_expiring_soon.assert_awaited_once_with()
    mock_hub.invalidate.assert_called_once_with(None)
