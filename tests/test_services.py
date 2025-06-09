"""Tests for ServiceHandler."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import voluptuous as vol

from custom_components.simple_inventory.services import (
    ServiceHandler,
    ITEM_SCHEMA,
    UPDATE_SCHEMA,
    UPDATE_SETTINGS_SCHEMA,
    REMOVE_SCHEMA,
    UPDATE_ITEM_SCHEMA,
    SET_EXPIRY_THRESHOLD_SCHEMA
)


class TestServiceHandler:
    """Test ServiceHandler class."""

    @pytest.fixture
    def coordinator(self):
        """Create a mock coordinator."""
        coordinator = MagicMock()
        coordinator.add_item = MagicMock()
        coordinator.remove_item = MagicMock(return_value=True)
        coordinator.increment_item = MagicMock(return_value=True)
        coordinator.decrement_item = MagicMock(return_value=True)
        coordinator.update_item_settings = MagicMock(return_value=True)
        coordinator.update_item = MagicMock(return_value=True)
        coordinator.get_item = MagicMock(
            return_value={"quantity": 5, "threshold": 10})
        coordinator.async_save_data = AsyncMock()
        return coordinator

    @pytest.fixture
    def todo_manager(self):
        """Create a mock todo manager."""
        todo_manager = MagicMock()
        todo_manager.check_and_add_item = AsyncMock(return_value=True)
        return todo_manager

    @pytest.fixture
    def service_handler(self, hass, coordinator, todo_manager):
        """Create a ServiceHandler instance."""
        return ServiceHandler(hass, coordinator, todo_manager)

    @pytest.fixture
    def mock_service_call(self):
        """Create a mock service call."""
        call = MagicMock()
        call.data = {}
        return call

    def test_init(self, hass, coordinator, todo_manager):
        """Test ServiceHandler initialization."""
        handler = ServiceHandler(hass, coordinator, todo_manager)
        assert handler.hass is hass
        assert handler.coordinator is coordinator
        assert handler.todo_manager is todo_manager

    @pytest.mark.asyncio
    async def test_async_set_expiry_threshold(self, service_handler, mock_service_call):
        """Test setting expiry threshold."""
        mock_service_call.data = {"threshold_days": 7}

        with patch.object(service_handler.hass.states, 'async_entity_ids', return_value=["sensor.items_expiring_soon"]):
            await service_handler.async_set_expiry_threshold(mock_service_call)

        # Should not raise an exception (method currently just logs)

    @pytest.mark.asyncio
    async def test_async_add_item(self, service_handler, mock_service_call):
        """Test adding an item."""
        mock_service_call.data = {
            "inventory_id": "kitchen",
            "name": "milk",
            "quantity": 2,
            "unit": "liters",
            "category": "dairy"
        }

        await service_handler.async_add_item(mock_service_call)

        service_handler.coordinator.add_item.assert_called_once_with(
            "kitchen", "milk", quantity=2, unit="liters", category="dairy"
        )
        service_handler.coordinator.async_save_data.assert_called_once_with(
            "kitchen")

    @pytest.mark.asyncio
    async def test_async_add_item_minimal_data(self, service_handler, mock_service_call):
        """Test adding an item with minimal data."""
        mock_service_call.data = {
            "inventory_id": "kitchen",
            "name": "milk"
        }

        await service_handler.async_add_item(mock_service_call)

        service_handler.coordinator.add_item.assert_called_once_with(
            "kitchen", "milk")
        service_handler.coordinator.async_save_data.assert_called_once_with(
            "kitchen")

    @pytest.mark.asyncio
    async def test_async_remove_item_success(self, service_handler, mock_service_call):
        """Test successfully removing an item."""
        mock_service_call.data = {
            "inventory_id": "kitchen",
            "name": "milk"
        }

        await service_handler.async_remove_item(mock_service_call)

        service_handler.coordinator.remove_item.assert_called_once_with(
            "kitchen", "milk")
        service_handler.coordinator.async_save_data.assert_called_once_with(
            "kitchen")

    @pytest.mark.asyncio
    async def test_async_remove_item_not_found(self, service_handler, mock_service_call):
        """Test removing an item that doesn't exist."""
        mock_service_call.data = {
            "inventory_id": "kitchen",
            "name": "milk"
        }
        service_handler.coordinator.remove_item.return_value = False

        await service_handler.async_remove_item(mock_service_call)

        service_handler.coordinator.remove_item.assert_called_once_with(
            "kitchen", "milk")
        service_handler.coordinator.async_save_data.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_increment_item_success(self, service_handler, mock_service_call):
        """Test successfully incrementing an item."""
        mock_service_call.data = {
            "inventory_id": "kitchen",
            "name": "milk",
            "amount": 3
        }

        await service_handler.async_increment_item(mock_service_call)

        service_handler.coordinator.increment_item.assert_called_once_with(
            "kitchen", "milk", 3)
        service_handler.coordinator.async_save_data.assert_called_once_with(
            "kitchen")

    @pytest.mark.asyncio
    async def test_async_increment_item_default_amount(self, service_handler, mock_service_call):
        """Test incrementing an item with default amount."""
        mock_service_call.data = {
            "inventory_id": "kitchen",
            "name": "milk"
        }

        await service_handler.async_increment_item(mock_service_call)

        service_handler.coordinator.increment_item.assert_called_once_with(
            "kitchen", "milk", 1)

    @pytest.mark.asyncio
    async def test_async_increment_item_not_found(self, service_handler, mock_service_call):
        """Test incrementing an item that doesn't exist."""
        mock_service_call.data = {
            "inventory_id": "kitchen",
            "name": "milk"
        }
        service_handler.coordinator.increment_item.return_value = False

        await service_handler.async_increment_item(mock_service_call)

        service_handler.coordinator.async_save_data.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_decrement_item_success(self, service_handler, mock_service_call):
        """Test successfully decrementing an item."""
        mock_service_call.data = {
            "inventory_id": "kitchen",
            "name": "milk",
            "amount": 2
        }

        await service_handler.async_decrement_item(mock_service_call)

        service_handler.coordinator.decrement_item.assert_called_once_with(
            "kitchen", "milk", 2)
        service_handler.coordinator.get_item.assert_called_once_with(
            "kitchen", "milk")
        service_handler.todo_manager.check_and_add_item.assert_called_once()
        service_handler.coordinator.async_save_data.assert_called_once_with(
            "kitchen")

    @pytest.mark.asyncio
    async def test_async_decrement_item_no_todo_check_when_not_found(self, service_handler, mock_service_call):
        """Test decrementing an item that doesn't exist."""
        mock_service_call.data = {
            "inventory_id": "kitchen",
            "name": "milk"
        }
        service_handler.coordinator.decrement_item.return_value = False

        await service_handler.async_decrement_item(mock_service_call)

        service_handler.coordinator.get_item.assert_not_called()
        service_handler.todo_manager.check_and_add_item.assert_not_called()
        service_handler.coordinator.async_save_data.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_decrement_item_no_item_data(self, service_handler, mock_service_call):
        """Test decrementing when get_item returns None."""
        mock_service_call.data = {
            "inventory_id": "kitchen",
            "name": "milk"
        }
        service_handler.coordinator.get_item.return_value = None

        await service_handler.async_decrement_item(mock_service_call)

        service_handler.todo_manager.check_and_add_item.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_update_item_settings_success(self, service_handler, mock_service_call):
        """Test successfully updating item settings."""
        mock_service_call.data = {
            "inventory_id": "kitchen",
            "name": "milk",
            "auto_add_enabled": True,
            "threshold": 5,
            "todo_list": "todo.shopping"
        }

        await service_handler.async_update_item_settings(mock_service_call)

        service_handler.coordinator.update_item_settings.assert_called_once_with(
            "kitchen", "milk", auto_add_enabled=True, threshold=5, todo_list="todo.shopping"
        )
        service_handler.coordinator.async_save_data.assert_called_once_with(
            "kitchen")

    @pytest.mark.asyncio
    async def test_async_update_item_settings_not_found(self, service_handler, mock_service_call):
        """Test updating settings for item that doesn't exist."""
        mock_service_call.data = {
            "inventory_id": "kitchen",
            "name": "milk"
        }
        service_handler.coordinator.update_item_settings.return_value = False

        await service_handler.async_update_item_settings(mock_service_call)

        service_handler.coordinator.async_save_data.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_update_item_success(self, service_handler, mock_service_call):
        """Test successfully updating an item."""
        mock_service_call.data = {
            "inventory_id": "kitchen",
            "old_name": "milk",
            "name": "whole_milk",
            "quantity": 3,
            "unit": "liters",
            "category": "dairy"
        }

        await service_handler.async_update_item(mock_service_call)

        service_handler.coordinator.get_item.assert_called_once_with(
            "kitchen", "milk")
        service_handler.coordinator.update_item.assert_called_once_with(
            "kitchen", "milk", "whole_milk",
            quantity=3, unit="liters", category="dairy"
        )
        service_handler.coordinator.async_save_data.assert_called_once_with(
            "kitchen")

    @pytest.mark.asyncio
    async def test_async_update_item_not_found(self, service_handler, mock_service_call):
        """Test updating an item that doesn't exist."""
        mock_service_call.data = {
            "inventory_id": "kitchen",
            "old_name": "milk",
            "name": "whole_milk"
        }
        service_handler.coordinator.get_item.return_value = None

        await service_handler.async_update_item(mock_service_call)

        service_handler.coordinator.update_item.assert_not_called()
        service_handler.coordinator.async_save_data.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_update_item_partial_update(self, service_handler, mock_service_call):
        """Test updating an item with only some fields."""
        mock_service_call.data = {
            "inventory_id": "kitchen",
            "old_name": "milk",
            "name": "milk",
            "quantity": 5
        }

        await service_handler.async_update_item(mock_service_call)

        service_handler.coordinator.update_item.assert_called_once_with(
            "kitchen", "milk", "milk", quantity=5
        )

    @pytest.mark.asyncio
    async def test_async_update_item_coordinator_fails(self, service_handler, mock_service_call):
        """Test when coordinator update fails."""
        mock_service_call.data = {
            "inventory_id": "kitchen",
            "old_name": "milk",
            "name": "whole_milk"
        }
        service_handler.coordinator.update_item.return_value = False

        await service_handler.async_update_item(mock_service_call)

        service_handler.coordinator.async_save_data.assert_not_called()


