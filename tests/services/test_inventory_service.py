"""Tests for InventoryService."""

import logging
from unittest.mock import MagicMock

import pytest
from homeassistant.core import ServiceCall
from typing_extensions import Self

from custom_components.simple_inventory.services.inventory_service import (
    InventoryService,
)


class TestInventoryService:
    """Test InventoryService class."""

    def test_inheritance(self: Self, inventory_service: InventoryService) -> None:
        """Test that InventoryService properly inherits from BaseServiceHandler."""
        from custom_components.simple_inventory.services.base_service import (
            BaseServiceHandler,
        )

        assert isinstance(inventory_service, BaseServiceHandler)
        assert hasattr(inventory_service, "_save_and_log_success")
        assert hasattr(inventory_service, "_extract_item_kwargs")
        assert hasattr(inventory_service, "_get_inventory_and_name")

    @pytest.mark.asyncio
    async def test_async_add_item_success(
        self: Self,
        inventory_service: InventoryService,
        add_item_service_call: ServiceCall,
        mock_coordinator: MagicMock,
    ) -> None:
        """Test successful item addition."""
        await inventory_service.async_add_item(add_item_service_call)

        mock_coordinator.add_item.assert_called_once_with(
            "kitchen",
            name="milk",
            auto_add_enabled=True,
            auto_add_to_list_quantity=1,
            category="dairy",
            location="fridge",
            expiry_alert_days=7,
            expiry_date="2024-12-31",
            quantity=2,
            todo_list="todo.shopping",
            unit="liters",
        )

        mock_coordinator.async_save_data.assert_called_once_with("kitchen")

    @pytest.mark.asyncio
    async def test_async_add_item_minimal_data(
        self: Self,
        inventory_service: InventoryService,
        basic_service_call: ServiceCall,
        mock_coordinator: MagicMock,
    ) -> None:
        """Test adding item with minimal required data."""
        await inventory_service.async_add_item(basic_service_call)

        mock_coordinator.add_item.assert_called_once_with("kitchen", name="milk")
        mock_coordinator.async_save_data.assert_called_once_with("kitchen")

    @pytest.mark.asyncio
    async def test_async_add_item_coordinator_exception(
        self: Self,
        inventory_service: InventoryService,
        add_item_service_call: ServiceCall,
        mock_coordinator: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test handling coordinator exception during add."""
        mock_coordinator.add_item.side_effect = Exception("Database error")

        with caplog.at_level(logging.ERROR):
            await inventory_service.async_add_item(add_item_service_call)

        assert "Failed to add item milk to inventory kitchen: Database error" in caplog.text
        mock_coordinator.async_save_data.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_remove_item_success(
        self: Self,
        inventory_service: InventoryService,
        basic_service_call: ServiceCall,
        mock_coordinator: MagicMock,
    ) -> None:
        """Test successful item removal."""
        mock_coordinator.remove_item.return_value = True

        await inventory_service.async_remove_item(basic_service_call)

        mock_coordinator.remove_item.assert_called_once_with("kitchen", "milk")
        mock_coordinator.async_save_data.assert_called_once_with("kitchen")

    @pytest.mark.asyncio
    async def test_async_remove_item_not_found(
        self: Self,
        inventory_service: InventoryService,
        basic_service_call: ServiceCall,
        mock_coordinator: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test removing item that doesn't exist."""
        mock_coordinator.remove_item.return_value = False

        with caplog.at_level(logging.WARNING):
            await inventory_service.async_remove_item(basic_service_call)

        mock_coordinator.remove_item.assert_called_once_with("kitchen", "milk")
        mock_coordinator.async_save_data.assert_not_called()

        assert "Remove item failed - Item not found: milk in inventory: kitchen" in caplog.text

    @pytest.mark.asyncio
    async def test_async_remove_item_coordinator_exception(
        self: Self,
        inventory_service: InventoryService,
        basic_service_call: ServiceCall,
        mock_coordinator: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test handling coordinator exception during remove."""
        mock_coordinator.remove_item.side_effect = Exception("Database connection lost")

        with caplog.at_level(logging.ERROR):
            await inventory_service.async_remove_item(basic_service_call)

        assert (
            "Failed to remove item milk from inventory kitchen: Database connection lost"
            in caplog.text
        )
        mock_coordinator.async_save_data.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_update_item_success(
        self: Self,
        inventory_service: InventoryService,
        update_item_service_call: ServiceCall,
        mock_coordinator: MagicMock,
    ) -> None:
        """Test successful item update."""
        await inventory_service.async_update_item(update_item_service_call)

        mock_coordinator.get_item.assert_called_once_with("kitchen", "milk")
        mock_coordinator.update_item.assert_called_once_with(
            "kitchen",
            "milk",
            "whole_milk",
            quantity=3,
            unit="liters",
            category="dairy",
            location="fridge",
        )

        mock_coordinator.async_save_data.assert_called_once_with("kitchen")

    @pytest.mark.asyncio
    async def test_async_update_item_not_found(
        self: Self,
        inventory_service: InventoryService,
        update_item_service_call: ServiceCall,
        mock_coordinator: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test updating item that doesn't exist."""
        mock_coordinator.get_item.return_value = None

        with caplog.at_level(logging.WARNING):
            await inventory_service.async_update_item(update_item_service_call)

        # Should check existence but not proceed with update
        mock_coordinator.get_item.assert_called_once_with("kitchen", "milk")
        mock_coordinator.update_item.assert_not_called()
        mock_coordinator.async_save_data.assert_not_called()

        assert "Update item failed - Item not found: milk in inventory: kitchen" in caplog.text

    @pytest.mark.asyncio
    async def test_async_update_item_coordinator_update_fails(
        self: Self,
        inventory_service: InventoryService,
        update_item_service_call: ServiceCall,
        mock_coordinator: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test when coordinator update returns False."""
        mock_coordinator.update_item.return_value = False

        with caplog.at_level(logging.ERROR):
            await inventory_service.async_update_item(update_item_service_call)

        mock_coordinator.update_item.assert_called_once()
        mock_coordinator.async_save_data.assert_not_called()

        assert "Update item failed for item: milk in inventory: kitchen" in caplog.text

    @pytest.mark.asyncio
    async def test_async_update_item_coordinator_exception(
        self: Self,
        inventory_service: InventoryService,
        update_item_service_call: ServiceCall,
        mock_coordinator: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test handling coordinator exception during update."""
        mock_coordinator.update_item.side_effect = Exception("Update failed")

        with caplog.at_level(logging.ERROR):
            await inventory_service.async_update_item(update_item_service_call)

        assert "Failed to update item milk in inventory kitchen: Update failed" in caplog.text
        mock_coordinator.async_save_data.assert_not_called()

    @pytest.mark.asyncio
    async def test_concurrent_operations(
        self: Self,
        inventory_service: InventoryService,
        mock_coordinator: MagicMock,
    ) -> None:
        """Test concurrent inventory operations."""
        import asyncio

        calls = []
        for i in range(3):
            call = MagicMock()
            call.data = {
                "inventory_id": f"inventory_{i}",
                "name": f"item_{i}",
                "quantity": i + 1,
            }
            calls.append(call)

        tasks = [inventory_service.async_add_item(call) for call in calls]
        await asyncio.gather(*tasks)

        assert mock_coordinator.add_item.call_count == 3
        assert mock_coordinator.async_save_data.call_count == 3
