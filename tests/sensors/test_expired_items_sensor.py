"""Tests for ExpiredItemsSensor."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.simple_inventory.const import DOMAIN
from custom_components.simple_inventory.sensors import ExpiredItemsSensor


@pytest.fixture
def mock_hub() -> MagicMock:
    hub = MagicMock()
    hub.async_items_expiring_soon = AsyncMock(return_value=[])
    return hub


@pytest.fixture
def expired_sensor(hass: HomeAssistant, mock_hub: MagicMock) -> ExpiredItemsSensor:
    return ExpiredItemsSensor(hass, mock_hub, "kitchen_inventory", "Kitchen")


def test_init(expired_sensor: ExpiredItemsSensor) -> None:
    assert expired_sensor._attr_name == "Kitchen Expired Items"
    assert expired_sensor._attr_unique_id == "simple_inventory_expired_items_kitchen_inventory"
    assert expired_sensor._attr_native_unit_of_measurement == "items"
    assert expired_sensor._attr_icon == "mdi:calendar-remove"
    assert expired_sensor.inventory_id == "kitchen_inventory"
    assert expired_sensor.inventory_name == "Kitchen"


@pytest.mark.asyncio
async def test_update_state_with_expired_items(
    expired_sensor: ExpiredItemsSensor, mock_hub: MagicMock
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

    mock_hub.async_items_expiring_soon.return_value = test_items

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
    expired_sensor: ExpiredItemsSensor, mock_hub: MagicMock
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
    mock_hub.async_items_expiring_soon.return_value = test_items

    with patch.object(expired_sensor, "async_write_ha_state"):
        await expired_sensor._async_update_state()

    assert expired_sensor._attr_native_value == 0
    assert expired_sensor._attr_extra_state_attributes["total_expired"] == 0
    assert len(expired_sensor._attr_extra_state_attributes["expired_items"]) == 0


@pytest.mark.asyncio
async def test_update_state_empty(expired_sensor: ExpiredItemsSensor, mock_hub: MagicMock) -> None:
    mock_hub.async_items_expiring_soon.return_value = []

    with patch.object(expired_sensor, "async_write_ha_state"):
        await expired_sensor._async_update_state()

    assert expired_sensor._attr_native_value == 0


@pytest.mark.asyncio
async def test_hub_called_with_inventory_id(
    expired_sensor: ExpiredItemsSensor, mock_hub: MagicMock
) -> None:
    with patch.object(expired_sensor, "async_write_ha_state"):
        await expired_sensor._async_update_state()

    mock_hub.async_items_expiring_soon.assert_awaited_once_with("kitchen_inventory")


def test_handle_update_schedules_task(expired_sensor: ExpiredItemsSensor) -> None:
    with patch.object(
        expired_sensor.hass, "async_create_task", side_effect=lambda coro: coro.close()
    ) as mock_create_task:
        expired_sensor._handle_update(None)
        mock_create_task.assert_called_once()


def test_handle_update_invalidates_cache(
    expired_sensor: ExpiredItemsSensor, mock_hub: MagicMock
) -> None:
    """_handle_update must evict the per-inventory cache key so the next refresh is fresh."""
    with patch.object(
        expired_sensor.hass, "async_create_task", side_effect=lambda coro: coro.close()
    ):
        expired_sensor._handle_update(None)

    mock_hub.invalidate.assert_called_once_with("kitchen_inventory")


async def test_refreshes_only_on_entry_scoped_event(
    hass: HomeAssistant,
    expired_sensor: ExpiredItemsSensor,
    mock_hub: MagicMock,
    attach_sensor: Callable[[Any], Awaitable[Any]],
) -> None:
    await attach_sensor(expired_sensor)
    mock_hub.async_items_expiring_soon.reset_mock()

    hass.bus.async_fire(f"{DOMAIN}_updated")
    await hass.async_block_till_done()
    mock_hub.async_items_expiring_soon.assert_not_awaited()

    hass.bus.async_fire(f"{DOMAIN}_updated_kitchen_inventory")
    await hass.async_block_till_done()
    mock_hub.async_items_expiring_soon.assert_awaited_once_with("kitchen_inventory")


async def test_local_midnight_moves_item_into_expired(
    expired_sensor: ExpiredItemsSensor,
    mock_hub: MagicMock,
    attach_sensor: Callable[[Any], Awaitable[Any]],
    fire_next_local_midnight: Callable[[], Awaitable[None]],
) -> None:
    """An item expiring today must flip to expired after midnight with no inventory write."""
    mock_hub.async_items_expiring_soon.return_value = [
        {"inventory_id": "kitchen_inventory", "name": "milk", "days_until_expiry": 0}
    ]
    await attach_sensor(expired_sensor)
    assert expired_sensor._attr_native_value == 0

    mock_hub.invalidate.reset_mock()
    mock_hub.async_items_expiring_soon.return_value = [
        {"inventory_id": "kitchen_inventory", "name": "milk", "days_until_expiry": -1}
    ]

    await fire_next_local_midnight()

    assert expired_sensor._attr_native_value == 1
    mock_hub.invalidate.assert_called_once_with("kitchen_inventory")
