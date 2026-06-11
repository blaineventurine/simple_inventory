"""Tests for InventoryService."""

from __future__ import annotations

import logging
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.core import ServiceCall

from custom_components.simple_inventory.services.base_service import BaseServiceHandler
from custom_components.simple_inventory.services.inventory_service import InventoryService


class TestInventoryService:
    """Test InventoryService class."""

    def test_inheritance(self, inventory_service: InventoryService) -> None:
        assert isinstance(inventory_service, BaseServiceHandler)
        assert hasattr(inventory_service, "_save_and_log_success")
        assert hasattr(inventory_service, "_extract_item_kwargs")
        assert hasattr(inventory_service, "_get_inventory_and_name")

    @pytest.mark.asyncio
    async def test_async_add_item_success(
        self,
        inventory_service: InventoryService,
        add_item_service_call: ServiceCall,
        mock_coordinator: MagicMock,
    ) -> None:
        await inventory_service.async_add_item(add_item_service_call)

        # InventoryService should route to the per-inventory coordinator (async API)
        mock_coordinator.async_add_item.assert_awaited_once()
        args, kwargs = mock_coordinator.async_add_item.call_args

        assert args[0] == "kitchen"  # inventory_id
        assert kwargs["name"] == "milk"
        assert kwargs["quantity"] == 2
        assert kwargs["unit"] == "liters"
        assert kwargs["category"] == "dairy"
        assert kwargs["location"] == "fridge"

        mock_coordinator.async_save_data.assert_awaited_once_with("kitchen")

    @pytest.mark.asyncio
    async def test_async_add_item_minimal_data(
        self,
        inventory_service: InventoryService,
        basic_service_call: ServiceCall,
        mock_coordinator: MagicMock,
    ) -> None:
        # basic_service_call only has inventory_id + name
        await inventory_service.async_add_item(basic_service_call)

        mock_coordinator.async_add_item.assert_awaited_once()
        args, kwargs = mock_coordinator.async_add_item.call_args
        assert args[0] == "kitchen"
        assert kwargs["name"] == "milk"

    @pytest.mark.asyncio
    async def test_async_add_item_coordinator_exception_logged(
        self,
        inventory_service: InventoryService,
        add_item_service_call: ServiceCall,
        mock_coordinator: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_coordinator.async_add_item.side_effect = Exception("Database error")

        with caplog.at_level(logging.ERROR):
            await inventory_service.async_add_item(add_item_service_call)

        assert "Failed to add item" in caplog.text
        mock_coordinator.async_save_data.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_async_remove_item_success(
        self,
        inventory_service: InventoryService,
        basic_service_call: ServiceCall,
        mock_coordinator: MagicMock,
    ) -> None:
        mock_coordinator.async_remove_item.return_value = True
        mock_coordinator.async_get_item.return_value = {"name": "milk", "quantity": 2}

        await inventory_service.async_remove_item(basic_service_call)

        mock_coordinator.async_get_item.assert_awaited_once_with("kitchen", "milk")
        mock_coordinator.async_remove_item.assert_awaited_once_with("kitchen", "milk", barcode=None)
        mock_coordinator.async_save_data.assert_awaited_once_with("kitchen")

    @pytest.mark.asyncio
    async def test_async_remove_item_not_found_logs_warning(
        self,
        inventory_service: InventoryService,
        basic_service_call: ServiceCall,
        mock_coordinator: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_coordinator.async_remove_item.return_value = False

        with caplog.at_level(logging.WARNING):
            await inventory_service.async_remove_item(basic_service_call)

        mock_coordinator.async_remove_item.assert_awaited_once_with("kitchen", "milk", barcode=None)
        mock_coordinator.async_save_data.assert_not_awaited()
        assert "Item not found" in caplog.text

    @pytest.mark.asyncio
    async def test_async_remove_item_coordinator_exception_logged(
        self,
        inventory_service: InventoryService,
        basic_service_call: ServiceCall,
        mock_coordinator: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_coordinator.async_remove_item.side_effect = Exception("Database connection lost")

        with caplog.at_level(logging.ERROR):
            await inventory_service.async_remove_item(basic_service_call)

        assert "Failed to remove item" in caplog.text
        mock_coordinator.async_save_data.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_async_update_item_success(
        self,
        inventory_service: InventoryService,
        update_item_service_call: ServiceCall,
        mock_coordinator: MagicMock,
    ) -> None:
        mock_coordinator.async_get_item.side_effect = [
            {"name": "milk", "quantity": 2},  # existence check
            {"name": "whole_milk", "quantity": 3},  # updated fetch
        ]
        mock_coordinator.async_update_item.return_value = True

        await inventory_service.async_update_item(update_item_service_call)

        mock_coordinator.async_get_item.assert_any_await("kitchen", "milk")
        mock_coordinator.async_update_item.assert_awaited_once()
        args, kwargs = mock_coordinator.async_update_item.call_args
        assert args[0] == "kitchen"
        assert args[1] == "milk"
        assert args[2] == "whole_milk"
        assert kwargs["quantity"] == 3
        assert kwargs["unit"] == "liters"
        assert kwargs["category"] == "dairy"
        assert kwargs["location"] == "fridge"

        mock_coordinator.async_save_data.assert_awaited_once_with("kitchen")

    @pytest.mark.asyncio
    async def test_async_update_item_not_found_logs_warning(
        self,
        inventory_service: InventoryService,
        update_item_service_call: ServiceCall,
        mock_coordinator: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_coordinator.async_get_item.return_value = None

        with caplog.at_level(logging.WARNING):
            await inventory_service.async_update_item(update_item_service_call)

        mock_coordinator.async_get_item.assert_awaited_once_with("kitchen", "milk")
        mock_coordinator.async_update_item.assert_not_awaited()
        mock_coordinator.async_save_data.assert_not_awaited()
        assert "Item not found" in caplog.text

    @pytest.mark.asyncio
    async def test_async_update_item_update_returns_false_logs_error(
        self,
        inventory_service: InventoryService,
        update_item_service_call: ServiceCall,
        mock_coordinator: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_coordinator.async_get_item.return_value = {"name": "milk", "quantity": 2}
        mock_coordinator.async_update_item.return_value = False

        with caplog.at_level(logging.ERROR):
            await inventory_service.async_update_item(update_item_service_call)

        mock_coordinator.async_update_item.assert_awaited_once()
        mock_coordinator.async_save_data.assert_not_awaited()
        assert "failed" in caplog.text.lower()

    @pytest.mark.asyncio
    async def test_async_update_item_exception_logged(
        self,
        inventory_service: InventoryService,
        update_item_service_call: ServiceCall,
        mock_coordinator: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_coordinator.async_get_item.return_value = {"name": "milk", "quantity": 2}
        mock_coordinator.async_update_item.side_effect = Exception("Update failed")

        with caplog.at_level(logging.ERROR):
            await inventory_service.async_update_item(update_item_service_call)

        assert "Failed to update item" in caplog.text
        mock_coordinator.async_save_data.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_async_get_items_returns_sorted_items(
        self,
        inventory_service: InventoryService,
        mock_coordinator: MagicMock,
    ) -> None:
        mock_coordinator.async_list_items.return_value = [
            {"name": "Banana", "quantity": 2, "unit": "pcs"},
            {"name": "apple", "quantity": 1, "unit": "pcs"},
            {"name": "carrot", "quantity": 5, "unit": "pcs"},
        ]

        call = MagicMock(spec=ServiceCall)
        call.data = {"inventory_id": "kitchen"}

        result = await inventory_service.async_get_items(call)
        items = cast(list[dict[str, Any]], result["items"])

        assert [item["name"] for item in items] == ["apple", "Banana", "carrot"]
        mock_coordinator.async_list_items.assert_awaited_once_with("kitchen")

    @pytest.mark.asyncio
    async def test_async_get_items_by_name(
        self,
        inventory_service: InventoryService,
        mock_coordinator: MagicMock,
    ) -> None:
        entry = MagicMock()
        entry.entry_id = "kitchen"
        entry.data = {"name": "My Kitchen"}

        mock_coordinator.async_list_items.return_value = [
            {"name": "Milk", "quantity": 2},
            {"name": "Bread", "quantity": 1},
        ]

        call = MagicMock(spec=ServiceCall)
        call.data = {"inventory_name": "My Kitchen"}

        with patch.object(
            inventory_service.hass.config_entries, "async_entries", return_value=[entry]
        ):
            result = await inventory_service.async_get_items(call)

        items = cast(list[dict[str, Any]], result["items"])
        assert [item["name"] for item in items] == ["Bread", "Milk"]
        mock_coordinator.async_list_items.assert_awaited_once_with("kitchen")

    @pytest.mark.asyncio
    async def test_async_get_items_by_name_not_found(
        self,
        inventory_service: InventoryService,
        hass: MagicMock,
    ) -> None:
        call = MagicMock(spec=ServiceCall)
        call.data = {"inventory_name": "Non-existent Inventory"}

        with (
            patch.object(hass.config_entries, "async_entries", return_value=[]),
            pytest.raises(
                ValueError, match="Inventory with name 'Non-existent Inventory' not found"
            ),
        ):
            await inventory_service.async_get_items(call)

    @pytest.mark.asyncio
    async def test_async_get_items_missing_both_parameters(
        self,
        inventory_service: InventoryService,
    ) -> None:
        call = MagicMock(spec=ServiceCall)
        call.data = {}

        with pytest.raises(
            ValueError, match="Either 'inventory_id' or 'inventory_name' must be provided"
        ):
            await inventory_service.async_get_items(call)

    @pytest.mark.asyncio
    async def test_async_get_items_falls_back_to_repo_when_no_coordinator(
        self,
        inventory_service: InventoryService,
    ) -> None:
        """When no coordinator is registered for an inventory, fall back to the repository."""
        from unittest.mock import AsyncMock

        from custom_components.simple_inventory.const import DOMAIN

        mock_repo = MagicMock()
        mock_repo.list_items_with_details = AsyncMock(
            return_value=[{"name": "Milk", "quantity": 1}, {"name": "Butter", "quantity": 2}]
        )

        # No coordinator registered for this inventory_id
        inventory_service.hass.data[DOMAIN]["coordinators"] = {}

        call = MagicMock(spec=ServiceCall)
        call.data = {"inventory_id": "kitchen"}

        with patch(
            "custom_components.simple_inventory.services.inventory_service.get_repository",
            return_value=mock_repo,
        ):
            result = await inventory_service.async_get_items(call)

        items = cast(list[dict[str, Any]], result["items"])
        assert [item["name"] for item in items] == ["Butter", "Milk"]
        mock_repo.list_items_with_details.assert_awaited_once_with("kitchen")

    @pytest.mark.asyncio
    async def test_async_add_item_forwards_description_fields(
        self,
        inventory_service: InventoryService,
        add_item_service_call: ServiceCall,
        mock_coordinator: MagicMock,
    ) -> None:
        add_item_service_call.data["description"] = "Pantry staple"
        add_item_service_call.data["auto_add_id_to_description_enabled"] = True

        await inventory_service.async_add_item(add_item_service_call)

        _, kwargs = mock_coordinator.async_add_item.call_args
        assert kwargs["description"] == "Pantry staple"
        assert kwargs["auto_add_id_to_description_enabled"] is True
