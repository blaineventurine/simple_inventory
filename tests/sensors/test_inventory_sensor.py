"""Tests for InventorySensor."""
import pytest
from unittest.mock import MagicMock, patch
from custom_components.simple_inventory.sensors.inventory_sensor import InventorySensor
from custom_components.simple_inventory.const import DOMAIN


class TestInventorySensor:
    """Test InventorySensor class."""

    @pytest.fixture
    def inventory_sensor(self, hass, mock_sensor_coordinator):
        """Create an inventory sensor."""
        return InventorySensor(
            hass,
            mock_sensor_coordinator,
            "Kitchen",
            "mdi:fridge",
            "kitchen_123"
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

        # Verify both listeners were registered
        assert hass.bus.async_listen.call_count == 2

        # Verify specific inventory update listener
        hass.bus.async_listen.assert_any_call(
            f"{DOMAIN}_updated_{inventory_sensor._entry_id}",
            inventory_sensor._handle_update
        )

        # Verify general update listener
        hass.bus.async_listen.assert_any_call(
            f"{DOMAIN}_updated",
            inventory_sensor._handle_update
        )

    def test_handle_update(self, inventory_sensor):
        """Test inventory update handling."""
        inventory_sensor._update_data = MagicMock()
        inventory_sensor.async_write_ha_state = MagicMock()

        # Test with mock event
        event = MagicMock()
        inventory_sensor._handle_update(event)

        inventory_sensor._update_data.assert_called_once()
        inventory_sensor.async_write_ha_state.assert_called_once()

    def test_update_data_comprehensive(self, inventory_sensor, sample_inventory_data):
        """Test comprehensive data update."""
        # Set up the coordinator to return kitchen data
        kitchen_items = sample_inventory_data["kitchen"]["items"]
        inventory_sensor.coordinator.get_all_items.return_value = kitchen_items

        inventory_sensor._update_data()

        # Check total quantity calculation: 2 + 1 + 1 = 4
        assert inventory_sensor._attr_native_value == 4

        # Check attributes structure
        attributes = inventory_sensor._attr_extra_state_attributes
        assert "inventory_id" in attributes
        assert "items" in attributes
        assert attributes["inventory_id"] == "kitchen_123"

        # Check items list
        items = attributes["items"]
        assert len(items) == 3

        # Verify item structure
        milk_item = next(item for item in items if item["name"] == "milk")
        assert milk_item["quantity"] == 2
        assert milk_item["unit"] == "liters"
        assert milk_item["category"] == "dairy"

    def test_update_data_empty_inventory(self, inventory_sensor):
        """Test data update with empty inventory."""
        inventory_sensor.coordinator.get_all_items.return_value = {}

        inventory_sensor._update_data()

        assert inventory_sensor._attr_native_value == 0
        attributes = inventory_sensor._attr_extra_state_attributes
        assert attributes["inventory_id"] == "kitchen_123"
        assert len(attributes["items"]) == 0

    def test_coordinator_interaction(self, inventory_sensor):
        """Test proper interaction with coordinator."""
        # Reset the mock to clear the call from __init__
        inventory_sensor.coordinator.get_all_items.reset_mock()

        inventory_sensor._update_data()

        # Verify coordinator method was called with correct entry_id
        inventory_sensor.coordinator.get_all_items.assert_called_once_with(
            "kitchen_123")

    def test_update_data_called_during_init(self, hass, mock_sensor_coordinator):
        """Test that _update_data is called during initialization."""
        with patch.object(InventorySensor, '_update_data') as mock_update:
            sensor = InventorySensor(
                hass,
                mock_sensor_coordinator,
                "Test",
                "mdi:test",
                "test_123"
            )

            mock_update.assert_called_once()

    @pytest.mark.parametrize("inventory_name,expected_attr_name", [
        ("Kitchen", "Kitchen Inventory"),
        ("Main Pantry", "Main Pantry Inventory"),
        ("Garage Storage", "Garage Storage Inventory"),
        ("", " Inventory"),  # Edge case with empty name
    ])
    def test_dynamic_sensor_names(self, hass, mock_sensor_coordinator, inventory_name, expected_attr_name):
        """Test sensor name generation with different inventory names."""
        sensor = InventorySensor(
            hass,
            mock_sensor_coordinator,
            inventory_name,
            "mdi:test",
            "test_123"
        )

        assert sensor._attr_name == expected_attr_name
