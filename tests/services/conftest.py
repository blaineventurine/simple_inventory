"""Fixture overrides for service handler tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.simple_inventory.todo_manager import TodoManager

from ..harness import todo_stack  # noqa: F401 - real-stack fixture for the e2e tests


@pytest.fixture
def mock_coordinator(mock_coordinator: MagicMock) -> MagicMock:
    """Shared mock coordinator, returning items shaped like the repository's rows."""
    mock_coordinator.async_get_item = AsyncMock(
        return_value={"name": "milk", "quantity": 5, "auto_add_to_list_quantity": 2}
    )
    return mock_coordinator


@pytest.fixture
def mock_todo_manager(mock_todo_manager: TodoManager) -> TodoManager:
    """Shared mock todo manager plus the unconditional entry removal API."""
    mock_todo_manager.remove_item_entry = AsyncMock(return_value=True)  # type: ignore[method-assign]
    return mock_todo_manager
