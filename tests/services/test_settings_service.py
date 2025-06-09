"""Tests for SettingsService."""
import pytest
import logging
from unittest.mock import MagicMock


class TestSettingsService:
    """Test SettingsService class."""

    def test_inheritance(self, settings_service):
        """Test that SettingsService properly inherits from BaseServiceHandler."""
        from custom_components.simple_inventory.services.base_service import BaseServiceHandler

        assert isinstance(settings_service, BaseServiceHandler)
        assert hasattr(settings_service, '_save_and_log_success')
        assert hasattr(settings_service, '_get_inventory_and_name')
        assert hasattr(settings_service, '_log_item_not_found')

    # Tests for async_update_item_settings
    @pytest.mark.asyncio
    async def test_async_update_item_settings_success(self, settings_service, update_settings_service_call, mock_coordinator):
        """Test successful item settings update."""
        await settings_service.async_update_item_settings(update_settings_service_call)

        # Verify coordinator update_item_settings was called with correct parameters
        mock_coordinator.update_item_settings.assert_called_once_with(
            "kitchen", "milk",
            auto_add_enabled=True,
            threshold=5,
            todo_list="todo.shopping"
        )

        # Verify save and log was called
        mock_coordinator.async_save_data.assert_called_once_with("kitchen")

    @pytest.mark.asyncio
    async def test_async_update_item_settings_minimal_data(self, settings_service, basic_service_call, mock_coordinator):
        """Test updating settings with minimal data."""
        await settings_service.async_update_item_settings(basic_service_call)

        # Should call update_item_settings with no additional kwargs
        mock_coordinator.update_item_settings.assert_called_once_with(
            "kitchen", "milk")
        mock_coordinator.async_save_data.assert_called_once_with("kitchen")

    @pytest.mark.asyncio
    async def test_async_update_item_settings_not_found(self, settings_service, update_settings_service_call, mock_coordinator, caplog):
        """Test updating settings for item that doesn't exist."""
        mock_coordinator.update_item_settings.return_value = False

        with caplog.at_level(logging.WARNING):
            await settings_service.async_update_item_settings(update_settings_service_call)

        mock_coordinator.update_item_settings.assert_called_once()
        mock_coordinator.async_save_data.assert_not_called()

        # Verify warning was logged
        assert "Update item settings failed - Item not found: milk in inventory: kitchen" in caplog.text

    @pytest.mark.asyncio
    async def test_async_update_item_settings_coordinator_exception(self, settings_service, update_settings_service_call, mock_coordinator, caplog):
        """Test handling coordinator exception during settings update."""
        mock_coordinator.update_item_settings.side_effect = Exception(
            "Settings update failed")

        with caplog.at_level(logging.ERROR):
            await settings_service.async_update_item_settings(update_settings_service_call)

        assert "Failed to update settings for item milk in inventory kitchen: Settings update failed" in caplog.text
        mock_coordinator.async_save_data.assert_not_called()

    # Tests for async_set_expiry_threshold
    @pytest.mark.asyncio
    async def test_async_set_expiry_threshold_success(self, settings_service, threshold_service_call, hass_with_expiry_sensor, caplog):
        """Test successful expiry threshold update."""
        # Replace the hass instance to use our enhanced fixture
        settings_service.hass = hass_with_expiry_sensor

        with caplog.at_level(logging.INFO):
            await settings_service.async_set_expiry_threshold(threshold_service_call)

        # Verify config entry was updated
        hass_with_expiry_sensor.config_entries.async_update_entry.assert_called_once()

        # Check the call arguments
        call_args = hass_with_expiry_sensor.config_entries.async_update_entry.call_args
        entry, options = call_args[0][0], call_args[1]["options"]
        assert options["expiry_threshold"] == 7

        # Verify sensor update was attempted
        hass_with_expiry_sensor.helpers.entity_registry.async_get.assert_called_once()

        # Verify event was fired
        hass_with_expiry_sensor.bus.async_fire.assert_called_once_with(
            "simple_inventory_threshold_updated",
            {"new_threshold": 7}
        )

        # Verify info log
        assert "Expiry threshold updated from 7 to 7 days" in caplog.text

    @pytest.mark.asyncio
    async def test_async_set_expiry_threshold_no_config_entries(self, settings_service, threshold_service_call, hass, caplog):
        """Test setting threshold when no config entries exist."""
        hass.config_entries.async_entries.return_value = []
        settings_service.hass = hass

        with caplog.at_level(logging.ERROR):
            await settings_service.async_set_expiry_threshold(threshold_service_call)

        # Should log error and return early
        assert "No Simple Inventory config entries found" in caplog.text
        hass.config_entries.async_update_entry.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_set_expiry_threshold_config_update_exception(self, settings_service, threshold_service_call, hass_with_expiry_sensor, caplog):
        """Test handling exception during config entry update."""
        hass_with_expiry_sensor.config_entries.async_update_entry.side_effect = Exception(
            "Config update failed")
        settings_service.hass = hass_with_expiry_sensor

        with caplog.at_level(logging.ERROR):
            with pytest.raises(Exception, match="Config update failed"):
                await settings_service.async_set_expiry_threshold(threshold_service_call)

        assert "Failed to set expiry threshold to 7 days: Config update failed" in caplog.text

    @pytest.mark.asyncio
    async def test_async_set_expiry_threshold_different_values(self, settings_service, hass_with_expiry_sensor, caplog):
        """Test threshold update with different old and new values."""
        # Set up config entry with different initial threshold
        config_entry = hass_with_expiry_sensor.config_entries.async_entries()[
            0]
        config_entry.options = {"expiry_threshold": 14}

        call = MagicMock()
        call.data = {"threshold_days": 21}

        settings_service.hass = hass_with_expiry_sensor

        with caplog.at_level(logging.INFO):
            await settings_service.async_set_expiry_threshold(call)

        # Verify log shows actual change
        assert "Expiry threshold updated from 14 to 21 days" in caplog.text

    # Tests for _update_expiry_sensor_threshold
    @pytest.mark.asyncio
    async def test_update_expiry_sensor_threshold_success(self, settings_service, hass_with_expiry_sensor, caplog):
        """Test successful expiry sensor threshold update."""
        settings_service.hass = hass_with_expiry_sensor

        with caplog.at_level(logging.DEBUG):
            await settings_service._update_expiry_sensor_threshold(10)

        # Verify entity lookup was performed
        hass_with_expiry_sensor.states.async_entity_ids.assert_called_once_with(
            "sensor")
        hass_with_expiry_sensor.states.get.assert_called_once()

        # Verify entity registry was accessed
        hass_with_expiry_sensor.helpers.entity_registry.async_get.assert_called_once()

        # Verify event was fired
        hass_with_expiry_sensor.bus.async_fire.assert_called_once_with(
            "simple_inventory_threshold_updated",
            {"new_threshold": 10}
        )

        # Verify debug log
        assert "Updated expiry sensor threshold to 10 days" in caplog.text

    @pytest.mark.asyncio
    async def test_update_expiry_sensor_threshold_sensor_not_found(self, settings_service, hass, caplog):
        """Test sensor update when expiry sensor is not found."""
        # Mock no matching sensor entities
        hass.states.async_entity_ids.return_value = ["sensor.other_sensor"]
        hass.states.get.return_value = None
        settings_service.hass = hass

        with caplog.at_level(logging.WARNING):
            await settings_service._update_expiry_sensor_threshold(10)

        # Should log warning and return early
        assert "Could not find expiry sensor to update" in caplog.text
        hass.helpers.entity_registry.async_get.assert_not_called()
        hass.bus.async_fire.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_expiry_sensor_threshold_wrong_platform(self, settings_service, hass_with_expiry_sensor):
        """Test sensor update when entity has wrong platform."""
        # Set up entity with wrong platform
        entity_registry = hass_with_expiry_sensor.helpers.entity_registry.async_get.return_value
        entity_registry.entities["expiry_sensor_key"].platform = "other_platform"

        settings_service.hass = hass_with_expiry_sensor

        await settings_service._update_expiry_sensor_threshold(10)

        # Should not fire event for wrong platform
        hass_with_expiry_sensor.bus.async_fire.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_expiry_sensor_threshold_entity_registry_exception(self, settings_service, hass_with_expiry_sensor):
        """Test handling entity registry exception."""
        hass_with_expiry_sensor.helpers.entity_registry.async_get.side_effect = Exception(
            "Registry error")
        settings_service.hass = hass_with_expiry_sensor

        # Exception should be raised since there's no exception handling in the method
        with pytest.raises(Exception, match="Registry error"):
            await settings_service._update_expiry_sensor_threshold(10)

        # Event should not be fired due to exception
        hass_with_expiry_sensor.bus.async_fire.assert_not_called()

    # Tests for get_current_expiry_threshold
    def test_get_current_expiry_threshold_with_config(self, settings_service, hass_with_expiry_sensor):
        """Test getting current threshold from config entries."""
        settings_service.hass = hass_with_expiry_sensor

        threshold = settings_service.get_current_expiry_threshold()
        assert threshold == 7

    def test_get_current_expiry_threshold_custom_value(self, settings_service, hass_with_expiry_sensor):
        """Test getting custom threshold value."""
        # Set up config entry with custom threshold
        config_entry = hass_with_expiry_sensor.config_entries.async_entries()[
            0]
        config_entry.options = {"expiry_threshold": 14}

        settings_service.hass = hass_with_expiry_sensor

        threshold = settings_service.get_current_expiry_threshold()
        assert threshold == 14

    def test_get_current_expiry_threshold_no_config_entries(self, settings_service, hass):
        """Test getting threshold when no config entries exist."""
        hass.config_entries.async_entries.return_value = []
        settings_service.hass = hass

        threshold = settings_service.get_current_expiry_threshold()
        assert threshold == 7  # Default value

    def test_get_current_expiry_threshold_no_threshold_in_options(self, settings_service, hass_with_expiry_sensor):
        """Test getting threshold when not set in options."""
        # Set up config entry with no expiry_threshold option
        config_entry = hass_with_expiry_sensor.config_entries.async_entries()[
            0]
        config_entry.options = {}

        settings_service.hass = hass_with_expiry_sensor

        threshold = settings_service.get_current_expiry_threshold()
        assert threshold == 7  # Default value

    # Integration and edge case tests
    @pytest.mark.asyncio
    async def test_concurrent_settings_operations(self, settings_service, mock_coordinator):
        """Test concurrent settings operations."""
        import asyncio

        calls = []
        for i in range(3):
            call = MagicMock()
            call.data = {
                "inventory_id": f"inventory_{i}",
                "name": f"item_{i}",
                "auto_add_enabled": True,
                "threshold": i + 1
            }
            calls.append(call)

        # Execute concurrent settings update operations
        tasks = [settings_service.async_update_item_settings(
            call) for call in calls]
        await asyncio.gather(*tasks)

        # Verify all operations completed
        assert mock_coordinator.update_item_settings.call_count == 3
        assert mock_coordinator.async_save_data.call_count == 3

    @pytest.mark.asyncio
    async def test_complete_threshold_workflow(self, settings_service, hass_with_expiry_sensor, caplog):
        """Test complete threshold update workflow."""
        settings_service.hass = hass_with_expiry_sensor

        call = MagicMock()
        call.data = {"threshold_days": 21}

        with caplog.at_level(logging.INFO):
            await settings_service.async_set_expiry_threshold(call)

        # Verify complete workflow
        hass_with_expiry_sensor.config_entries.async_update_entry.assert_called_once()
        hass_with_expiry_sensor.helpers.entity_registry.async_get.assert_called_once()
        hass_with_expiry_sensor.bus.async_fire.assert_called_once()

        # Verify logging
        assert "Expiry threshold updated from 7 to 21 days" in caplog.text

    @pytest.mark.parametrize("threshold_days", [1, 7, 14, 30])
    @pytest.mark.asyncio
    async def test_various_threshold_values(self, settings_service, hass_with_expiry_sensor, threshold_days):
        """Test threshold updates with various values."""
        settings_service.hass = hass_with_expiry_sensor

        call = MagicMock()
        call.data = {"threshold_days": threshold_days}

        await settings_service.async_set_expiry_threshold(call)

        # Verify event was fired with correct value
        hass_with_expiry_sensor.bus.async_fire.assert_called_once_with(
            "simple_inventory_threshold_updated",
            {"new_threshold": threshold_days}
        )

    @pytest.mark.asyncio
    async def test_settings_extraction(self, settings_service, mock_coordinator):
        """Test proper extraction of settings from service call."""
        call = MagicMock()
        call.data = {
            "inventory_id": "kitchen",
            "name": "milk",
            "auto_add_enabled": True,
            "threshold": 5,
            "todo_list": "todo.shopping",
            "extra_setting": "should_be_included"
        }

        await settings_service.async_update_item_settings(call)

        # Verify extra_setting was included in kwargs
        mock_coordinator.update_item_settings.assert_called_once_with(
            "kitchen", "milk",
            auto_add_enabled=True,
            threshold=5,
            todo_list="todo.shopping",
            extra_setting="should_be_included"
        )
