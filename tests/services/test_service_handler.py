"""Tests for Service Handler initialization."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typing_extensions import Self

from custom_components.simple_inventory.services import ServiceHandler


class TestServiceHandler:
    """Test ServiceHandler class."""

    @pytest.fixture
    def mock_hass(self: Self) -> MagicMock:
        """Create a mock Home Assistant instance."""
        return MagicMock()

    @pytest.fixture
    def mock_coordinator(self: Self) -> MagicMock:
        """Create a mock coordinator."""
        return MagicMock()

    @pytest.fixture
    def mock_todo_manager(self: Self) -> MagicMock:
        """Create a mock todo manager."""
        return MagicMock()

    @pytest.fixture
    def mock_service_call(self: Self) -> MagicMock:
        """Create a mock service call."""
        call = MagicMock()
        call.data = {"inventory_id": "kitchen", "name": "milk", "quantity": 2}
        return call

    def test_init(
        self: Self,
        mock_hass: MagicMock,
        mock_coordinator: MagicMock,
        mock_todo_manager: MagicMock,
    ) -> None:
        """Test ServiceHandler initialization."""
        with (
            patch(
                "custom_components.simple_inventory.services.InventoryService"
            ) as mock_inventory_service,
            patch(
                "custom_components.simple_inventory.services.QuantityService"
            ) as mock_quantity_service,
        ):

            service_handler = ServiceHandler(mock_hass, mock_coordinator, mock_todo_manager)

            assert service_handler.hass is mock_hass
            assert service_handler.coordinator is mock_coordinator
            assert service_handler.todo_manager is mock_todo_manager

            mock_inventory_service.assert_called_once_with(
                mock_hass, mock_coordinator, mock_todo_manager
            )
            mock_quantity_service.assert_called_once_with(
                mock_hass, mock_coordinator, mock_todo_manager
            )

            assert service_handler.inventory_service == mock_inventory_service.return_value
            assert service_handler.quantity_service == mock_quantity_service.return_value

    @pytest.mark.asyncio
    async def test_async_add_item(
        self: Self,
        mock_hass: MagicMock,
        mock_coordinator: MagicMock,
        mock_todo_manager: MagicMock,
        mock_service_call: MagicMock,
    ) -> None:
        """Test async_add_item delegates to inventory service."""
        with (
            patch(
                "custom_components.simple_inventory.services.InventoryService"
            ) as mock_inventory_service,
            patch("custom_components.simple_inventory.services.QuantityService"),
        ):

            mock_inventory_instance = MagicMock()
            mock_inventory_instance.async_add_item = AsyncMock()
            mock_inventory_service.return_value = mock_inventory_instance

            service_handler = ServiceHandler(mock_hass, mock_coordinator, mock_todo_manager)
            await service_handler.async_add_item(mock_service_call)

            mock_inventory_instance.async_add_item.assert_called_once_with(mock_service_call)

    @pytest.mark.asyncio
    async def test_async_remove_item(
        self: Self,
        mock_hass: MagicMock,
        mock_coordinator: MagicMock,
        mock_todo_manager: MagicMock,
        mock_service_call: MagicMock,
    ) -> None:
        """Test async_remove_item delegates to inventory service."""
        with (
            patch(
                "custom_components.simple_inventory.services.InventoryService"
            ) as mock_inventory_service,
            patch("custom_components.simple_inventory.services.QuantityService"),
        ):

            mock_inventory_instance = MagicMock()
            mock_inventory_instance.async_remove_item = AsyncMock()
            mock_inventory_service.return_value = mock_inventory_instance

            service_handler = ServiceHandler(mock_hass, mock_coordinator, mock_todo_manager)
            await service_handler.async_remove_item(mock_service_call)

            mock_inventory_instance.async_remove_item.assert_called_once_with(mock_service_call)

    @pytest.mark.asyncio
    async def test_async_update_item(
        self: Self,
        mock_hass: MagicMock,
        mock_coordinator: MagicMock,
        mock_todo_manager: MagicMock,
        mock_service_call: MagicMock,
    ) -> None:
        """Test async_update_item delegates to inventory service."""
        with (
            patch(
                "custom_components.simple_inventory.services.InventoryService"
            ) as mock_inventory_service,
            patch("custom_components.simple_inventory.services.QuantityService"),
        ):

            mock_inventory_instance = MagicMock()
            mock_inventory_instance.async_update_item = AsyncMock()
            mock_inventory_service.return_value = mock_inventory_instance

            service_handler = ServiceHandler(mock_hass, mock_coordinator, mock_todo_manager)
            await service_handler.async_update_item(mock_service_call)

            mock_inventory_instance.async_update_item.assert_called_once_with(mock_service_call)

    @pytest.mark.asyncio
    async def test_async_increment_item(
        self: Self,
        mock_hass: MagicMock,
        mock_coordinator: MagicMock,
        mock_todo_manager: MagicMock,
        mock_service_call: MagicMock,
    ) -> None:
        """Test async_increment_item delegates to quantity service."""
        with (
            patch("custom_components.simple_inventory.services.InventoryService"),
            patch(
                "custom_components.simple_inventory.services.QuantityService"
            ) as mock_quantity_service,
        ):

            mock_quantity_instance = MagicMock()
            mock_quantity_instance.async_increment_item = AsyncMock()
            mock_quantity_service.return_value = mock_quantity_instance

            service_handler = ServiceHandler(mock_hass, mock_coordinator, mock_todo_manager)
            await service_handler.async_increment_item(mock_service_call)

            mock_quantity_instance.async_increment_item.assert_called_once_with(mock_service_call)

    @pytest.mark.asyncio
    async def test_async_decrement_item(
        self: Self,
        mock_hass: MagicMock,
        mock_coordinator: MagicMock,
        mock_todo_manager: MagicMock,
        mock_service_call: MagicMock,
    ) -> None:
        """Test async_decrement_item delegates to quantity service."""
        with (
            patch("custom_components.simple_inventory.services.InventoryService"),
            patch(
                "custom_components.simple_inventory.services.QuantityService"
            ) as mock_quantity_service,
        ):

            mock_quantity_instance = MagicMock()
            mock_quantity_instance.async_decrement_item = AsyncMock()
            mock_quantity_service.return_value = mock_quantity_instance

            service_handler = ServiceHandler(mock_hass, mock_coordinator, mock_todo_manager)
            await service_handler.async_decrement_item(mock_service_call)

            mock_quantity_instance.async_decrement_item.assert_called_once_with(mock_service_call)

    @pytest.mark.asyncio
    async def test_async_add_item_exception_propagation(
        self: Self,
        mock_hass: MagicMock,
        mock_coordinator: MagicMock,
        mock_todo_manager: MagicMock,
        mock_service_call: MagicMock,
    ) -> None:
        """Test that exceptions from inventory service are propagated."""
        with (
            patch(
                "custom_components.simple_inventory.services.InventoryService"
            ) as mock_inventory_service,
            patch("custom_components.simple_inventory.services.QuantityService"),
        ):

            mock_inventory_instance = MagicMock()
            mock_inventory_instance.async_add_item = AsyncMock(side_effect=Exception("Add failed"))
            mock_inventory_service.return_value = mock_inventory_instance

            service_handler = ServiceHandler(mock_hass, mock_coordinator, mock_todo_manager)

            with pytest.raises(Exception, match="Add failed"):
                await service_handler.async_add_item(mock_service_call)

            mock_inventory_instance.async_add_item.assert_called_once_with(mock_service_call)

    @pytest.mark.asyncio
    async def test_async_increment_item_exception_propagation(
        self: Self,
        mock_hass: MagicMock,
        mock_coordinator: MagicMock,
        mock_todo_manager: MagicMock,
        mock_service_call: MagicMock,
    ) -> None:
        """Test that exceptions from quantity service are propagated."""
        with (
            patch("custom_components.simple_inventory.services.InventoryService"),
            patch(
                "custom_components.simple_inventory.services.QuantityService"
            ) as mock_quantity_service,
        ):

            mock_quantity_instance = MagicMock()
            mock_quantity_instance.async_increment_item = AsyncMock(
                side_effect=Exception("Increment failed")
            )
            mock_quantity_service.return_value = mock_quantity_instance

            service_handler = ServiceHandler(mock_hass, mock_coordinator, mock_todo_manager)

            with pytest.raises(Exception, match="Increment failed"):
                await service_handler.async_increment_item(mock_service_call)

            mock_quantity_instance.async_increment_item.assert_called_once_with(mock_service_call)

    @pytest.mark.asyncio
    async def test_multiple_service_calls(
        self: Self,
        mock_hass: MagicMock,
        mock_coordinator: MagicMock,
        mock_todo_manager: MagicMock,
    ) -> None:
        """Test that multiple service calls work correctly."""
        with (
            patch(
                "custom_components.simple_inventory.services.InventoryService"
            ) as mock_inventory_service,
            patch(
                "custom_components.simple_inventory.services.QuantityService"
            ) as mock_quantity_service,
        ):

            mock_inventory_instance = MagicMock()
            mock_inventory_instance.async_add_item = AsyncMock()
            mock_inventory_instance.async_remove_item = AsyncMock()
            mock_inventory_service.return_value = mock_inventory_instance
            mock_quantity_instance = MagicMock()
            mock_quantity_instance.async_increment_item = AsyncMock()
            mock_quantity_instance.async_decrement_item = AsyncMock()
            mock_quantity_service.return_value = mock_quantity_instance
            service_handler = ServiceHandler(mock_hass, mock_coordinator, mock_todo_manager)

            add_call = MagicMock()
            add_call.data = {"inventory_id": "kitchen", "name": "milk"}

            remove_call = MagicMock()
            remove_call.data = {"inventory_id": "kitchen", "name": "bread"}

            increment_call = MagicMock()
            increment_call.data = {"inventory_id": "pantry", "name": "rice"}

            decrement_call = MagicMock()
            decrement_call.data = {"inventory_id": "pantry", "name": "pasta"}

            await service_handler.async_add_item(add_call)
            await service_handler.async_remove_item(remove_call)
            await service_handler.async_increment_item(increment_call)
            await service_handler.async_decrement_item(decrement_call)

            mock_inventory_instance.async_add_item.assert_called_once_with(add_call)
            mock_inventory_instance.async_remove_item.assert_called_once_with(remove_call)
            mock_quantity_instance.async_increment_item.assert_called_once_with(increment_call)
            mock_quantity_instance.async_decrement_item.assert_called_once_with(decrement_call)

    def test_exports(self: Self) -> None:
        """Test that __all__ exports are correct."""
        from custom_components.simple_inventory.services import __all__

        expected_exports = [
            "ServiceHandler",
            "InventoryService",
            "QuantityService",
        ]
        assert __all__ == expected_exports

    def test_import_structure(self: Self) -> None:
        """Test that imports work correctly."""
        from custom_components.simple_inventory.services import (
            InventoryService,
            QuantityService,
            ServiceHandler,
        )

        assert callable(ServiceHandler)
        assert callable(InventoryService)
        assert callable(QuantityService)

    @pytest.mark.asyncio
    async def test_service_handler_isolation(
        self: Self,
        mock_hass: MagicMock,
        mock_coordinator: MagicMock,
        mock_todo_manager: MagicMock,
    ) -> None:
        """Test that multiple ServiceHandler instances don't interfere with each other."""
        with (
            patch(
                "custom_components.simple_inventory.services.InventoryService"
            ) as mock_inventory_service,
            patch(
                "custom_components.simple_inventory.services.QuantityService"
            ) as mock_quantity_service,
        ):

            mock_inventory_service.side_effect = (
                lambda *args: MagicMock(),
                lambda **kwargs: MagicMock(),
            )
            mock_quantity_service.side_effect = (
                lambda *args: MagicMock(),
                lambda **kwargs: MagicMock(),
            )

            service_handler1 = ServiceHandler(mock_hass, mock_coordinator, mock_todo_manager)
            service_handler2 = ServiceHandler(mock_hass, mock_coordinator, mock_todo_manager)

            assert service_handler1.inventory_service is not service_handler2.inventory_service
            assert service_handler1.quantity_service is not service_handler2.quantity_service
            assert mock_inventory_service.call_count == 2
            assert mock_quantity_service.call_count == 2
