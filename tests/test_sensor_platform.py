"""Tests for sensor platform setup."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from homeassistant import config_entries

from custom_components.simple_inventory.const import DOMAIN
from custom_components.simple_inventory.sensor import async_setup_entry


class TestSensorPlatform:
    """Test sensor platform setup."""

    @pytest.fixture
    def mock_add_entities(self) -> MagicMock:
        """Create a mock async_add_entities callback."""
        return MagicMock()

    def _make_entry(self, entry_id: str, data: dict) -> config_entries.ConfigEntry:
        """Create a mock ConfigEntry-like object."""
        entry = MagicMock()
        entry.entry_id = entry_id
        entry.data = data
        entry.options = {}
        return entry

    @pytest.fixture
    def mock_hass(self) -> MagicMock:
        """Provide a minimal hass mock with real dict hass.data."""
        hass = MagicMock()
        hass.data = {DOMAIN: {"coordinators": {}}}
        return hass

    @pytest.mark.asyncio
    async def test_async_setup_entry_inventory_basic(
        self,
        mock_hass: MagicMock,
        mock_add_entities: MagicMock,
    ) -> None:
        """Inventory entry creates InventorySensor + ItemsExpiringSoonSensor + ExpiredItemsSensor."""
        entry = self._make_entry(
            "test_entry_123",
            {"name": "Kitchen Inventory", "icon": "mdi:fridge", "entry_type": "inventory"},
        )

        coordinator = MagicMock()
        mock_hass.data[DOMAIN]["coordinators"][entry.entry_id] = coordinator

        with (
            patch(
                "custom_components.simple_inventory.sensor.InventorySensor"
            ) as mock_inventory_sensor,
            patch(
                "custom_components.simple_inventory.sensor.ItemsExpiringSoonSensor"
            ) as mock_expiry_sensor,
            patch(
                "custom_components.simple_inventory.sensor.ExpiredItemsSensor"
            ) as mock_expired_sensor,
        ):
            await async_setup_entry(mock_hass, entry, mock_add_entities)

            mock_inventory_sensor.assert_called_once_with(
                mock_hass,
                coordinator,
                "Kitchen Inventory",
                "mdi:fridge",
                "test_entry_123",
            )
            mock_expiry_sensor.assert_called_once_with(
                mock_hass,
                coordinator,
                "test_entry_123",
                "Kitchen Inventory",
            )
            mock_expired_sensor.assert_called_once_with(
                mock_hass,
                coordinator,
                "test_entry_123",
                "Kitchen Inventory",
            )
            mock_add_entities.assert_called_once_with(
                [
                    mock_inventory_sensor.return_value,
                    mock_expiry_sensor.return_value,
                    mock_expired_sensor.return_value,
                ]
            )

    @pytest.mark.asyncio
    async def test_async_setup_entry_inventory_minimal_defaults(
        self,
        mock_hass: MagicMock,
        mock_add_entities: MagicMock,
    ) -> None:
        """Inventory entry with minimal data uses defaults."""
        entry = self._make_entry(
            "minimal_entry_456",
            {"entry_type": "inventory"},
        )

        coordinator = MagicMock()
        mock_hass.data[DOMAIN]["coordinators"][entry.entry_id] = coordinator

        with (
            patch(
                "custom_components.simple_inventory.sensor.InventorySensor"
            ) as mock_inventory_sensor,
            patch(
                "custom_components.simple_inventory.sensor.ItemsExpiringSoonSensor"
            ) as mock_expiry_sensor,
            patch(
                "custom_components.simple_inventory.sensor.ExpiredItemsSensor"
            ) as mock_expired_sensor,
        ):
            await async_setup_entry(mock_hass, entry, mock_add_entities)

            mock_inventory_sensor.assert_called_once_with(
                mock_hass,
                coordinator,
                "Inventory",
                "mdi:package-variant",
                "minimal_entry_456",
            )
            mock_expiry_sensor.assert_called_once_with(
                mock_hass,
                coordinator,
                "minimal_entry_456",
                "Inventory",
            )
            mock_expired_sensor.assert_called_once_with(
                mock_hass,
                coordinator,
                "minimal_entry_456",
                "Inventory",
            )

    @pytest.mark.asyncio
    async def test_async_setup_entry_global_creates_only_global_sensor(
        self,
        mock_hass: MagicMock,
        mock_add_entities: MagicMock,
    ) -> None:
        """Global entry creates GlobalItemsExpiringSoonSensor + GlobalExpiredItemsSensor."""
        entry = self._make_entry(
            "global_entry_999",
            {"name": "All Items Expiring Soon", "entry_type": "global"},
        )

        coordinator = MagicMock()
        mock_hass.data[DOMAIN]["coordinators"][entry.entry_id] = coordinator

        with (
            patch(
                "custom_components.simple_inventory.sensor.InventorySensor"
            ) as mock_inventory_sensor,
            patch(
                "custom_components.simple_inventory.sensor.ItemsExpiringSoonSensor"
            ) as mock_expiry_sensor,
            patch(
                "custom_components.simple_inventory.sensor.GlobalItemsExpiringSoonSensor"
            ) as mock_global_sensor,
            patch(
                "custom_components.simple_inventory.sensor.GlobalExpiredItemsSensor"
            ) as mock_global_expired_sensor,
        ):
            await async_setup_entry(mock_hass, entry, mock_add_entities)

            mock_inventory_sensor.assert_not_called()
            mock_expiry_sensor.assert_not_called()

            mock_global_sensor.assert_called_once_with(mock_hass, coordinator)
            mock_global_expired_sensor.assert_called_once_with(mock_hass, coordinator)
            mock_add_entities.assert_called_once_with(
                [mock_global_sensor.return_value, mock_global_expired_sensor.return_value]
            )

    @pytest.mark.asyncio
    async def test_async_setup_entry_missing_coordinator_skips_setup(
        self,
        mock_hass: MagicMock,
        mock_add_entities: MagicMock,
    ) -> None:
        """If no coordinator exists for entry_id, setup should skip sensor creation."""
        entry = self._make_entry(
            "missing_entry",
            {"name": "Kitchen Inventory", "entry_type": "inventory"},
        )

        with (
            patch(
                "custom_components.simple_inventory.sensor.InventorySensor"
            ) as mock_inventory_sensor,
            patch(
                "custom_components.simple_inventory.sensor.ItemsExpiringSoonSensor"
            ) as mock_expiry_sensor,
            patch(
                "custom_components.simple_inventory.sensor.GlobalItemsExpiringSoonSensor"
            ) as mock_global_sensor,
        ):
            await async_setup_entry(mock_hass, entry, mock_add_entities)

            mock_inventory_sensor.assert_not_called()
            mock_expiry_sensor.assert_not_called()
            mock_global_sensor.assert_not_called()
            mock_add_entities.assert_not_called()
