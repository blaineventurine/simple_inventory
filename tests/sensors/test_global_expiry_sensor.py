from unittest.mock import MagicMock

import pytest

from custom_components.simple_inventory.sensors import (
    GlobalExpiryNotificationSensor,
)


class TestGlobalExpiryNotificationSensor:
    """Test GlobalExpiryNotificationSensor class."""

    @pytest.fixture
    def global_expiry_sensor(self, hass, mock_sensor_coordinator):
        """Create a global expiry sensor."""
        mock_sensor_coordinator.get_items_expiring_soon.side_effect = None
        mock_sensor_coordinator.get_items_expiring_soon.return_value = []
        mock_sensor_coordinator.get_data.return_value = {"inventories": {}}

        sensor = GlobalExpiryNotificationSensor(hass, mock_sensor_coordinator)
        mock_sensor_coordinator.get_items_expiring_soon.reset_mock()
        return sensor

    def test_init(self, global_expiry_sensor):
        """Test global sensor initialization."""
        assert global_expiry_sensor._attr_name == "All Items Expiring Soon"
        assert (
            global_expiry_sensor._attr_unique_id
            == "simple_inventory_all_expiring_items"
        )
        assert global_expiry_sensor._attr_native_unit_of_measurement == "items"

    def test_update_data_multiple_inventories(self, global_expiry_sensor):
        """Test data update with items from multiple inventories."""
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

        global_expiry_sensor.coordinator.get_items_expiring_soon.side_effect = (
            None
        )
        global_expiry_sensor.coordinator.get_items_expiring_soon.return_value = (
            test_items
        )
        global_expiry_sensor._get_inventory_name = MagicMock(
            side_effect=lambda x: f"Inventory {x}"
        )

        global_expiry_sensor._update_data()

        assert global_expiry_sensor._attr_native_value == 2

        attributes = global_expiry_sensor._attr_extra_state_attributes
        assert attributes["inventories_count"] == 2
        assert len(attributes["expiring_items"]) == 1  # days_until_expiry >= 0
        assert len(attributes["expired_items"]) == 1  # days_until_expiry < 0

    def test_coordinator_method_called_without_inventory_id(
        self, global_expiry_sensor
    ):
        """Test that coordinator method is called without inventory ID for global sensor."""
        global_expiry_sensor.coordinator.get_items_expiring_soon.reset_mock()
        global_expiry_sensor._update_data()
        global_expiry_sensor.coordinator.get_items_expiring_soon.assert_called_once_with()

    @pytest.mark.parametrize(
        "most_urgent_days,expected_icon",
        [
            (-1, "mdi:calendar-remove"),  # Has expired items
            (0, "mdi:calendar-alert"),  # Most urgent expires today
            (1, "mdi:calendar-alert"),  # Most urgent expires tomorrow
            (2, "mdi:calendar-clock"),  # Most urgent expires in 2 days
            (3, "mdi:calendar-clock"),  # Most urgent expires in 3 days
            (4, "mdi:calendar-week"),  # Most urgent expires in 4+ days
        ],
    )
    def test_global_icon_selection(
        self, global_expiry_sensor, most_urgent_days, expected_icon
    ):
        """Test icon selection for global sensor based on most urgent item."""
        if most_urgent_days < 0:
            test_items = [
                {"days_until_expiry": most_urgent_days, "inventory_id": "test"}
            ]
        else:
            test_items = [
                {"days_until_expiry": most_urgent_days, "inventory_id": "test"}
            ]

        global_expiry_sensor.coordinator.get_items_expiring_soon.side_effect = (
            None
        )
        global_expiry_sensor.coordinator.get_items_expiring_soon.return_value = (
            test_items
        )
        global_expiry_sensor._get_inventory_name = MagicMock(
            return_value="Test"
        )

        global_expiry_sensor._update_data()
        assert global_expiry_sensor._attr_icon == expected_icon
