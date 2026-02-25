"""Tests for ServiceHandler initialization and delegation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typing_extensions import Self

from custom_components.simple_inventory.const import DOMAIN
from custom_components.simple_inventory.services import ServiceHandler


class TestServiceHandler:
    """Test ServiceHandler class."""

    @pytest.fixture
    def mock_hass(self: Self) -> MagicMock:
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.bus = MagicMock()
        hass.bus.async_fire = MagicMock()
        return hass

    @pytest.fixture
    def mock_todo_manager(self: Self) -> MagicMock:
        """Create a mock todo manager."""
        return MagicMock()

    @pytest.fixture
    def mock_service_call(self: Self) -> MagicMock:
        """Create a mock service call."""
        call = MagicMock()
        call.data = {"inventory_id": "kitchen", "name": "milk", "quantity": 2}
        call.context.id = "ctx-123"
        return call

    def test_init(
        self: Self,
        mock_hass: MagicMock,
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
            service_handler = ServiceHandler(mock_hass, mock_todo_manager)

            assert service_handler.hass is mock_hass
            assert service_handler.todo_manager is mock_todo_manager

            mock_inventory_service.assert_called_once_with(mock_hass, mock_todo_manager)
            mock_quantity_service.assert_called_once_with(mock_hass, mock_todo_manager)

            assert service_handler.inventory_service == mock_inventory_service.return_value
            assert service_handler.quantity_service == mock_quantity_service.return_value

    @pytest.mark.asyncio
    async def test_async_add_item(
        self: Self,
        mock_hass: MagicMock,
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

            service_handler = ServiceHandler(mock_hass, mock_todo_manager)
            await service_handler.async_add_item(mock_service_call)

            mock_inventory_instance.async_add_item.assert_awaited_once_with(mock_service_call)

    @pytest.mark.asyncio
    async def test_async_remove_item(
        self: Self,
        mock_hass: MagicMock,
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

            service_handler = ServiceHandler(mock_hass, mock_todo_manager)
            await service_handler.async_remove_item(mock_service_call)

            mock_inventory_instance.async_remove_item.assert_awaited_once_with(mock_service_call)

    @pytest.mark.asyncio
    async def test_async_update_item(
        self: Self,
        mock_hass: MagicMock,
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

            service_handler = ServiceHandler(mock_hass, mock_todo_manager)
            await service_handler.async_update_item(mock_service_call)

            mock_inventory_instance.async_update_item.assert_awaited_once_with(mock_service_call)

    @pytest.mark.asyncio
    async def test_async_increment_item(
        self: Self,
        mock_hass: MagicMock,
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

            service_handler = ServiceHandler(mock_hass, mock_todo_manager)
            await service_handler.async_increment_item(mock_service_call)

            mock_quantity_instance.async_increment_item.assert_awaited_once_with(mock_service_call)

    @pytest.mark.asyncio
    async def test_async_decrement_item(
        self: Self,
        mock_hass: MagicMock,
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

            service_handler = ServiceHandler(mock_hass, mock_todo_manager)
            await service_handler.async_decrement_item(mock_service_call)

            mock_quantity_instance.async_decrement_item.assert_awaited_once_with(mock_service_call)

    @pytest.mark.asyncio
    async def test_async_get_items_fires_event(
        self: Self,
        mock_hass: MagicMock,
        mock_todo_manager: MagicMock,
        mock_service_call: MagicMock,
    ) -> None:
        """Test async_get_items fires a result event."""
        with (
            patch(
                "custom_components.simple_inventory.services.InventoryService"
            ) as mock_inventory_service,
            patch("custom_components.simple_inventory.services.QuantityService"),
        ):
            mock_inventory_instance = MagicMock()
            mock_inventory_instance.async_get_items = AsyncMock(return_value={"items": []})
            mock_inventory_service.return_value = mock_inventory_instance

            service_handler = ServiceHandler(mock_hass, mock_todo_manager)
            await service_handler.async_get_items(mock_service_call)

            mock_inventory_instance.async_get_items.assert_awaited_once_with(mock_service_call)
            mock_hass.bus.async_fire.assert_called_once()
            event_name, payload = mock_hass.bus.async_fire.call_args[0]
            assert event_name == f"{DOMAIN}_get_items_result"
            assert payload["context_id"] == "ctx-123"

    @pytest.mark.asyncio
    async def test_async_get_all_items_fires_event(
        self: Self,
        mock_hass: MagicMock,
        mock_todo_manager: MagicMock,
        mock_service_call: MagicMock,
    ) -> None:
        """Test async_get_items_from_all_inventories fires a result event."""
        with (
            patch(
                "custom_components.simple_inventory.services.InventoryService"
            ) as mock_inventory_service,
            patch("custom_components.simple_inventory.services.QuantityService"),
        ):
            mock_inventory_instance = MagicMock()
            mock_inventory_instance.async_get_items_from_all_inventories = AsyncMock(
                return_value={"inventories": []}
            )
            mock_inventory_service.return_value = mock_inventory_instance

            service_handler = ServiceHandler(mock_hass, mock_todo_manager)
            await service_handler.async_get_items_from_all_inventories(mock_service_call)

            mock_inventory_instance.async_get_items_from_all_inventories.assert_awaited_once_with(
                mock_service_call
            )
            mock_hass.bus.async_fire.assert_called_once()
            event_name, payload = mock_hass.bus.async_fire.call_args[0]
            assert event_name == f"{DOMAIN}_get_all_items_result"
            assert payload["context_id"] == "ctx-123"

    @pytest.mark.asyncio
    async def test_scan_barcode_delegates_to_quantity_service(
        self: Self,
        mock_hass: MagicMock,
        mock_todo_manager: MagicMock,
    ) -> None:
        """async_scan_barcode must be a thin adapter that delegates to quantity_service."""
        expected = {"action": "decrement", "success": True, "item_name": "Milk"}
        mock_quantity_instance = MagicMock()
        mock_quantity_instance.async_scan_barcode = AsyncMock(return_value=expected)

        call = MagicMock()
        call.data = {
            "barcode": "123456",
            "action": "decrement",
            "amount": 2.0,
            "inventory_id": "kitchen",
            "price": None,
        }

        with (
            patch("custom_components.simple_inventory.services.InventoryService"),
            patch("custom_components.simple_inventory.services.QuantityService") as mock_qs_cls,
        ):
            mock_qs_cls.return_value = mock_quantity_instance
            handler = ServiceHandler(mock_hass, mock_todo_manager)
            result = await handler.async_scan_barcode(call)

        mock_quantity_instance.async_scan_barcode.assert_awaited_once_with(
            barcode="123456",
            action="decrement",
            amount=2.0,
            inventory_id="kitchen",
            price=None,
        )
        assert result == expected

    def test_exports(self: Self) -> None:
        """Test that __all__ exports are correct."""
        from custom_components.simple_inventory.services import __all__

        assert __all__ == ["ServiceHandler", "InventoryService", "QuantityService"]

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
