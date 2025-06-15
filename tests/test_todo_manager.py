"""Tests for TodoManager."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.simple_inventory.todo_manager import TodoManager


class TestTodoManager:
    def test_init(self, hass):
        manager = TodoManager(hass)
        assert manager.hass is hass

    @pytest.mark.parametrize(
        "item,expected",
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
            ),
        ],
    )
    def test_is_item_completed(self, todo_manager, item, expected):
        result = todo_manager._is_item_completed(item)
        assert result == expected

    @pytest.mark.asyncio
    async def test_get_incomplete_items_service_success(
        self, todo_manager, sample_todo_items
    ):
        todo_manager.hass.services.async_call.return_value = {
            "todo.shopping_list": {"items": sample_todo_items}
        }

        result = await todo_manager._get_incomplete_items("todo.shopping_list")

        expected_items = [
            {"summary": "milk", "status": "needs_action"},
            {"summary": "eggs", "completed": False},
        ]
        assert result == expected_items

    @pytest.mark.asyncio
    async def test_get_incomplete_items_service_fallback(
        self, todo_manager, sample_todo_items
    ):
        todo_manager.hass.services.async_call.side_effect = Exception("Service error")
        mock_state = MagicMock()
        mock_state.attributes = {"items": sample_todo_items}
        todo_manager.hass.states.get.return_value = mock_state

        result = await todo_manager._get_incomplete_items("todo.shopping_list")

        expected_items = [
            {"summary": "milk", "status": "needs_action"},
            {"summary": "eggs", "completed": False},
        ]
        assert result == expected_items

    @pytest.mark.asyncio
    async def test_get_incomplete_items_no_entity(self, todo_manager):
        todo_manager.hass.services.async_call.side_effect = Exception("Service error")
        todo_manager.hass.states.get.return_value = None

        result = await todo_manager._get_incomplete_items("todo.nonexistent")
        assert result == []

    @pytest.mark.asyncio
    async def test_check_and_add_item_success(self, todo_manager, sample_item_data):
        todo_manager._get_incomplete_items = AsyncMock(
            return_value=[{"summary": "milk", "status": "needs_action"}]
        )

        result = await todo_manager.check_and_add_item("bread", sample_item_data)

        assert result is True
        todo_manager.hass.services.async_call.assert_called_with(
            "todo", "add_item", {"item": "bread", "entity_id": "todo.shopping_list"}
        )

    @pytest.mark.asyncio
    async def test_check_and_add_item_duplicate(self, todo_manager, sample_item_data):
        todo_manager._get_incomplete_items = AsyncMock(
            return_value=[{"summary": "bread", "status": "needs_action"}]
        )

        result = await todo_manager.check_and_add_item("bread", sample_item_data)

        assert result is False
        todo_manager.hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_and_add_item_case_insensitive_duplicate(
        self, todo_manager, sample_item_data
    ):
        todo_manager._get_incomplete_items = AsyncMock(
            return_value=[{"summary": "BREAD", "status": "needs_action"}]
        )

        result = await todo_manager.check_and_add_item("bread", sample_item_data)

        assert result is False
        todo_manager.hass.services.async_call.assert_not_called()

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
        self, todo_manager, item_data, expected
    ):
        result = await todo_manager.check_and_add_item("Buy bread", item_data)
        assert result == expected
        todo_manager.hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_and_add_item_service_error(
        self, todo_manager, sample_item_data
    ):
        todo_manager._get_incomplete_items = AsyncMock(return_value=[])
        todo_manager.hass.services.async_call.side_effect = Exception("Service error")

        result = await todo_manager.check_and_add_item("Buy bread", sample_item_data)

        assert result is False

    @pytest.mark.asyncio
    async def test_check_and_add_item_get_items_error(
        self, todo_manager, sample_item_data
    ):
        todo_manager._get_incomplete_items = AsyncMock(
            side_effect=Exception("Get items error")
        )

        result = await todo_manager.check_and_add_item("Buy bread", sample_item_data)

        assert result is False

    @pytest.mark.asyncio
    async def test_integration_complete_workflow(self, todo_manager):
        item_data = {
            "auto_add_enabled": True,
            "quantity": 2,
            "auto_add_to_list_quantity": 5,
            "todo_list": "todo.shopping_list",
        }

        todo_manager.hass.services.async_call.side_effect = [
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
        assert todo_manager.hass.services.async_call.call_count == 2
