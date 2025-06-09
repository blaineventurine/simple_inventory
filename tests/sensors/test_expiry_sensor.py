"""Tests for ExpiryNotificationSensor."""
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, call, patch
from custom_components.simple_inventory.sensors.expiry_sensor import ExpiryNotificationSensor


class TestExpiryNotificationSensor:
    """Test ExpiryNotificationSensor class."""

    @pytest.fixture
    def expiry_sensor(self, hass, mock_sensor_coordinator):
        """Create an expiry sensor."""
        # Ensure coordinator.expiry_threshold_days returns an integer
        mock_sensor_coordinator.expiry_threshold_days.return_value = 7

        sensor = ExpiryNotificationSensor(
            hass, mock_sensor_coordinator, days_threshold=7)
        # Mock the inventory name method
        sensor._get_inventory_name = MagicMock(return_value="Kitchen")
        return sensor

    def test_init(self, expiry_sensor):
        """Test sensor initialization."""
        assert expiry_sensor._attr_name == "Items Expiring Soon"
        assert expiry_sensor._attr_unique_id == "simple_inventory_expiring_items"
        # Icon will be set based on data during init
        assert expiry_sensor._attr_native_unit_of_measurement == "items"
        assert expiry_sensor._days_threshold == 7
        assert expiry_sensor.current_threshold == 7

    def test_current_threshold_property(self, expiry_sensor):
        """Test current_threshold property."""
        assert expiry_sensor.current_threshold == 7

        expiry_sensor._days_threshold = 14
        assert expiry_sensor.current_threshold == 14

    @pytest.mark.asyncio
    async def test_async_added_to_hass(self, expiry_sensor, hass, sample_inventory_data):
        """Test sensor registration with Home Assistant."""
        expiry_sensor.async_on_remove = MagicMock()

        await expiry_sensor.async_added_to_hass()

        # Verify general update listener was registered
        # At least general and threshold updates
        assert hass.bus.async_listen.call_count >= 2

        # Verify specific inventory listeners were registered
        expected_calls = [
            call("simple_inventory_updated", expiry_sensor._handle_update),
            call("simple_inventory_threshold_updated",
                 expiry_sensor._handle_threshold_update),
        ]

        hass.bus.async_listen.assert_has_calls(expected_calls, any_order=True)

    def test_handle_update(self, expiry_sensor):
        """Test inventory update handling."""
        expiry_sensor._update_data = MagicMock()
        expiry_sensor.async_write_ha_state = MagicMock()

        expiry_sensor._handle_update(None)

        expiry_sensor._update_data.assert_called_once()
        expiry_sensor.async_write_ha_state.assert_called_once()

    def test_handle_threshold_update(self, expiry_sensor):
        """Test threshold update handling."""
        expiry_sensor._update_data = MagicMock()
        expiry_sensor.async_write_ha_state = MagicMock()

        event = MagicMock()
        event.data = {"new_threshold": 14}

        expiry_sensor._handle_threshold_update(event)

        assert expiry_sensor._days_threshold == 14
        expiry_sensor._update_data.assert_called_once()
        expiry_sensor.async_write_ha_state.assert_called_once()

    def test_update_threshold(self, expiry_sensor):
        """Test manual threshold updating."""
        expiry_sensor._update_data = MagicMock()

        # Test successful update
        result = expiry_sensor.update_threshold(14)

        assert result is True
        assert expiry_sensor._days_threshold == 14
        expiry_sensor._update_data.assert_called_once()

    def test_update_threshold_same_value(self, expiry_sensor):
        """Test updating threshold to same value."""
        expiry_sensor._update_data = MagicMock()

        result = expiry_sensor.update_threshold(7)  # Same as initial value

        assert result is False
        expiry_sensor._update_data.assert_not_called()

    def test_update_data_comprehensive(self, expiry_sensor, sample_inventory_data):
        """Test comprehensive data update with various scenarios."""
        # Patch datetime.now to return a fixed date for consistent testing
        fixed_date = datetime(2024, 6, 15)
        with patch('datetime.datetime') as mock_dt:
            mock_dt.now.return_value = fixed_date
            mock_dt.strptime.side_effect = datetime.strptime

            # Set up test data with known expiry dates
            expiry_sensor.coordinator.get_data.return_value = {
                "inventories": {
                    "kitchen": {
                        "items": {
                            "milk": {
                                "quantity": 1,
                                "expiry_date": "2024-06-20",  # 5 days from now
                                "unit": "liter",
                                "category": "dairy"
                            },
                            "yogurt": {
                                "quantity": 1,
                                "expiry_date": "2024-06-14",  # 1 day ago
                                "unit": "cup",
                                "category": "dairy"
                            },
                            "bread": {
                                "quantity": 1,
                                "expiry_date": "",  # No expiry date
                                "unit": "loaf",
                                "category": "bakery"
                            }
                        }
                    }
                }
            }

            expiry_sensor._update_data()

            # Should have found expired yogurt and expiring milk
            assert expiry_sensor._attr_native_value == 2

            attributes = expiry_sensor._attr_extra_state_attributes
            assert "expiring_items" in attributes
            assert "expired_items" in attributes
            assert "threshold_days" in attributes
            assert attributes["threshold_days"] == 7

            # Check expired items
            assert len(attributes["expired_items"]) == 1
            assert attributes["expired_items"][0]["name"] == "yogurt"
            assert attributes["expired_items"][0]["days_left"] == -1

            # Check expiring items
            assert len(attributes["expiring_items"]) == 1
            assert attributes["expiring_items"][0]["name"] == "milk"
            assert attributes["expiring_items"][0]["days_left"] == 5

    def test_get_inventory_name_unknown(self, expiry_sensor, hass):
        """Test getting inventory name for unknown inventory."""
        # Mock no matching entities or config entries
        hass.states.async_entity_ids.return_value = []
        hass.states.get.return_value = None
        hass.config_entries.async_entries.return_value = []

        # Reset the mock to test the actual method
        expiry_sensor._get_inventory_name = ExpiryNotificationSensor._get_inventory_name.__get__(
            expiry_sensor, ExpiryNotificationSensor)

        name = expiry_sensor._get_inventory_name("unknown")
        assert name == "Unknown Inventory"

    @pytest.mark.parametrize("days_left,expected_icon", [
        (-1, "mdi:calendar-remove"),  # Expired
        (0, "mdi:calendar-alert"),    # Expires today
        (1, "mdi:calendar-alert"),    # Expires tomorrow
        (2, "mdi:calendar-clock"),    # Expires in 2 days
        (3, "mdi:calendar-clock"),    # Expires in 3 days
        (4, "mdi:calendar-week"),     # Expires in 4 days
        (10, "mdi:calendar-check"),   # No urgent expiry
    ])
    def test_icon_selection_logic(self, expiry_sensor, days_left, expected_icon):
        """Test icon selection for different expiry scenarios."""
        today = datetime.now().date()
        expiry_date = today + timedelta(days=days_left)

        # For days_left=10 (beyond threshold), we should have no expiring items
        if days_left > 7:  # Beyond threshold
            expiry_sensor.coordinator.get_data.return_value = {
                "inventories": {
                    "kitchen": {
                        "items": {
                            "test_item": {
                                "quantity": 1,
                                "expiry_date": expiry_date.strftime("%Y-%m-%d"),
                            }
                        }
                    }
                }
            }
            expiry_sensor._update_data()
            assert expiry_sensor._attr_icon == "mdi:calendar-check"
        else:
            # Set up test data with a single item having the specified expiry
            with patch('datetime.datetime') as mock_dt:
                fixed_date = datetime.now()
                mock_dt.now.return_value = fixed_date
                mock_dt.strptime.side_effect = datetime.strptime

                expiry_sensor.coordinator.get_data.return_value = {
                    "inventories": {
                        "kitchen": {
                            "items": {
                                "test_item": {
                                    "quantity": 1,
                                    "expiry_date": expiry_date.strftime("%Y-%m-%d"),
                                }
                            }
                        }
                    }
                }

                expiry_sensor._update_data()
                assert expiry_sensor._attr_icon == expected_icon
