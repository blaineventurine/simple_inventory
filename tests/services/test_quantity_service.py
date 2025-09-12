"""Tests for QuantityService."""

import logging
from unittest.mock import MagicMock

import pytest
from homeassistant.core import HomeAssistant, ServiceCall
from typing_extensions import Self

from custom_components.simple_inventory.services.quantity_service import (
    QuantityService,
)


class TestQuantityService:
    """Test QuantityService class."""

    def test_init(
        self: Self,
        hass: HomeAssistant,
        mock_coordinator: MagicMock,
        mock_todo_manager: MagicMock,
    ) -> None:
        """Test QuantityService initialization."""
        from custom_components.simple_inventory.services.quantity_service import (
            QuantityService,
        )

        service = QuantityService(hass, mock_coordinator, mock_todo_manager)

        assert service.hass is hass
        assert service.coordinator is mock_coordinator
        assert service.todo_manager is mock_todo_manager

    def test_inheritance(self: Self, quantity_service: QuantityService) -> None:
        """Test that QuantityService properly inherits from BaseServiceHandler."""
        from custom_components.simple_inventory.services.base_service import (
            BaseServiceHandler,
        )

        assert isinstance(quantity_service, BaseServiceHandler)
        assert hasattr(quantity_service, "_save_and_log_success")
        assert hasattr(quantity_service, "_get_inventory_and_name")
        assert hasattr(quantity_service, "_log_item_not_found")

    @pytest.mark.asyncio
    async def test_async_increment_item_success(
        self: Self,
        quantity_service: QuantityService,
        quantity_service_call: ServiceCall,
        mock_coordinator: MagicMock,
    ) -> None:
        """Test successful item increment."""
        await quantity_service.async_increment_item(quantity_service_call)

        mock_coordinator.increment_item.assert_called_once_with("kitchen", "milk", 2)
        mock_coordinator.async_save_data.assert_called_once_with("kitchen")

    @pytest.mark.asyncio
    async def test_async_increment_item_default_amount(
        self: Self,
        quantity_service: QuantityService,
        basic_service_call: ServiceCall,
        mock_coordinator: MagicMock,
    ) -> None:
        """Test increment with default amount (1)."""
        await quantity_service.async_increment_item(basic_service_call)

        mock_coordinator.increment_item.assert_called_once_with("kitchen", "milk", 1)
        mock_coordinator.async_save_data.assert_called_once_with("kitchen")

    @pytest.mark.asyncio
    async def test_async_increment_item_not_found(
        self: Self,
        quantity_service: QuantityService,
        quantity_service_call: ServiceCall,
        mock_coordinator: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test incrementing item that doesn't exist."""
        mock_coordinator.increment_item.return_value = False

        with caplog.at_level(logging.WARNING):
            await quantity_service.async_increment_item(quantity_service_call)

        mock_coordinator.increment_item.assert_called_once_with("kitchen", "milk", 2)
        mock_coordinator.async_save_data.assert_not_called()

        assert "Increment item failed - Item not found: milk in inventory: kitchen" in caplog.text

    @pytest.mark.asyncio
    async def test_async_increment_item_coordinator_exception(
        self: Self,
        quantity_service: QuantityService,
        quantity_service_call: ServiceCall,
        mock_coordinator: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test handling coordinator exception during increment."""
        mock_coordinator.increment_item.side_effect = Exception("Database error")

        with caplog.at_level(logging.ERROR):
            await quantity_service.async_increment_item(quantity_service_call)

        assert "Failed to increment item milk in inventory kitchen: Database error" in caplog.text
        mock_coordinator.async_save_data.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_decrement_item_success_with_todo_check(
        self: Self,
        quantity_service: QuantityService,
        quantity_service_call: ServiceCall,
        mock_coordinator: MagicMock,
        mock_todo_manager: MagicMock,
    ) -> None:
        """Test successful item decrement with todo list check."""
        await quantity_service.async_decrement_item(quantity_service_call)

        mock_coordinator.decrement_item.assert_called_once_with("kitchen", "milk", 2)
        mock_coordinator.get_item.assert_called_once_with("kitchen", "milk")
        expected_item_data = {"quantity": 5, "auto_add_to_list_quantity": 2}
        mock_todo_manager.check_and_add_item.assert_called_once_with("milk", expected_item_data)
        mock_coordinator.async_save_data.assert_called_once_with("kitchen")

    @pytest.mark.asyncio
    async def test_async_decrement_item_default_amount(
        self: Self,
        quantity_service: QuantityService,
        basic_service_call: ServiceCall,
        mock_coordinator: MagicMock,
        mock_todo_manager: MagicMock,
    ) -> None:
        """Test decrement with default amount (1)."""
        await quantity_service.async_decrement_item(basic_service_call)

        mock_coordinator.decrement_item.assert_called_once_with("kitchen", "milk", 1)
        mock_coordinator.get_item.assert_called_once_with("kitchen", "milk")
        mock_todo_manager.check_and_add_item.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_decrement_item_no_item_data(
        self: Self,
        quantity_service: QuantityService,
        quantity_service_call: ServiceCall,
        mock_coordinator: MagicMock,
        mock_todo_manager: MagicMock,
    ) -> None:
        """Test decrement when get_item returns None."""
        mock_coordinator.get_item.return_value = None

        await quantity_service.async_decrement_item(quantity_service_call)

        mock_coordinator.decrement_item.assert_called_once()
        mock_coordinator.get_item.assert_called_once()
        mock_todo_manager.check_and_add_item.assert_not_called()
        mock_coordinator.async_save_data.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_decrement_item_not_found(
        self: Self,
        quantity_service: QuantityService,
        quantity_service_call: ServiceCall,
        mock_coordinator: MagicMock,
        mock_todo_manager: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test decrementing item that doesn't exist."""
        mock_coordinator.decrement_item.return_value = False

        with caplog.at_level(logging.WARNING):
            await quantity_service.async_decrement_item(quantity_service_call)

        mock_coordinator.decrement_item.assert_called_once_with("kitchen", "milk", 2)

        mock_coordinator.get_item.assert_not_called()
        mock_todo_manager.check_and_add_item.assert_not_called()
        mock_coordinator.async_save_data.assert_not_called()

        assert "Decrement item failed - Item not found: milk in inventory: kitchen" in caplog.text

    @pytest.mark.asyncio
    async def test_async_decrement_item_coordinator_exception(
        self: Self,
        quantity_service: QuantityService,
        quantity_service_call: ServiceCall,
        mock_coordinator: MagicMock,
        mock_todo_manager: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test handling coordinator exception during decrement."""
        mock_coordinator.decrement_item.side_effect = Exception("Decrement failed")

        with caplog.at_level(logging.ERROR):
            await quantity_service.async_decrement_item(quantity_service_call)

        assert "Failed to decrement item milk in inventory kitchen: Decrement failed" in caplog.text

        mock_todo_manager.check_and_add_item.assert_not_called()
        mock_coordinator.async_save_data.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_decrement_item_todo_manager_exception(
        self: Self,
        quantity_service: QuantityService,
        quantity_service_call: ServiceCall,
        mock_coordinator: MagicMock,
        mock_todo_manager: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test handling todo manager exception during decrement."""
        mock_todo_manager.check_and_add_item.side_effect = Exception("Todo check failed")

        # The exception should be caught and logged, not propagated
        with caplog.at_level(logging.ERROR):
            await quantity_service.async_decrement_item(quantity_service_call)

        mock_coordinator.decrement_item.assert_called_once()
        mock_coordinator.get_item.assert_called_once()

        assert (
            "Failed to decrement item milk in inventory kitchen: Todo check failed" in caplog.text
        )

        mock_coordinator.async_save_data.assert_not_called()

    @pytest.mark.parametrize("amount", [1, 5, 10, 100, 0])
    @pytest.mark.asyncio
    async def test_increment_various_amounts(
        self: Self,
        quantity_service: QuantityService,
        mock_coordinator: MagicMock,
        amount: int,
    ) -> None:
        """Test increment with various amount values."""
        from unittest.mock import MagicMock

        call = MagicMock()
        call.data = {
            "inventory_id": "kitchen",
            "name": "milk",
            "amount": amount,
        }

        await quantity_service.async_increment_item(call)

        mock_coordinator.increment_item.assert_called_once_with("kitchen", "milk", amount)

    @pytest.mark.asyncio
    async def test_concurrent_decrement_operations(
        self: Self,
        quantity_service: QuantityService,
        mock_coordinator: MagicMock,
        mock_todo_manager: MagicMock,
    ) -> None:
        """Test concurrent decrement operations."""
        import asyncio
        from unittest.mock import MagicMock

        calls = []
        for i in range(3):
            call = MagicMock()
            call.data = {
                "inventory_id": f"inventory_{i}",
                "name": f"item_{i}",
                "amount": i + 1,
            }
            calls.append(call)

        tasks = [quantity_service.async_decrement_item(call) for call in calls]
        await asyncio.gather(*tasks)

        assert mock_coordinator.decrement_item.call_count == 3
        assert mock_coordinator.get_item.call_count == 3
        assert mock_todo_manager.check_and_add_item.call_count == 3
        assert mock_coordinator.async_save_data.call_count == 3
