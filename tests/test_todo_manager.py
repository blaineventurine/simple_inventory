"""Tests for TodoManager."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.todo import TodoItem, TodoItemStatus
from typing_extensions import Self

from custom_components.simple_inventory.todo_manager import TodoManager
from custom_components.simple_inventory.types import InventoryItem


class TestTodoManager:
    """Test TodoManager class."""

    @pytest.fixture
    def mock_hass(self: Self) -> MagicMock:
        """Create a mock Home Assistant instance."""
        return MagicMock()

    @pytest.fixture
    def todo_manager(self: Self, mock_hass: MagicMock) -> TodoManager:
        """Create a TodoManager instance."""
        return TodoManager(mock_hass)

    @pytest.fixture
    def sample_todo_items(self: Self) -> list[dict[str, Any]]:
        """Sample todo items for testing."""
        return [
            {"summary": "milk", "status": "needs_action", "uid": "1"},
            {"summary": "bread", "status": "completed", "uid": "2"},
            {"summary": "eggs", "status": "needs_action", "uid": "3"},
            {"summary": "cheese", "status": "completed", "uid": "4"},
        ]

    @pytest.fixture
    def sample_item_data(self: Self) -> InventoryItem:
        """Sample item data for testing."""
        return {
            "auto_add_enabled": True,
            "quantity": 2,
            "auto_add_to_list_quantity": 5,
            "todo_list": "todo.shopping_list",
        }

    def test_init(self: Self, mock_hass: MagicMock) -> None:
        """Test TodoManager initialization."""
        manager = TodoManager(mock_hass)
        assert manager.hass is mock_hass

    @pytest.mark.parametrize(
        "item,expected",
        [
            (
                {"summary": "milk", "status": "needs_action"},
                False,
            ),
            (
                {"summary": "bread", "status": "completed"},
                True,
            ),
            (
                {"summary": "eggs", "status": "needs_action"},
                False,
            ),
            (
                {"summary": "cheese", "status": "completed"},
                True,
            ),
        ],
    )
    def test_is_item_completed(
        self: Self,
        todo_manager: TodoManager,
        item: dict[str, Any],
        expected: bool,
    ) -> None:
        """Test _is_item_completed method."""
        result = todo_manager._is_item_completed(item)
        assert result == expected

    @pytest.mark.asyncio
    async def test_get_incomplete_items_service_success(
        self: Self,
        todo_manager: TodoManager,
        sample_todo_items: list[dict[str, Any]],
    ) -> None:
        """Test _get_incomplete_items with successful service call."""
        with patch.object(
            todo_manager.hass.services,
            "async_call",
            new=AsyncMock(return_value={"todo.shopping_list": {"items": sample_todo_items}}),
        ):
            result = await todo_manager._get_incomplete_items("todo.shopping_list")

            expected_items = [
                {"summary": "milk", "status": "needs_action", "uid": "1"},
                {"summary": "eggs", "status": "needs_action", "uid": "3"},
            ]
            assert result == expected_items

    @pytest.mark.asyncio
    async def test_get_incomplete_items_no_entity(self: Self, todo_manager: TodoManager) -> None:
        """Test _get_incomplete_items when entity doesn't exist."""
        with (
            patch.object(
                todo_manager.hass.services,
                "async_call",
                new=AsyncMock(side_effect=Exception("Service error")),
            ),
            patch.object(todo_manager.hass.states, "get", return_value=None),
        ):

            result = await todo_manager._get_incomplete_items("todo.nonexistent")
            assert result == []

    @pytest.mark.asyncio
    async def test_check_and_add_item_success(
        self: Self, todo_manager: TodoManager, sample_item_data: InventoryItem
    ) -> None:
        """Test check_and_add_item with successful addition."""
        with (
            patch.object(
                todo_manager,
                "_get_incomplete_items",
                new=AsyncMock(return_value=[{"summary": "milk", "status": "needs_action"}]),
            ),
            patch.object(todo_manager.hass.services, "async_call", new=AsyncMock()) as mock_call,
        ):

            result = await todo_manager.check_and_add_item("bread", sample_item_data)

            assert result is True
            mock_call.assert_called_with(
                "todo",
                "add_item",
                {"item": "bread", "entity_id": "todo.shopping_list"},
            )

    @pytest.mark.asyncio
    async def test_check_and_add_item_duplicate(
        self: Self, todo_manager: TodoManager, sample_item_data: InventoryItem
    ) -> None:
        """Test check_and_add_item with duplicate item."""
        with (
            patch.object(
                todo_manager,
                "_get_incomplete_items",
                new=AsyncMock(
                    return_value=[
                        TodoItem(summary="bread", status=TodoItemStatus.NEEDS_ACTION),
                    ]
                ),
            ),
            patch.object(todo_manager.hass.services, "async_call", new=AsyncMock()) as mock_call,
        ):

            result = await todo_manager.check_and_add_item("bread", sample_item_data)

            assert result is False
            mock_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_and_add_item_case_insensitive_duplicate(
        self: Self, todo_manager: TodoManager, sample_item_data: InventoryItem
    ) -> None:
        """Test check_and_add_item with case-insensitive duplicate."""
        with (
            patch.object(
                todo_manager,
                "_get_incomplete_items",
                new=AsyncMock(return_value=[{"summary": "BREAD", "status": "needs_action"}]),
            ),
            patch.object(todo_manager.hass.services, "async_call", new=AsyncMock()) as mock_call,
        ):

            result = await todo_manager.check_and_add_item("bread", sample_item_data)

            assert result is False
            mock_call.assert_not_called()

    @pytest.mark.parametrize(
        "item_data,expected",
        [
            (
                {
                    "auto_add_enabled": False,
                    "quantity": 5,
                    "auto_add_to_list_quantity": 10,
                    "todo_list": "todo.list",
                },
                False,
            ),
            (
                {
                    "auto_add_enabled": True,
                    "quantity": 15,
                    "auto_add_to_list_quantity": 10,
                    "todo_list": "todo.list",
                },
                False,
            ),
            (
                {
                    "auto_add_enabled": True,
                    "quantity": 5,
                    "auto_add_to_list_quantity": 10,
                    "todo_list": "",
                },
                False,
            ),
            (
                {
                    "auto_add_enabled": True,
                    "quantity": 5,
                    "auto_add_to_list_quantity": 10,
                },
                False,
            ),  # no todo_list
        ],
    )
    @pytest.mark.asyncio
    async def test_check_and_add_item_conditions_not_met(
        self: Self,
        todo_manager: TodoManager,
        item_data: InventoryItem,
        expected: bool,
    ) -> None:
        """Test check_and_add_item when conditions are not met."""
        with patch.object(todo_manager.hass.services, "async_call", new=AsyncMock()) as mock_call:
            result = await todo_manager.check_and_add_item("Buy bread", item_data)
            assert result == expected
            mock_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_and_add_item_service_error(
        self: Self, todo_manager: TodoManager, sample_item_data: InventoryItem
    ) -> None:
        """Test check_and_add_item with service error."""
        with (
            patch.object(
                todo_manager,
                "_get_incomplete_items",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(
                todo_manager.hass.services,
                "async_call",
                new=AsyncMock(side_effect=Exception("Service error")),
            ),
        ):

            result = await todo_manager.check_and_add_item("Buy bread", sample_item_data)

            assert result is False

    @pytest.mark.asyncio
    async def test_check_and_add_item_get_items_error(
        self: Self, todo_manager: TodoManager, sample_item_data: InventoryItem
    ) -> None:
        """Test check_and_add_item with get items error."""
        with patch.object(
            todo_manager,
            "_get_incomplete_items",
            new=AsyncMock(side_effect=Exception("Get items error")),
        ):
            result = await todo_manager.check_and_add_item("Buy bread", sample_item_data)

            assert result is False

    @pytest.mark.asyncio
    async def test_integration_complete_workflow(self: Self, todo_manager: TodoManager) -> None:
        """Test complete workflow integration."""
        item_data: InventoryItem = {
            "auto_add_enabled": True,
            "quantity": 2,
            "auto_add_to_list_quantity": 5,
            "todo_list": "todo.shopping_list",
        }

        with patch.object(todo_manager.hass.services, "async_call", new=AsyncMock()) as mock_call:
            mock_call.side_effect = [
                # First call: get_items
                {
                    "todo.shopping_list": {
                        "items": [
                            {"summary": "milk", "status": "needs_action"},
                            {"summary": "sugar", "status": "completed"},
                        ]
                    }
                },
                # Second call: add_item (no return value needed)
                None,
            ]

            result = await todo_manager.check_and_add_item("bread", item_data)

            assert result is True
            assert mock_call.call_count == 2
