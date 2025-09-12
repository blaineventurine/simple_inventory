"""Tests for InventorySensor."""

from unittest.mock import MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from typing_extensions import Self

from custom_components.simple_inventory.const import DOMAIN
from custom_components.simple_inventory.sensors import InventorySensor


class TestInventorySensor:
    """Test InventorySensor class."""

    @pytest.fixture
    def inventory_sensor(
        self,
        hass: HomeAssistant,
        mock_sensor_coordinator: MagicMock,
    ) -> InventorySensor:
        """Create an inventory sensor."""
        mock_sensor_coordinator.get_inventory_statistics.return_value = {
            "total_quantity": 0,
            "total_items": 0,
            "categories": [],
            "below_threshold": [],
            "expiring_items": [],
        }

        return InventorySensor(
            hass,
            mock_sensor_coordinator,
            "Kitchen",
            "mdi:fridge",
            "kitchen_123",
        )

    def test_init(self, inventory_sensor: InventorySensor) -> None:
        """Test sensor initialization."""
        assert inventory_sensor._attr_name == "Kitchen Inventory"
        assert inventory_sensor._attr_unique_id == "inventory_kitchen_123"
        assert inventory_sensor._attr_icon == "mdi:fridge"
        assert inventory_sensor._attr_native_unit_of_measurement == "items"
        assert inventory_sensor._entry_id == "kitchen_123"

    @pytest.mark.asyncio
    async def test_async_added_to_hass(
        self: Self, inventory_sensor: InventorySensor, hass: MagicMock
    ) -> None:
        """Test sensor registration with Home Assistant."""
        with patch.object(inventory_sensor, "async_on_remove"):
            await inventory_sensor.async_added_to_hass()

            assert hass.bus.async_listen.call_count == 2
            hass.bus.async_listen.assert_any_call(
                f"{DOMAIN}_updated_{inventory_sensor._entry_id}",
                inventory_sensor._handle_update,
            )
            hass.bus.async_listen.assert_any_call(
                f"{DOMAIN}_updated", inventory_sensor._handle_update
            )

    def test_handle_update(self: Self, inventory_sensor: InventorySensor) -> None:
        """Test inventory update handling."""
        with (
            patch.object(inventory_sensor, "_update_data") as mock_update_data,
            patch.object(inventory_sensor, "async_write_ha_state") as mock_write_state,
        ):

            event = MagicMock()
            inventory_sensor._handle_update(event)

            mock_update_data.assert_called_once()
            mock_write_state.assert_called_once()

    def test_update_data_comprehensive(
        self: Self,
        inventory_sensor: InventorySensor,
        sample_inventory_data: dict,
        mock_sensor_coordinator: MagicMock,
    ) -> None:
        """Test comprehensive data update."""
        kitchen_items = sample_inventory_data["kitchen"]["items"]
        mock_sensor_coordinator.get_all_items.return_value = kitchen_items

        mock_stats = {
            "total_quantity": 4,  # 2 + 1 + 1 from sample data
            "total_items": 3,  # milk, bread, expired_yogurt
            "categories": ["dairy", "bakery"],
            "below_threshold": [],
            "expiring_items": [
                {
                    "name": "milk",
                    "expiry_date": "2024-06-20",
                    "days_until_expiry": 5,
                },
                {
                    "name": "expired_yogurt",
                    "expiry_date": "2024-06-14",
                    "days_until_expiry": -1,
                },
            ],
        }
        mock_sensor_coordinator.get_inventory_statistics.return_value = mock_stats

        inventory_sensor._update_data()

        # Check total quantity calculation: 2 + 1 + 1 = 4
        assert inventory_sensor._attr_native_value == 4

        attributes = inventory_sensor._attr_extra_state_attributes
        assert "inventory_id" in attributes
        assert "items" in attributes
        assert attributes["inventory_id"] == "kitchen_123"

        items = attributes["items"]
        assert len(items) == 3

        milk_item = next(item for item in items if item["name"] == "milk")
        assert milk_item["quantity"] == 2
        assert milk_item["unit"] == "liters"
        assert milk_item["category"] == "dairy"
        assert attributes["total_items"] == 3
        assert attributes["total_quantity"] == 4
        assert attributes["expiring_soon"] == 2

    def test_update_data_empty_inventory(
        self: Self,
        inventory_sensor: InventorySensor,
        mock_sensor_coordinator: MagicMock,
    ) -> None:
        """Test data update with empty inventory."""
        mock_sensor_coordinator.get_all_items.return_value = {}
        mock_sensor_coordinator.get_inventory_statistics.return_value = {
            "total_quantity": 0,
            "total_items": 0,
            "categories": [],
            "below_threshold": [],
            "expiring_items": [],
        }

        inventory_sensor._update_data()

        assert inventory_sensor._attr_native_value == 0
        attributes = inventory_sensor._attr_extra_state_attributes
        assert attributes["inventory_id"] == "kitchen_123"
        assert len(attributes["items"]) == 0
        assert attributes["total_items"] == 0
        assert attributes["total_quantity"] == 0
        assert attributes["expiring_soon"] == 0

    def test_coordinator_interaction(
        self: Self,
        inventory_sensor: InventorySensor,
        mock_sensor_coordinator: MagicMock,
    ) -> None:
        """Test proper interaction with coordinator."""
        mock_sensor_coordinator.get_all_items.reset_mock()
        mock_sensor_coordinator.get_inventory_statistics.reset_mock()

        inventory_sensor._update_data()

        mock_sensor_coordinator.get_all_items.assert_called_once_with("kitchen_123")
        mock_sensor_coordinator.get_inventory_statistics.assert_called_once_with("kitchen_123")

    def test_update_data_called_during_init(
        self: Self, hass: HomeAssistant, mock_sensor_coordinator: MagicMock
    ) -> None:
        """Test that _update_data is called during initialization."""
        mock_sensor_coordinator.get_inventory_statistics.return_value = {
            "total_quantity": 0,
            "total_items": 0,
            "categories": [],
            "below_threshold": [],
            "expiring_items": [],
        }

        with patch.object(InventorySensor, "_update_data") as mock_update:
            _ = InventorySensor(hass, mock_sensor_coordinator, "Test", "mdi:test", "test_123")
            mock_update.assert_called_once()

    @pytest.mark.parametrize(
        "inventory_name,expected_attr_name",
        [
            ("Kitchen", "Kitchen Inventory"),
            ("Main Pantry", "Main Pantry Inventory"),
            ("Garage Storage", "Garage Storage Inventory"),
            ("", " Inventory"),
        ],
    )
    def test_dynamic_sensor_names(
        self: Self,
        hass: HomeAssistant,
        mock_sensor_coordinator: MagicMock,
        inventory_name: str,
        expected_attr_name: str,
    ) -> None:
        """Test sensor name generation with different inventory names."""
        mock_sensor_coordinator.get_inventory_statistics.return_value = {
            "total_quantity": 0,
            "total_items": 0,
            "categories": [],
            "below_threshold": [],
            "expiring_items": [],
        }

        sensor = InventorySensor(
            hass,
            mock_sensor_coordinator,
            inventory_name,
            "mdi:test",
            "test_123",
        )

        assert sensor._attr_name == expected_attr_name