class TestSchemas:
    """Test schema validation."""

    def test_item_schema_valid_full(self):
        """Test ITEM_SCHEMA with all fields."""
        data = {
            "inventory_id": "kitchen",
            "name": "milk",
            "quantity": 2,
            "unit": "liters",
            "category": "dairy",
            "expiry_date": "2024-12-31",
            "auto_add_enabled": True,
            "threshold": 5,
            "todo_list": "todo.shopping"
        }
        result = ITEM_SCHEMA(data)
        assert result == data

    def test_item_schema_valid_minimal(self):
        """Test ITEM_SCHEMA with required fields only."""
        data = {
            "inventory_id": "kitchen",
            "name": "milk"
        }
        result = ITEM_SCHEMA(data)
        assert result["inventory_id"] == "kitchen"
        assert result["name"] == "milk"
        assert result["quantity"] == 1  # default
        assert result["unit"] == ""  # default
        assert result["auto_add_enabled"] is False  # default

    def test_item_schema_invalid_missing_required(self):
        """Test ITEM_SCHEMA with missing required fields."""
        data = {"inventory_id": "kitchen"}
        with pytest.raises(vol.Invalid):
            ITEM_SCHEMA(data)

    def test_item_schema_invalid_negative_quantity(self):
        """Test ITEM_SCHEMA with negative quantity."""
        data = {
            "inventory_id": "kitchen",
            "name": "milk",
            "quantity": -1
        }
        with pytest.raises(vol.Invalid):
            ITEM_SCHEMA(data)

    def test_update_schema_valid(self):
        """Test UPDATE_SCHEMA validation."""
        data = {
            "inventory_id": "kitchen",
            "name": "milk",
            "amount": 5
        }
        result = UPDATE_SCHEMA(data)
        assert result == data

    def test_update_schema_default_amount(self):
        """Test UPDATE_SCHEMA with default amount."""
        data = {
            "inventory_id": "kitchen",
            "name": "milk"
        }
        result = UPDATE_SCHEMA(data)
        assert result["amount"] == 1

    def test_remove_schema_valid(self):
        """Test REMOVE_SCHEMA validation."""
        data = {
            "inventory_id": "kitchen",
            "name": "milk"
        }
        result = REMOVE_SCHEMA(data)
        assert result == data

    def test_update_settings_schema_valid(self):
        """Test UPDATE_SETTINGS_SCHEMA validation."""
        data = {
            "inventory_id": "kitchen",
            "name": "milk",
            "auto_add_enabled": True,
            "threshold": 5,
            "todo_list": "todo.shopping"
        }
        result = UPDATE_SETTINGS_SCHEMA(data)
        assert result == data

    def test_update_item_schema_valid_full(self):
        """Test UPDATE_ITEM_SCHEMA with all fields."""
        data = {
            "inventory_id": "kitchen",
            "old_name": "milk",
            "name": "whole_milk",
            "quantity": 3,
            "unit": "liters",
            "category": "dairy",
            "expiry_date": "2024-12-31",
            "auto_add_enabled": True,
            "threshold": 5,
            "todo_list": "todo.shopping"
        }
        result = UPDATE_ITEM_SCHEMA(data)
        assert result == data

    def test_update_item_schema_zero_quantity_allowed(self):
        """Test UPDATE_ITEM_SCHEMA allows zero quantity."""
        data = {
            "inventory_id": "kitchen",
            "old_name": "milk",
            "name": "milk",
            "quantity": 0
        }
        result = UPDATE_ITEM_SCHEMA(data)
        assert result["quantity"] == 0

    def test_update_item_schema_negative_quantity_invalid(self):
        """Test UPDATE_ITEM_SCHEMA rejects negative quantity."""
        data = {
            "inventory_id": "kitchen",
            "old_name": "milk",
            "name": "milk",
            "quantity": -1
        }
        with pytest.raises(vol.Invalid):
            UPDATE_ITEM_SCHEMA(data)

    def test_set_expiry_threshold_schema_valid(self):
        """Test SET_EXPIRY_THRESHOLD_SCHEMA validation."""
        data = {"threshold_days": 7}
        result = SET_EXPIRY_THRESHOLD_SCHEMA(data)
        assert result == data

    @pytest.mark.parametrize("threshold_days", [0, 31, -1])
    def test_set_expiry_threshold_schema_invalid_range(self, threshold_days):
        """Test SET_EXPIRY_THRESHOLD_SCHEMA with invalid ranges."""
        data = {"threshold_days": threshold_days}
        with pytest.raises(vol.Invalid):
            SET_EXPIRY_THRESHOLD_SCHEMA(data)


