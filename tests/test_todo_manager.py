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

    @pytest.fixture
    def valid_item_data(self) -> InventoryItem:
        """Item data with auto-add enabled."""
        return {
            "quantity": 5,
            "auto_add_enabled": True,
            "auto_add_to_list_quantity": 2,
            "todo_list": "todo.shopping_list",
            "unit": "items",
            "category": "groceries",
            "expiry_date": "",
            "expiry_alert_days": 7,
            "location": "",
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
                {"item": "bread (x4)", "entity_id": "todo.shopping_list"},
                blocking=True,
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
                new=AsyncMock(return_value=[{"summary": "BREAD (x4)", "status": "needs_action"}]),
            ),
            patch.object(todo_manager.hass.services, "async_call", new=AsyncMock()) as mock_call,
        ):

            result = await todo_manager.check_and_add_item("bread", sample_item_data)

            assert result is True
            mock_call.assert_called()

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

    @pytest.mark.asyncio
    async def test_auto_add_disabled(
        self, todo_manager: TodoManager, valid_item_data: InventoryItem
    ) -> None:
        """Test when auto_add is disabled, should return False."""
        valid_item_data["auto_add_enabled"] = False

        result = await todo_manager.check_and_remove_item("bread", valid_item_data)

        assert result is False

    @pytest.mark.asyncio
    async def test_no_todo_list(
        self, todo_manager: TodoManager, valid_item_data: InventoryItem
    ) -> None:
        """Test when todo_list is empty, should return False."""
        valid_item_data["todo_list"] = ""

        result = await todo_manager.check_and_remove_item("bread", valid_item_data)

        assert result is False

    @pytest.mark.asyncio
    async def test_no_matching_item_found(
        self, todo_manager: TodoManager, valid_item_data: InventoryItem
    ) -> None:
        """Test when no matching item is found in todo list."""
        with patch.object(
            todo_manager,
            "_find_matching_incomplete_item",
            new=AsyncMock(return_value=None),
        ):
            result = await todo_manager.check_and_remove_item("bread", valid_item_data)

            assert result is False

    @pytest.mark.asyncio
    async def test_remove_item_quantity_satisfied(
        self, todo_manager: TodoManager, valid_item_data: InventoryItem
    ) -> None:
        """Test removing item when quantity is above threshold."""
        # Set quantity high enough that quantity_needed will be <= 0
        valid_item_data["quantity"] = 10  # > auto_add_to_list_quantity (2)
        # quantity_needed = 2 - 10 + 1 = -7 (which is <= 0)

        matching_item = {"summary": "bread (x3)", "uid": "123"}

        with (
            patch.object(
                todo_manager,
                "_find_matching_incomplete_item",
                new=AsyncMock(return_value=matching_item),
            ),
            patch.object(todo_manager, "_remove_todo_item", new=AsyncMock()) as mock_remove,
        ):
            result = await todo_manager.check_and_remove_item("bread", valid_item_data)

            assert result is True
            mock_remove.assert_called_once_with("todo.shopping_list", matching_item)

    @pytest.mark.asyncio
    async def test_update_item_quantity_still_low(
        self, todo_manager: TodoManager, valid_item_data: InventoryItem
    ) -> None:
        """Test updating item when quantity is still below threshold."""
        # Set quantity so quantity_needed > 0
        valid_item_data["quantity"] = 1  # < auto_add_to_list_quantity (2)
        # quantity_needed = 2 - 1 + 1 = 2 (which is > 0)

        matching_item = {"summary": "bread (x3)", "uid": "123"}

        with (
            patch.object(
                todo_manager,
                "_find_matching_incomplete_item",
                new=AsyncMock(return_value=matching_item),
            ),
            patch.object(todo_manager, "_update_todo_item", new=AsyncMock()) as mock_update,
            patch.object(
                todo_manager, "_build_todo_item_name", return_value="bread (x2)"
            ) as mock_build_name,
            patch.object(todo_manager, "_calculate_quantity_needed", return_value=2) as mock_calc,
        ):
            result = await todo_manager.check_and_remove_item("bread", valid_item_data)

            assert result is True
            mock_calc.assert_called_once_with(1, 2)
            mock_build_name.assert_called_once_with("bread", 2)
            mock_update.assert_called_once_with("todo.shopping_list", matching_item, "bread (x2)")

    @pytest.mark.asyncio
    async def test_remove_item_at_threshold(
        self, todo_manager: TodoManager, valid_item_data: InventoryItem
    ) -> None:
        """Test removing item when quantity exactly equals threshold."""
        # quantity = auto_add_to_list_quantity
        valid_item_data["quantity"] = 2
        valid_item_data["auto_add_to_list_quantity"] = 2
        # quantity_needed = 2 - 2 + 1 = 1 (which is > 0, so UPDATE not REMOVE)

        matching_item = {"summary": "bread (x1)", "uid": "123"}

        with (
            patch.object(
                todo_manager,
                "_find_matching_incomplete_item",
                new=AsyncMock(return_value=matching_item),
            ),
            patch.object(todo_manager, "_update_todo_item", new=AsyncMock()) as mock_update,
        ):
            result = await todo_manager.check_and_remove_item("bread", valid_item_data)

            assert result is True
            # Should update, not remove
            mock_update.assert_called_once()

    @pytest.mark.asyncio
    async def test_remove_item_one_above_threshold(
        self, todo_manager: TodoManager, valid_item_data: InventoryItem
    ) -> None:
        """Test removing item when quantity is one above threshold."""
        # quantity = auto_add_to_list_quantity + 1
        valid_item_data["quantity"] = 3
        valid_item_data["auto_add_to_list_quantity"] = 2
        # quantity_needed = 2 - 3 + 1 = 0 (which is <= 0, so REMOVE)

        matching_item = {"summary": "bread", "uid": "123"}

        with (
            patch.object(
                todo_manager,
                "_find_matching_incomplete_item",
                new=AsyncMock(return_value=matching_item),
            ),
            patch.object(todo_manager, "_remove_todo_item", new=AsyncMock()) as mock_remove,
        ):
            result = await todo_manager.check_and_remove_item("bread", valid_item_data)

            assert result is True
            mock_remove.assert_called_once_with("todo.shopping_list", matching_item)

    @pytest.mark.asyncio
    async def test_service_error_during_removal(
        self, todo_manager: TodoManager, valid_item_data: InventoryItem
    ) -> None:
        """Test handling service error during item removal."""
        valid_item_data["quantity"] = 10  # High enough to trigger removal

        matching_item = {"summary": "bread", "uid": "123"}

        with (
            patch.object(
                todo_manager,
                "_find_matching_incomplete_item",
                new=AsyncMock(return_value=matching_item),
            ),
            patch.object(
                todo_manager,
                "_remove_todo_item",
                new=AsyncMock(side_effect=Exception("Service error")),
            ),
        ):
            result = await todo_manager.check_and_remove_item("bread", valid_item_data)

            assert result is False

    @pytest.mark.asyncio
    async def test_service_error_during_update(
        self, todo_manager: TodoManager, valid_item_data: InventoryItem
    ) -> None:
        """Test handling service error during item update."""
        valid_item_data["quantity"] = 1  # Low enough to trigger update

        matching_item = {"summary": "bread (x2)", "uid": "123"}

        with (
            patch.object(
                todo_manager,
                "_find_matching_incomplete_item",
                new=AsyncMock(return_value=matching_item),
            ),
            patch.object(
                todo_manager,
                "_update_todo_item",
                new=AsyncMock(side_effect=Exception("Service error")),
            ),
        ):
            result = await todo_manager.check_and_remove_item("bread", valid_item_data)

            assert result is False

    @pytest.mark.asyncio
    async def test_get_incomplete_items_error(
        self, todo_manager: TodoManager, valid_item_data: InventoryItem
    ) -> None:
        """Test handling error when getting incomplete items."""
        with patch.object(
            todo_manager,
            "_find_matching_incomplete_item",
            new=AsyncMock(side_effect=Exception("Get items error")),
        ):
            result = await todo_manager.check_and_remove_item("bread", valid_item_data)

            assert result is False

    @pytest.mark.asyncio
    async def test_remove_with_no_uid(
        self, todo_manager: TodoManager, valid_item_data: InventoryItem
    ) -> None:
        """Test removing item that has no UID (uses summary instead)."""
        valid_item_data["quantity"] = 10

        matching_item = {"summary": "bread"}  # No UID

        with (
            patch.object(
                todo_manager,
                "_find_matching_incomplete_item",
                new=AsyncMock(return_value=matching_item),
            ),
            patch.object(todo_manager.hass.services, "async_call", new=AsyncMock()) as mock_call,
        ):
            result = await todo_manager.check_and_remove_item("bread", valid_item_data)

            assert result is True
            # Should use summary since no UID
            mock_call.assert_called_once()
            call_args = mock_call.call_args.args[2]
            assert call_args["item"] == "bread"  # Uses summary

    @pytest.mark.asyncio
    async def test_multiple_scenarios_boundary_conditions(self, todo_manager: TodoManager) -> None:
        """Test various boundary conditions for quantity calculations."""
        test_cases = [
            # (quantity, threshold, expected_quantity_needed, should_remove)
            (0, 2, 3, False),  # Way below, update with x3
            (1, 2, 2, False),  # Below, update with x2
            (2, 2, 1, False),  # At threshold, update with x1
            (3, 2, 0, True),  # One above, remove
            (5, 2, -2, True),  # Way above, remove
        ]

        for quantity, threshold, _expected_needed, should_remove in test_cases:
            item_data: InventoryItem = {
                "quantity": quantity,
                "auto_add_enabled": True,
                "auto_add_to_list_quantity": threshold,
                "todo_list": "todo.shopping_list",
                "unit": "",
                "category": "",
                "expiry_date": "",
                "expiry_alert_days": 7,
                "location": "",
            }

            matching_item = {"summary": "test_item", "uid": "123"}

            with (
                patch.object(
                    todo_manager,
                    "_find_matching_incomplete_item",
                    new=AsyncMock(return_value=matching_item),
                ),
                patch.object(todo_manager, "_remove_todo_item", new=AsyncMock()) as mock_remove,
                patch.object(todo_manager, "_update_todo_item", new=AsyncMock()) as mock_update,
            ):
                result = await todo_manager.check_and_remove_item("test_item", item_data)

                assert result is True

                if should_remove:
                    mock_remove.assert_called_once()
                    mock_update.assert_not_called()
                else:
                    mock_update.assert_called_once()
                    mock_remove.assert_not_called()
