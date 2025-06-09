"""Test configuration and fixtures."""
from custom_components.simple_inventory.todo_manager import TodoManager
import sys
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture
def hass():
    """Create a mock Home Assistant instance."""
    hass_mock = MagicMock()
    hass_mock.services = MagicMock()
    hass_mock.services.async_call = AsyncMock()
    hass_mock.states = MagicMock()
    return hass_mock


@pytest.fixture
def todo_manager(hass):
    """Create a TodoManager instance with mocked hass."""
    return TodoManager(hass)


@pytest.fixture
def sample_todo_items():
    """Sample todo items for testing."""
    return [
        {"summary": "milk", "status": "needs_action"},
        {"summary": "bread", "status": "completed"},
        {"summary": "eggs", "completed": False},
        {"summary": "cheese", "done": True},
        {"summary": "butter", "state": "completed"}
    ]


@pytest.fixture
def sample_item_data():
    """Sample item data for testing."""
    return {
        "auto_add_enabled": True,
        "quantity": 5,
        "threshold": 10,
        "todo_list": "todo.shopping_list"
    }