class TestServiceHandlerIntegration:
    """Integration tests for ServiceHandler."""

    @pytest.fixture
    def service_handler_integration(self, hass):
        """Create ServiceHandler with real-ish dependencies for integration testing."""
        coordinator = MagicMock()
        coordinator.async_save_data = AsyncMock()
        todo_manager = MagicMock()
        todo_manager.check_and_add_item = AsyncMock()
        return ServiceHandler(hass, coordinator, todo_manager)

    @pytest.mark.asyncio
    async def test_complete_add_workflow(self, service_handler_integration):
        """Test complete workflow of adding an item."""
        call = MagicMock()
        call.data = {
            "inventory_id": "pantry",
            "name": "rice",
            "quantity": 5,
            "unit": "kg",
            "auto_add_enabled": True,
            "threshold": 2
        }

        await service_handler_integration.async_add_item(call)

        service_handler_integration.coordinator.add_item.assert_called_once_with(
            "pantry", "rice", quantity=5, unit="kg", auto_add_enabled=True, threshold=2
        )
        service_handler_integration.coordinator.async_save_data.assert_called_once_with(
            "pantry")

    @pytest.mark.asyncio
    async def test_complete_decrement_with_todo_workflow(self, service_handler_integration):
        """Test complete workflow of decrementing an item and checking todo."""
        call = MagicMock()
        call.data = {
            "inventory_id": "pantry",
            "name": "rice",
            "amount": 3
        }

        service_handler_integration.coordinator.decrement_item.return_value = True
        service_handler_integration.coordinator.get_item.return_value = {
            "quantity": 1,
            "threshold": 2,
            "auto_add_enabled": True,
            "todo_list": "todo.shopping"
        }

        await service_handler_integration.async_decrement_item(call)

        service_handler_integration.coordinator.decrement_item.assert_called_once_with(
            "pantry", "rice", 3)
        service_handler_integration.coordinator.get_item.assert_called_once_with(
            "pantry", "rice")
        service_handler_integration.todo_manager.check_and_add_item.assert_called_once_with(
            "rice",
            {"quantity": 1, "threshold": 2, "auto_add_enabled": True,
                "todo_list": "todo.shopping"}
        )
        service_handler_integration.coordinator.async_save_data.assert_called_once_with(
            "pantry")
