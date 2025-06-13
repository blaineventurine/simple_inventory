"""Tests for InventorySensor."""

from unittest.mock import MagicMock, patch

import pytest

from custom_components.simple_inventory.const import DOMAIN
from custom_components.simple_inventory.sensors import InventorySensor


class TestInventorySensor:
    """Test InventorySensor class."""

    @pytest.fixture
    def inventory_sensor(self, hass, mock_sensor_coordinator):
        """Create an inventory sensor."""
        mock_sensor_coordinator.get_inventory_statistics.return_value = {
            "total_quantity": 0,
            "total_items": 0,
            "categories": [],
            "below_threshold": [],
            "expiring_items": [],
        }

        return InventorySensor(
            hass, mock_sensor_coordinator, "Kitchen", "mdi:fridge", "kitchen_123"
        )

    def test_init(self, inventory_sensor):
        """Test sensor initialization."""
        assert inventory_sensor._attr_name == "Kitchen Inventory"
        assert inventory_sensor._attr_unique_id == "inventory_kitchen_123"
        assert inventory_sensor._attr_icon == "mdi:fridge"
        assert inventory_sensor._attr_native_unit_of_measurement == "items"
        assert inventory_sensor._entry_id == "kitchen_123"

    @pytest.mark.asyncio
    async def test_async_added_to_hass(self, inventory_sensor, hass):
        """Test sensor registration with Home Assistant."""
        inventory_sensor.async_on_remove = MagicMock()

        await inventory_sensor.async_added_to_hass()
        assert hass.bus.async_listen.call_count == 2
        hass.bus.async_listen.assert_any_call(
            f"{DOMAIN}_updated_{inventory_sensor._entry_id}",
            inventory_sensor._handle_update,
        )
        hass.bus.async_listen.assert_any_call(
            f"{DOMAIN}_updated", inventory_sensor._handle_update
        )

    def test_handle_update(self, inventory_sensor):
        """Test inventory update handling."""
        inventory_sensor._update_data = MagicMock()
        inventory_sensor.async_write_ha_state = MagicMock()
        event = MagicMock()
        inventory_sensor._handle_update(event)

        inventory_sensor._update_data.assert_called_once()
        inventory_sensor.async_write_ha_state.assert_called_once()

    def test_update_data_comprehensive(self, inventory_sensor, sample_inventory_data):
        """Test comprehensive data update."""
        kitchen_items = sample_inventory_data["kitchen"]["items"]
        inventory_sensor.coordinator.get_all_items.return_value = kitchen_items

        mock_stats = {
            "total_quantity": 4,  # 2 + 1 + 1 from sample data
            "total_items": 3,  # milk, bread, expired_yogurt
            "categories": ["dairy", "bakery"],
            "below_threshold": [],
            "expiring_items": [
                {"name": "milk", "expiry_date": "2024-06-20", "days_until_expiry": 5},
                {
                    "name": "expired_yogurt",
                    "expiry_date": "2024-06-14",
                    "days_until_expiry": -1,
                },
            ],
        }
        inventory_sensor.coordinator.get_inventory_statistics.return_value = mock_stats

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

    def test_update_data_empty_inventory(self, inventory_sensor):
        """Test data update with empty inventory."""
        inventory_sensor.coordinator.get_all_items.return_value = {}
        inventory_sensor.coordinator.get_inventory_statistics.return_value = {
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

    def test_coordinator_interaction(self, inventory_sensor):
        """Test proper interaction with coordinator."""
        inventory_sensor.coordinator.get_all_items.reset_mock()
        inventory_sensor.coordinator.get_inventory_statistics.reset_mock()

        inventory_sensor._update_data()

        inventory_sensor.coordinator.get_all_items.assert_called_once_with(
            "kitchen_123"
        )
        inventory_sensor.coordinator.get_inventory_statistics.assert_called_once_with(
            "kitchen_123"
        )

    def test_update_data_called_during_init(self, hass, mock_sensor_coordinator):
        """Test that _update_data is called during initialization."""
        mock_sensor_coordinator.get_inventory_statistics.return_value = {
            "total_quantity": 0,
            "total_items": 0,
            "categories": [],
            "below_threshold": [],
            "expiring_items": [],
        }

        with patch.object(InventorySensor, "_update_data") as mock_update:
            _ = InventorySensor(
                hass, mock_sensor_coordinator, "Test", "mdi:test", "test_123"
            )
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
        self, hass, mock_sensor_coordinator, inventory_name, expected_attr_name
    ):
        """Test sensor name generation with different inventory names."""
        mock_sensor_coordinator.get_inventory_statistics.return_value = {
            "total_quantity": 0,
            "total_items": 0,
            "categories": [],
            "below_threshold": [],
            "expiring_items": [],
        }

        sensor = InventorySensor(
            hass, mock_sensor_coordinator, inventory_name, "mdi:test", "test_123"
        )

        assert sensor._attr_name == expected_attr_name
