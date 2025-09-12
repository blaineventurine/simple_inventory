"""Tests for sensor platform setup."""

from unittest.mock import MagicMock, patch

import pytest
from homeassistant import config_entries
from typing_extensions import Self

from custom_components.simple_inventory.sensor import async_setup_entry


class TestSensorPlatform:
    """Test sensor platform setup."""

    @pytest.fixture
    def mock_config_entry_with_options(
        self: Self,
    ) -> config_entries.ConfigEntry:
        """Create a mock config entry with options."""
        config_entry = MagicMock()
        config_entry.entry_id = "test_entry_123"
        config_entry.data = {"name": "Kitchen Inventory", "icon": "mdi:fridge"}
        config_entry.options = {"expiry_threshold": 14}
        return config_entry

    @pytest.fixture
    def mock_config_entry_minimal(self: Self) -> config_entries.ConfigEntry:
        """Create a mock config entry with minimal data."""
        config_entry = MagicMock()
        config_entry.entry_id = "minimal_entry_456"
        config_entry.data = {}
        config_entry.options = {}
        return config_entry

    @pytest.fixture
    def mock_hass_with_coordinator(
        self: Self,
        mock_coordinator: MagicMock,
        domain: str = "simple_inventory",
    ) -> MagicMock:
        """Create a mock hass with coordinator in data."""
        hass = MagicMock()
        hass.data = {domain: {"coordinator": mock_coordinator}}
        hass.config_entries.async_entries.return_value = []
        return hass

    @pytest.fixture
    def mock_add_entities(self: Self) -> MagicMock:
        """Create a mock async_add_entities callback."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_async_setup_entry_basic(
        self: Self,
        mock_hass_with_coordinator: MagicMock,
        mock_config_entry_with_options: config_entries.ConfigEntry,
        mock_add_entities: MagicMock,
    ) -> None:
        """Test basic sensor setup."""
        mock_hass_with_coordinator.config_entries.async_entries.return_value = [
            mock_config_entry_with_options
        ]

        with (
            patch(
                "custom_components.simple_inventory.sensor.InventorySensor"
            ) as mock_inventory_sensor,
            patch(
                "custom_components.simple_inventory.sensor.ExpiryNotificationSensor"
            ) as mock_expiry_sensor,
        ):

            await async_setup_entry(
                mock_hass_with_coordinator,
                mock_config_entry_with_options,
                mock_add_entities,
            )

            mock_inventory_sensor.assert_called_once_with(
                mock_hass_with_coordinator,
                mock_hass_with_coordinator.data["simple_inventory"]["coordinator"],
                "Kitchen Inventory",
                "mdi:fridge",
                "test_entry_123",
            )

            mock_expiry_sensor.assert_called_once_with(
                mock_hass_with_coordinator,
                mock_hass_with_coordinator.data["simple_inventory"]["coordinator"],
                "test_entry_123",
                "Kitchen Inventory",
            )

            mock_add_entities.assert_called_once_with(
                [
                    mock_inventory_sensor.return_value,
                    mock_expiry_sensor.return_value,
                ]
            )

    @pytest.mark.asyncio
    async def test_async_setup_entry_minimal_data(
        self: Self,
        mock_hass_with_coordinator: MagicMock,
        mock_config_entry_minimal: config_entries.ConfigEntry,
        mock_add_entities: MagicMock,
    ) -> None:
        """Test setup with minimal config entry data."""
        mock_hass_with_coordinator.config_entries.async_entries.return_value = [
            mock_config_entry_minimal
        ]

        with (
            patch(
                "custom_components.simple_inventory.sensor.InventorySensor"
            ) as mock_inventory_sensor,
            patch(
                "custom_components.simple_inventory.sensor.ExpiryNotificationSensor"
            ) as mock_expiry_sensor,
        ):

            await async_setup_entry(
                mock_hass_with_coordinator,
                mock_config_entry_minimal,
                mock_add_entities,
            )

            # Verify InventorySensor was created with default values
            mock_inventory_sensor.assert_called_once_with(
                mock_hass_with_coordinator,
                mock_hass_with_coordinator.data["simple_inventory"]["coordinator"],
                "Inventory",  # Default name
                "mdi:package-variant",  # Default icon
                "minimal_entry_456",
            )

            # Verify per-inventory ExpiryNotificationSensor was created
            mock_expiry_sensor.assert_called_once_with(
                mock_hass_with_coordinator,
                mock_hass_with_coordinator.data["simple_inventory"]["coordinator"],
                "minimal_entry_456",  # entry_id
                "Inventory",  # inventory_name (default)
            )

    @pytest.mark.asyncio
    async def test_async_setup_entry_not_first_entry(
        self: Self,
        mock_hass_with_coordinator: MagicMock,
        mock_config_entry_with_options: config_entries.ConfigEntry,
        mock_add_entities: MagicMock,
    ) -> None:
        """Test setup when this is not the first config entry."""
        # Create a different "first" entry
        first_entry = MagicMock()
        first_entry.entry_id = "first_entry"

        mock_hass_with_coordinator.config_entries.async_entries.return_value = [
            first_entry,
            mock_config_entry_with_options,
        ]

        with (
            patch(
                "custom_components.simple_inventory.sensor.InventorySensor"
            ) as mock_inventory_sensor,
            patch(
                "custom_components.simple_inventory.sensor.ExpiryNotificationSensor"
            ) as mock_expiry_sensor,
            patch(
                "custom_components.simple_inventory.sensor.GlobalExpiryNotificationSensor"
            ) as mock_global_expiry_sensor,
        ):

            await async_setup_entry(
                mock_hass_with_coordinator,
                mock_config_entry_with_options,
                mock_add_entities,
            )

            mock_inventory_sensor.assert_called_once()
            mock_expiry_sensor.assert_called_once_with(
                mock_hass_with_coordinator,
                mock_hass_with_coordinator.data["simple_inventory"]["coordinator"],
                "test_entry_123",  # entry_id
                "Kitchen Inventory",  # inventory_name
            )

            # Verify GlobalExpiryNotificationSensor was NOT created (not first entry)
            mock_global_expiry_sensor.assert_not_called()

            # Verify async_add_entities was called once with two sensors
            mock_add_entities.assert_called_once_with(
                [
                    mock_inventory_sensor.return_value,
                    mock_expiry_sensor.return_value,
                ]
            )

    @pytest.mark.asyncio
    async def test_async_setup_entry_multiple_config_entries(
        self: Self,
        mock_hass_with_coordinator: MagicMock,
        mock_add_entities: MagicMock,
    ) -> None:
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

        with (
            patch(
                "custom_components.simple_inventory.sensor.InventorySensor"
            ) as mock_inventory_sensor,
            patch(
                "custom_components.simple_inventory.sensor.ExpiryNotificationSensor"
            ) as mock_expiry_sensor,
        ):

            # Test setup for first entry
            await async_setup_entry(mock_hass_with_coordinator, entry1, mock_add_entities)

            mock_expiry_sensor.assert_called_once()

            # Reset mocks
            mock_inventory_sensor.reset_mock()
            mock_expiry_sensor.reset_mock()
            mock_add_entities.reset_mock()

            # Test setup for second entry
            await async_setup_entry(mock_hass_with_coordinator, entry2, mock_add_entities)

            # Should create per-inventory expiry sensor but NOT global
            mock_expiry_sensor.assert_called_once()
            # Should be called once with 2 sensors (inventory + per-inventory expiry)
            mock_add_entities.assert_called_once()
            # Get the list of sensors
            call_args = mock_add_entities.call_args[0][0]
            assert len(call_args) == 2

    @pytest.mark.asyncio
    async def test_async_setup_entry_coordinator_access(
        self: Self,
        mock_hass_with_coordinator: MagicMock,
        mock_config_entry_with_options: config_entries.ConfigEntry,
        mock_add_entities: MagicMock,
    ) -> None:
        """Test that coordinator is properly accessed from hass.data."""
        expected_coordinator = mock_hass_with_coordinator.data["simple_inventory"]["coordinator"]

        # Make this the first entry
        mock_hass_with_coordinator.config_entries.async_entries.return_value = [
            mock_config_entry_with_options
        ]

        with (
            patch(
                "custom_components.simple_inventory.sensor.InventorySensor"
            ) as mock_inventory_sensor,
            patch(
                "custom_components.simple_inventory.sensor.ExpiryNotificationSensor"
            ) as mock_expiry_sensor,
        ):

            await async_setup_entry(
                mock_hass_with_coordinator,
                mock_config_entry_with_options,
                mock_add_entities,
            )

            # Verify all sensors received the same coordinator instance
            inventory_coordinator = mock_inventory_sensor.call_args[0][1]
            expiry_coordinator = mock_expiry_sensor.call_args[0][1]

            assert inventory_coordinator is expected_coordinator
            assert expiry_coordinator is expected_coordinator

    @pytest.mark.asyncio
    async def test_async_setup_entry_sensor_creation_order(
        self: Self,
        mock_hass_with_coordinator: MagicMock,
        mock_config_entry_with_options: config_entries.ConfigEntry,
        mock_add_entities: MagicMock,
    ) -> None:
        """Test that sensors are created in the correct order."""
        # Make this the first entry
        mock_hass_with_coordinator.config_entries.async_entries.return_value = [
            mock_config_entry_with_options
        ]

        with (
            patch(
                "custom_components.simple_inventory.sensor.InventorySensor"
            ) as mock_inventory_sensor,
            patch(
                "custom_components.simple_inventory.sensor.ExpiryNotificationSensor"
            ) as mock_expiry_sensor,
        ):

            await async_setup_entry(
                mock_hass_with_coordinator,
                mock_config_entry_with_options,
                mock_add_entities,
            )

            # Verify async_add_entities was called once with all sensors in correct order
            mock_add_entities.assert_called_once_with(
                [
                    mock_inventory_sensor.return_value,
                    mock_expiry_sensor.return_value,
                ]
            )

    @pytest.mark.asyncio
    async def test_async_setup_entry_data_extraction(
        self: Self,
        mock_hass_with_coordinator: MagicMock,
        mock_add_entities: MagicMock,
    ) -> None:
        """Test extraction of various data from config entry."""
        test_cases = [
            # (config_data, expected_name, expected_icon)
            (
                {"name": "Custom Name", "icon": "mdi:custom"},
                "Custom Name",
                "mdi:custom",
            ),
            (
                {"name": "Only Name"},
                "Only Name",
                "mdi:package-variant",
            ),  # Default icon
            (
                {"icon": "mdi:only-icon"},
                "Inventory",
                "mdi:only-icon",
            ),  # Default name
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
                other_entry,
                config_entry,
            ]

            with (
                patch(
                    "custom_components.simple_inventory.sensor.InventorySensor"
                ) as mock_inventory_sensor,
                patch(
                    "custom_components.simple_inventory.sensor.ExpiryNotificationSensor"
                ) as mock_expiry_sensor,
            ):

                await async_setup_entry(mock_hass_with_coordinator, config_entry, mock_add_entities)

                inventory_call_args = mock_inventory_sensor.call_args[0]

                assert inventory_call_args[2] == expected_name
                assert inventory_call_args[3] == expected_icon

                expiry_call_args = mock_expiry_sensor.call_args[0]

                assert expiry_call_args[3] == expected_name

    @pytest.mark.asyncio
    async def test_async_setup_entry_entry_id_usage(
        self: Self,
        mock_hass_with_coordinator: MagicMock,
        mock_add_entities: MagicMock,
    ) -> None:
        """Test that entry_id is properly passed to sensors."""
        config_entry = MagicMock()
        config_entry.entry_id = "unique_entry_id_123"
        config_entry.data = {"name": "Test"}
        config_entry.options = {}

        # Make this NOT the first entry to simplify testing
        other_entry = MagicMock()
        other_entry.entry_id = "other_entry"
        mock_hass_with_coordinator.config_entries.async_entries.return_value = [
            other_entry,
            config_entry,
        ]

        with (
            patch(
                "custom_components.simple_inventory.sensor.InventorySensor"
            ) as mock_inventory_sensor,
            patch(
                "custom_components.simple_inventory.sensor.ExpiryNotificationSensor"
            ) as mock_expiry_sensor,
        ):

            await async_setup_entry(mock_hass_with_coordinator, config_entry, mock_add_entities)

            inventory_call_args = mock_inventory_sensor.call_args[0]

            assert inventory_call_args[4] == "unique_entry_id_123"

            expiry_call_args = mock_expiry_sensor.call_args[0]

            assert expiry_call_args[2] == "unique_entry_id_123"
