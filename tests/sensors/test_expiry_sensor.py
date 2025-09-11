"""Tests for ExpiryNotificationSensor."""

from unittest.mock import MagicMock, Mock, call

import pytest
from homeassistant.core import HomeAssistant

from custom_components.simple_inventory.sensors import (
    ExpiryNotificationSensor,
)


class TestExpiryNotificationSensor:
    """Test ExpiryNotificationSensor class."""

    @pytest.fixture
    def expiry_sensor(
        self, hass: HomeAssistant, mock_sensor_coordinator: Mock
    ) -> ExpiryNotificationSensor:
        """Create an expiry sensor."""
        mock_sensor_coordinator.get_items_expiring_soon.side_effect = None
        mock_sensor_coordinator.get_items_expiring_soon.return_value = []
        sensor = ExpiryNotificationSensor(
            hass, mock_sensor_coordinator, "kitchen_inventory", "Kitchen"
        )
        mock_sensor_coordinator.get_items_expiring_soon.reset_mock()
        return sensor

    def test_init(self, expiry_sensor: ExpiryNotificationSensor) -> None:
        """Test sensor initialization."""
        assert expiry_sensor._attr_name == "Kitchen Items Expiring Soon"
        assert (
            expiry_sensor._attr_unique_id
            == "simple_inventory_expiring_items_kitchen_inventory"
        )
        assert expiry_sensor._attr_native_unit_of_measurement == "items"
        assert expiry_sensor.inventory_id == "kitchen_inventory"
        assert expiry_sensor.inventory_name == "Kitchen"

    @pytest.mark.asyncio
    async def test_async_added_to_hass(
        self, expiry_sensor: ExpiryNotificationSensor, hass: HomeAssistant
    ) -> None:
        """Test sensor registration with Home Assistant."""
        expiry_sensor.async_on_remove = MagicMock()

        await expiry_sensor.async_added_to_hass()

        expected_calls = [
            call(
                "simple_inventory_updated_kitchen_inventory",
                expiry_sensor._handle_update,
            ),
            call("simple_inventory_updated", expiry_sensor._handle_update),
        ]

        hass.bus.async_listen.assert_has_calls(expected_calls, any_order=True)

    def test_handle_update(self, expiry_sensor):
        """Test inventory update handling."""
        expiry_sensor._update_data = MagicMock()
        expiry_sensor.async_write_ha_state = MagicMock()

        expiry_sensor._handle_update(None)

        expiry_sensor._update_data.assert_called_once()
        expiry_sensor.async_write_ha_state.assert_called_once()

    def test_handle_coordinator_update(self, expiry_sensor):
        """Test coordinator update handling."""
        expiry_sensor._update_data = MagicMock()
        expiry_sensor.async_write_ha_state = MagicMock()

        expiry_sensor._handle_coordinator_update()
        expiry_sensor._update_data.assert_called_once()
        expiry_sensor.async_write_ha_state.assert_called_once()

    def test_update_data_with_items(
        self, expiry_sensor, mock_sensor_coordinator
    ):
        """Test data update with expiring and expired items."""
        test_items = [
            {
                "inventory_id": "kitchen_inventory",
                "name": "milk",
                "expiry_date": "2024-06-20",
                "days_until_expiry": 5,
                "threshold": 7,
                "quantity": 1,
                "unit": "liter",
                "category": "dairy",
            },
            {
                "inventory_id": "kitchen_inventory",
                "name": "yogurt",
                "expiry_date": "2024-06-14",
                "days_until_expiry": -1,
                "threshold": 7,
                "quantity": 1,
                "unit": "cup",
                "category": "dairy",
            },
        ]

        expiry_sensor.coordinator.get_items_expiring_soon.side_effect = None
        expiry_sensor.coordinator.get_items_expiring_soon.return_value = (
            test_items
        )
        expiry_sensor._update_data()

        # Should have found 2 items total (1 expired + 1 expiring)
        assert expiry_sensor._attr_native_value == 2

        attributes = expiry_sensor._attr_extra_state_attributes
        assert "expiring_items" in attributes
        assert "expired_items" in attributes
        assert attributes["inventory_id"] == "kitchen_inventory"
        assert attributes["inventory_name"] == "Kitchen"

        # Check expired items (days_until_expiry < 0)
        assert len(attributes["expired_items"]) == 1
        assert attributes["expired_items"][0]["name"] == "yogurt"
        assert attributes["expired_items"][0]["days_until_expiry"] == -1

        # Check expiring items (days_until_expiry >= 0)
        assert len(attributes["expiring_items"]) == 1
        assert attributes["expiring_items"][0]["name"] == "milk"
        assert attributes["expiring_items"][0]["days_until_expiry"] == 5

        # Icon should be "remove" because there are expired items
        assert expiry_sensor._attr_icon == "mdi:calendar-remove"

    def test_update_data_no_items(self, expiry_sensor):
        """Test data update with no expiring items."""
        expiry_sensor.coordinator.get_items_expiring_soon.side_effect = None
        expiry_sensor.coordinator.get_items_expiring_soon.return_value = []
        expiry_sensor._update_data()

        assert expiry_sensor._attr_native_value == 0
        assert expiry_sensor._attr_icon == "mdi:calendar-check"

        attributes = expiry_sensor._attr_extra_state_attributes
        assert len(attributes["expiring_items"]) == 0
        assert len(attributes["expired_items"]) == 0

    def test_update_data_only_expiring(self, expiry_sensor):
        """Test data update with only expiring items (no expired)."""
        test_items = [
            {
                "inventory_id": "kitchen_inventory",
                "name": "milk",
                "expiry_date": "2024-06-20",
                "days_until_expiry": 5,
                "threshold": 7,
                "quantity": 1,
            }
        ]

        expiry_sensor.coordinator.get_items_expiring_soon.side_effect = None
        expiry_sensor.coordinator.get_items_expiring_soon.return_value = (
            test_items
        )
        expiry_sensor._update_data()

        assert expiry_sensor._attr_native_value == 1
        assert expiry_sensor._attr_icon == "mdi:calendar-alert"

        attributes = expiry_sensor._attr_extra_state_attributes
        assert len(attributes["expiring_items"]) == 1
        assert len(attributes["expired_items"]) == 0

    def test_coordinator_method_called_with_inventory_id(self, expiry_sensor):
        """Test that coordinator method is called with correct inventory ID."""
        expiry_sensor._update_data()

        expiry_sensor.coordinator.get_items_expiring_soon.assert_called_once_with(
            "kitchen_inventory"
        )
