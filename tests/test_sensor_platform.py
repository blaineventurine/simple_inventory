"""Tests for sensor platform setup."""
import pytest
from unittest.mock import MagicMock, patch, call
from custom_components.simple_inventory.sensor import async_setup_entry


class TestSensorPlatform:
    """Test sensor platform setup."""

    @pytest.fixture
    def mock_config_entry_with_options(self):
        """Create a mock config entry with options."""
        config_entry = MagicMock()
        config_entry.entry_id = "test_entry_123"
        config_entry.data = {
            "name": "Kitchen Inventory",
            "icon": "mdi:fridge"
        }
        config_entry.options = {
            "expiry_threshold": 14
        }
        return config_entry

    @pytest.fixture
    def mock_config_entry_minimal(self):
        """Create a mock config entry with minimal data."""
        config_entry = MagicMock()
        config_entry.entry_id = "minimal_entry_456"
        config_entry.data = {}
        config_entry.options = {}
        return config_entry

    @pytest.fixture
    def mock_hass_with_coordinator(self, mock_coordinator, domain):
        """Create a mock hass with coordinator in data."""
        hass = MagicMock()
        hass.data = {
            domain: {
                "coordinator": mock_coordinator
            }
        }
        hass.config_entries.async_entries.return_value = []
        return hass

    @pytest.fixture
    def mock_add_entities(self):
        """Create a mock async_add_entities callback."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_async_setup_entry_basic(self, mock_hass_with_coordinator, mock_config_entry_with_options, mock_add_entities):
        """Test basic sensor setup."""
        # Mock that this is the only config entry
        mock_hass_with_coordinator.config_entries.async_entries.return_value = [
            mock_config_entry_with_options]

        with patch('custom_components.simple_inventory.sensor.InventorySensor') as mock_inventory_sensor, \
                patch('custom_components.simple_inventory.sensor.ExpiryNotificationSensor') as mock_expiry_sensor:

            await async_setup_entry(mock_hass_with_coordinator, mock_config_entry_with_options, mock_add_entities)

            # Verify InventorySensor was created with correct parameters
            mock_inventory_sensor.assert_called_once_with(
                mock_hass_with_coordinator,
                mock_hass_with_coordinator.data["simple_inventory"]["coordinator"],
                "Kitchen Inventory",
                "mdi:fridge",
                "test_entry_123"
            )

            # Verify ExpiryNotificationSensor was created (first entry)
            mock_expiry_sensor.assert_called_once_with(
                mock_hass_with_coordinator,
                mock_hass_with_coordinator.data["simple_inventory"]["coordinator"],
                14  # threshold from options
            )

            # Verify async_add_entities was called twice
            assert mock_add_entities.call_count == 2

    @pytest.mark.asyncio
    async def test_async_setup_entry_minimal_data(self, mock_hass_with_coordinator, mock_config_entry_minimal, mock_add_entities):
        """Test setup with minimal config entry data."""
        # Mock that this is the only config entry
        mock_hass_with_coordinator.config_entries.async_entries.return_value = [
            mock_config_entry_minimal]

        with patch('custom_components.simple_inventory.sensor.InventorySensor') as mock_inventory_sensor, \
                patch('custom_components.simple_inventory.sensor.ExpiryNotificationSensor') as mock_expiry_sensor:

            await async_setup_entry(mock_hass_with_coordinator, mock_config_entry_minimal, mock_add_entities)

            # Verify InventorySensor was created with default values
            mock_inventory_sensor.assert_called_once_with(
                mock_hass_with_coordinator,
                mock_hass_with_coordinator.data["simple_inventory"]["coordinator"],
                "Inventory",  # Default name
                "mdi:package-variant",  # Default icon
                "minimal_entry_456"
            )

            # Verify ExpiryNotificationSensor was created with default threshold
            mock_expiry_sensor.assert_called_once_with(
                mock_hass_with_coordinator,
                mock_hass_with_coordinator.data["simple_inventory"]["coordinator"],
                7  # Default threshold
            )

    @pytest.mark.asyncio
    async def test_async_setup_entry_not_first_entry(self, mock_hass_with_coordinator, mock_config_entry_with_options, mock_add_entities):
        """Test setup when this is not the first config entry."""
        # Create a different "first" entry
        first_entry = MagicMock()
        first_entry.entry_id = "first_entry"

        mock_hass_with_coordinator.config_entries.async_entries.return_value = [
            first_entry,  # This is the first entry
            mock_config_entry_with_options  # This is the second entry
        ]

        with patch('custom_components.simple_inventory.sensor.InventorySensor') as mock_inventory_sensor, \
                patch('custom_components.simple_inventory.sensor.ExpiryNotificationSensor') as mock_expiry_sensor:

            await async_setup_entry(mock_hass_with_coordinator, mock_config_entry_with_options, mock_add_entities)

            # Verify InventorySensor was created
            mock_inventory_sensor.assert_called_once()

            # Verify ExpiryNotificationSensor was NOT created (not first entry)
            mock_expiry_sensor.assert_not_called()

            # Verify async_add_entities was called only once (for inventory sensor)
            mock_add_entities.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_setup_entry_multiple_config_entries(self, mock_hass_with_coordinator, mock_add_entities):
        """Test setup with multiple config entries."""
        # Create multiple config entries
        entry1 = MagicMock()
        entry1.entry_id = "entry_1"
        entry1.data = {"name": "Kitchen", "icon": "mdi:fridge"}
        entry1.options = {"expiry_threshold": 5}

        entry2 = MagicMock()
        entry2.entry_id = "entry_2"
        entry2.data = {"name": "Pantry", "icon": "mdi:food"}
        entry2.options = {}

        entry3 = MagicMock()
        entry3.entry_id = "entry_3"
        entry3.data = {"name": "Garage"}
        entry3.options = {"expiry_threshold": 30}

        all_entries = [entry1, entry2, entry3]
        mock_hass_with_coordinator.config_entries.async_entries.return_value = all_entries

        with patch('custom_components.simple_inventory.sensor.InventorySensor') as mock_inventory_sensor, \
                patch('custom_components.simple_inventory.sensor.ExpiryNotificationSensor') as mock_expiry_sensor:

            # Test setup for first entry
            await async_setup_entry(mock_hass_with_coordinator, entry1, mock_add_entities)

            # Should create expiry sensor for first entry
            mock_expiry_sensor.assert_called_once_with(
                mock_hass_with_coordinator,
                mock_hass_with_coordinator.data["simple_inventory"]["coordinator"],
                5  # threshold from entry1 options
            )

            # Reset mocks
            mock_inventory_sensor.reset_mock()
            mock_expiry_sensor.reset_mock()
            mock_add_entities.reset_mock()

            # Test setup for second entry
            await async_setup_entry(mock_hass_with_coordinator, entry2, mock_add_entities)

            # Should NOT create expiry sensor for second entry
            mock_expiry_sensor.assert_not_called()
            mock_add_entities.assert_called_once()  # Only inventory sensor

    @pytest.mark.asyncio
    async def test_async_setup_entry_custom_threshold_values(self, mock_hass_with_coordinator, mock_add_entities):
        """Test setup with various threshold values."""
        test_cases = [
            ({"expiry_threshold": 1}, 1),
            ({"expiry_threshold": 30}, 30),
            ({"expiry_threshold": 0}, 0),
            ({}, 7),  # No threshold option, should use default
        ]

        for options, expected_threshold in test_cases:
            config_entry = MagicMock()
            config_entry.entry_id = "test_entry"
            config_entry.data = {"name": "Test"}
            config_entry.options = options

            # Make this the first entry
            mock_hass_with_coordinator.config_entries.async_entries.return_value = [
                config_entry]

            with patch('custom_components.simple_inventory.sensor.InventorySensor'), \
                    patch('custom_components.simple_inventory.sensor.ExpiryNotificationSensor') as mock_expiry_sensor:

                await async_setup_entry(mock_hass_with_coordinator, config_entry, mock_add_entities)

                # Check that expiry sensor was created with correct threshold
                mock_expiry_sensor.assert_called_once()
                call_args = mock_expiry_sensor.call_args[0]
                # Third argument is threshold
                assert call_args[2] == expected_threshold

    @pytest.mark.asyncio
    async def test_async_setup_entry_coordinator_access(self, mock_hass_with_coordinator, mock_config_entry_with_options, mock_add_entities):
        """Test that coordinator is properly accessed from hass.data."""
        expected_coordinator = mock_hass_with_coordinator.data["simple_inventory"]["coordinator"]

        # Make this the first entry
        mock_hass_with_coordinator.config_entries.async_entries.return_value = [
            mock_config_entry_with_options]

        with patch('custom_components.simple_inventory.sensor.InventorySensor') as mock_inventory_sensor, \
                patch('custom_components.simple_inventory.sensor.ExpiryNotificationSensor') as mock_expiry_sensor:

            await async_setup_entry(mock_hass_with_coordinator, mock_config_entry_with_options, mock_add_entities)

            # Verify both sensors received the same coordinator instance
            inventory_coordinator = mock_inventory_sensor.call_args[0][1]
            expiry_coordinator = mock_expiry_sensor.call_args[0][1]

            assert inventory_coordinator is expected_coordinator
            assert expiry_coordinator is expected_coordinator

    @pytest.mark.asyncio
    async def test_async_setup_entry_sensor_creation_order(self, mock_hass_with_coordinator, mock_config_entry_with_options, mock_add_entities):
        """Test that sensors are created in the correct order."""
        # Make this the first entry
        mock_hass_with_coordinator.config_entries.async_entries.return_value = [
            mock_config_entry_with_options]

        with patch('custom_components.simple_inventory.sensor.InventorySensor') as mock_inventory_sensor, \
                patch('custom_components.simple_inventory.sensor.ExpiryNotificationSensor') as mock_expiry_sensor:

            await async_setup_entry(mock_hass_with_coordinator, mock_config_entry_with_options, mock_add_entities)

            # Verify async_add_entities was called in correct order
            expected_calls = [
                # First call with inventory sensor
                call([mock_inventory_sensor.return_value]),
                # Second call with expiry sensor
                call([mock_expiry_sensor.return_value])
            ]

            mock_add_entities.assert_has_calls(expected_calls)

    @pytest.mark.asyncio
    async def test_async_setup_entry_data_extraction(self, mock_hass_with_coordinator, mock_add_entities):
        """Test extraction of various data from config entry."""
        test_cases = [
            # (config_data, expected_name, expected_icon)
            ({"name": "Custom Name", "icon": "mdi:custom"},
             "Custom Name", "mdi:custom"),
            ({"name": "Only Name"}, "Only Name",
             "mdi:package-variant"),  # Default icon
            ({"icon": "mdi:only-icon"}, "Inventory",
             "mdi:only-icon"),    # Default name
            # All defaults
            ({}, "Inventory", "mdi:package-variant"),
            # Empty strings
            ({"name": "", "icon": ""}, "", ""),
        ]

        for config_data, expected_name, expected_icon in test_cases:
            config_entry = MagicMock()
            config_entry.entry_id = "test_entry"
            config_entry.data = config_data
            config_entry.options = {}

            # Make this NOT the first entry to simplify testing
            other_entry = MagicMock()
            other_entry.entry_id = "other_entry"
            mock_hass_with_coordinator.config_entries.async_entries.return_value = [
                other_entry, config_entry]

            with patch('custom_components.simple_inventory.sensor.InventorySensor') as mock_inventory_sensor:

                await async_setup_entry(mock_hass_with_coordinator, config_entry, mock_add_entities)

                # Verify InventorySensor was called with correct extracted data
                call_args = mock_inventory_sensor.call_args[0]
                assert call_args[2] == expected_name   # name parameter
                assert call_args[3] == expected_icon   # icon parameter

    @pytest.mark.asyncio
    async def test_async_setup_entry_entry_id_usage(self, mock_hass_with_coordinator, mock_add_entities):
        """Test that entry_id is properly passed to sensors."""
        config_entry = MagicMock()
        config_entry.entry_id = "unique_entry_id_123"
        config_entry.data = {"name": "Test"}
        config_entry.options = {}

        # Make this the first entry
        mock_hass_with_coordinator.config_entries.async_entries.return_value = [
            config_entry]

        with patch('custom_components.simple_inventory.sensor.InventorySensor') as mock_inventory_sensor:

            await async_setup_entry(mock_hass_with_coordinator, config_entry, mock_add_entities)

            # Verify entry_id was passed to InventorySensor
            call_args = mock_inventory_sensor.call_args[0]
            assert call_args[4] == "unique_entry_id_123"  # entry_id parameter
