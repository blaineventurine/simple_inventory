"""Tests for BaseServiceHandler."""

import logging
from typing import cast
from unittest.mock import MagicMock

import pytest
from homeassistant.core import HomeAssistant
from typing_extensions import Self

from custom_components.simple_inventory.services.base_service import (
    BaseServiceHandler,
)
from custom_components.simple_inventory.types import AddItemServiceData


class TestBaseServiceHandler:
    """Test BaseServiceHandler class."""

    def test_init(self: Self, hass: HomeAssistant, mock_coordinator: MagicMock) -> None:
        """Test BaseServiceHandler initialization."""
        from custom_components.simple_inventory.services.base_service import (
            BaseServiceHandler,
        )

        handler = BaseServiceHandler(hass, mock_coordinator)

        assert handler.hass is hass
        assert handler.coordinator is mock_coordinator

    @pytest.mark.asyncio
    async def test_save_and_log_success(
        self: Self,
        base_service_handler: BaseServiceHandler,
        mock_coordinator: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test saving data and logging success."""
        with caplog.at_level(logging.DEBUG):
            await base_service_handler._save_and_log_success("kitchen", "Added item", "milk")

        mock_coordinator.async_save_data.assert_called_once_with("kitchen")

        assert "Added item: milk in inventory: kitchen" in caplog.text
        assert caplog.records[0].levelname == "DEBUG"

    @pytest.mark.asyncio
    async def test_save_and_log_success_with_special_characters(
        self: Self,
        base_service_handler: BaseServiceHandler,
        mock_coordinator: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test saving and logging with special characters in names."""
        with caplog.at_level(logging.DEBUG):
            await base_service_handler._save_and_log_success(
                "my-pantry_01", "Updated item", "café-latte"
            )

        mock_coordinator.async_save_data.assert_called_once_with("my-pantry_01")
        assert "Updated item: café-latte in inventory: my-pantry_01" in caplog.text

    @pytest.mark.asyncio
    async def test_save_and_log_success_coordinator_exception(
        self: Self,
        base_service_handler: BaseServiceHandler,
        mock_coordinator: MagicMock,
    ) -> None:
        """Test handling coordinator exception during save."""
        mock_coordinator.async_save_data.side_effect = Exception("Save failed")

        with pytest.raises(Exception, match="Save failed"):
            await base_service_handler._save_and_log_success("kitchen", "Added item", "milk")

        mock_coordinator.async_save_data.assert_called_once_with("kitchen")

    def test_log_item_not_found(
        self: Self,
        base_service_handler: BaseServiceHandler,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test logging when item is not found."""
        with caplog.at_level(logging.WARNING):
            base_service_handler._log_item_not_found("Remove item", "milk", "kitchen")

        assert "Remove item failed - Item not found: milk in inventory: kitchen" in caplog.text
        assert caplog.records[0].levelname == "WARNING"

    def test_log_operation_failed(
        self: Self,
        base_service_handler: BaseServiceHandler,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test logging when operation fails."""
        with caplog.at_level(logging.ERROR):
            base_service_handler._log_operation_failed("Update item", "milk", "kitchen")

        assert "Update item failed for item: milk in inventory: kitchen" in caplog.text
        assert caplog.records[0].levelname == "ERROR"

    def test_extract_item_kwargs_basic(
        self: Self, base_service_handler: BaseServiceHandler
    ) -> None:
        """Test extracting item kwargs with basic data."""
        data = cast(
            AddItemServiceData,
            {
                "inventory_id": "kitchen",
                "name": "milk",
                "quantity": 2,
                "unit": "liters",
                "category": "dairy",
            },
        )
        exclude_keys = ["inventory_id", "name"]

        result = base_service_handler._extract_item_kwargs(data, exclude_keys)

        expected = {"quantity": 2, "unit": "liters", "category": "dairy"}
        assert result == expected

    def test_extract_item_kwargs_empty_exclude(
        self: Self, base_service_handler: BaseServiceHandler
    ) -> None:
        """Test extracting kwargs with empty exclude list."""
        data = cast(
            AddItemServiceData,
            {"inventory_id": "kitchen", "name": "milk", "quantity": 2},
        )
        exclude_keys: list[str] = []

        result = base_service_handler._extract_item_kwargs(data, exclude_keys)

        assert result == data

    def test_extract_item_kwargs_all_excluded(
        self: Self, base_service_handler: BaseServiceHandler
    ) -> None:
        """Test extracting kwargs when all keys are excluded."""
        data = cast(AddItemServiceData, {"inventory_id": "kitchen", "name": "milk"})
        exclude_keys = ["inventory_id", "name"]

        result = base_service_handler._extract_item_kwargs(data, exclude_keys)

        assert result == {}

    def test_get_inventory_and_name_basic(
        self: Self,
        base_service_handler: BaseServiceHandler,
        basic_service_call: MagicMock,
    ) -> None:
        """Test extracting inventory ID and name from service call."""
        inventory_id, name = base_service_handler._get_inventory_and_name(basic_service_call)

        assert inventory_id == "kitchen"
        assert name == "milk"

    def test_get_inventory_and_name_missing_inventory_id(
        self: Self, base_service_handler: BaseServiceHandler
    ) -> None:
        """Test extracting when inventory_id is missing."""
        call = MagicMock()
        call.data = {"name": "milk"}

        with pytest.raises(KeyError, match="inventory_id"):
            base_service_handler._get_inventory_and_name(call)

    def test_get_inventory_and_name_missing_name(
        self: Self, base_service_handler: BaseServiceHandler
    ) -> None:
        """Test extracting when name is missing."""
        call = MagicMock()
        call.data = {"inventory_id": "kitchen"}

        with pytest.raises(KeyError, match="name"):
            base_service_handler._get_inventory_and_name(call)

    @pytest.mark.asyncio
    async def test_concurrent_save_operations(
        self: Self,
        base_service_handler: BaseServiceHandler,
        mock_coordinator: MagicMock,
    ) -> None:
        """Test concurrent save operations."""
        import asyncio

        # Create multiple concurrent save operations
        tasks = [
            base_service_handler._save_and_log_success(f"inventory_{i}", "Operation", f"item_{i}")
            for i in range(3)
        ]

        await asyncio.gather(*tasks)

        # Verify all coordinator calls were made
        assert mock_coordinator.async_save_data.call_count == 3

    def test_inheritance_capability(
        self: Self, hass: HomeAssistant, mock_coordinator: MagicMock
    ) -> None:
        """Test that BaseServiceHandler can be inherited properly."""
        from custom_components.simple_inventory.services.base_service import (
            BaseServiceHandler,
        )

        class TestChildHandler(BaseServiceHandler):
            def test_method(self: Self) -> str:
                return "child method"

        child_handler = TestChildHandler(hass, mock_coordinator)

        assert hasattr(child_handler, "_save_and_log_success")
        assert hasattr(child_handler, "_extract_item_kwargs")
        assert child_handler.hass is hass
        assert child_handler.coordinator is mock_coordinator
        assert child_handler.test_method() == "child method"
