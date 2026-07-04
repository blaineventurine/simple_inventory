"""Test configuration and fixtures."""

import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, ServiceCall

from custom_components.simple_inventory.const import DOMAIN
from custom_components.simple_inventory.services import ServiceHandler
from custom_components.simple_inventory.services.base_service import (
    BaseServiceHandler,
)
from custom_components.simple_inventory.services.inventory_service import (
    InventoryService,
)
from custom_components.simple_inventory.services.quantity_service import (
    QuantityService,
)
from custom_components.simple_inventory.todo_manager import TodoManager
from custom_components.simple_inventory.types import InventoryItem

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture
def hass_mock() -> MagicMock:
    """Create a mock Home Assistant instance."""
    hass_mock = MagicMock()
    hass_mock.data = {
        "simple_inventory": {
            "coordinators": {},
            "repository": MagicMock(),
        }
    }

    hass_mock.services = MagicMock()
    hass_mock.services.async_call = AsyncMock()
    hass_mock.states = MagicMock()
    hass_mock.bus = MagicMock()
    hass_mock.bus.async_listen = MagicMock()
    hass_mock.bus.async_fire = MagicMock()

    entity_registry = MagicMock()
    entity_registry.entities = {}
    hass_mock.helpers = MagicMock()
    hass_mock.helpers.entity_registry = MagicMock()
    hass_mock.helpers.entity_registry.async_get = AsyncMock(return_value=entity_registry)
    hass_mock.helpers.utcnow = MagicMock(return_value=datetime.now())

    hass_mock.config_entries = MagicMock()
    hass_mock.config_entries.async_entries = MagicMock(return_value=[])
    hass_mock.config_entries.async_update_entry = AsyncMock()

    hass_mock.states.async_entity_ids = MagicMock(return_value=[])
    hass_mock.states.get = MagicMock(return_value=None)
    hass_mock.states.async_set = MagicMock()

    return hass_mock


@pytest.fixture
def mock_coordinator() -> MagicMock:
    """Create a mock coordinator with common async methods."""
    coordinator = MagicMock()
    coordinator.async_save_data = AsyncMock()

    coordinator.async_add_item = AsyncMock(return_value="item-id")
    coordinator.async_remove_item = AsyncMock(return_value=True)
    coordinator.async_update_item = AsyncMock(return_value=True)
    coordinator.async_get_item = AsyncMock(
        return_value={"quantity": 5, "auto_add_to_list_quantity": 2}
    )
    coordinator.async_list_items = AsyncMock(return_value=[{"name": "milk", "quantity": 5}])

    coordinator.async_increment_item = AsyncMock(return_value=True)
    coordinator.async_decrement_item = AsyncMock(return_value=True)

    coordinator.async_get_inventory_statistics = AsyncMock(
        return_value={
            "total_quantity": 0,
            "total_items": 0,
            "categories": {},
            "locations": {},
            "below_threshold": [],
            "expiring_items": [],
        }
    )
    coordinator.async_get_items_expiring_soon = AsyncMock(return_value=[])

    coordinator.async_add_listener = MagicMock(return_value=lambda: None)

    mock_repo = MagicMock()
    mock_repo.get_item_by_barcode = AsyncMock(return_value=None)
    coordinator.repository = mock_repo

    return coordinator


@pytest.fixture
def mock_todo_manager() -> TodoManager:
    """Create a mock todo manager."""
    todo_manager = MagicMock()
    todo_manager.check_and_add_item = AsyncMock(return_value=True)
    todo_manager.check_and_remove_item = AsyncMock(return_value=True)
    return todo_manager


@pytest.fixture
def todo_manager(hass: HomeAssistant) -> TodoManager:
    """Create a TodoManager instance with mocked hass."""
    return TodoManager(hass)


@pytest.fixture
def base_service_handler(
    hass: HomeAssistant,
) -> BaseServiceHandler:
    """Create a BaseServiceHandler instance."""
    return BaseServiceHandler(hass)


@pytest.fixture
def inventory_service(
    hass: HomeAssistant,
    mock_todo_manager: TodoManager,
    mock_coordinator: MagicMock,
) -> InventoryService:
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault("coordinators", {})
    hass.data[DOMAIN]["coordinators"]["kitchen"] = mock_coordinator
    hass.data[DOMAIN].setdefault("repository", MagicMock())
    return InventoryService(hass, mock_todo_manager)


@pytest.fixture
def quantity_service(
    hass: HomeAssistant,
    mock_todo_manager: TodoManager,
    mock_coordinator: MagicMock,
) -> QuantityService:
    hass.data["simple_inventory"]["coordinators"]["kitchen"] = mock_coordinator
    return QuantityService(hass, mock_todo_manager)


@pytest.fixture
def basic_service_call() -> ServiceCall:
    """Create a basic service call with inventory_id and name."""
    call = MagicMock()
    call.data = {"inventory_id": "kitchen", "name": "milk"}
    return call


@pytest.fixture
def add_item_service_call() -> ServiceCall:
    """Create a service call for adding items."""
    call = MagicMock()
    call.data = {
        "auto_add_enabled": True,
        "auto_add_to_list_quantity": 1,
        "category": "dairy",
        "location": "fridge",
        "expiry_alert_days": 7,
        "expiry_date": "2024-12-31",
        "inventory_id": "kitchen",
        "name": "milk",
        "quantity": 2,
        "todo_list": "todo.shopping",
        "unit": "liters",
    }
    return call


@pytest.fixture
def update_item_service_call() -> ServiceCall:
    """Create a service call for updating items."""
    call = MagicMock()
    call.data = {
        "inventory_id": "kitchen",
        "old_name": "milk",
        "name": "whole_milk",
        "quantity": 3,
        "unit": "liters",
        "category": "dairy",
        "location": "fridge",
    }
    return call


@pytest.fixture
def quantity_service_call() -> ServiceCall:
    """Create a service call for quantity operations."""
    call = MagicMock()
    call.data = {"inventory_id": "kitchen", "name": "milk", "amount": 2}
    return call


@pytest.fixture
def threshold_service_call() -> ServiceCall:
    """Create a service call for setting expiry threshold."""
    call = MagicMock()
    call.data = {"threshold_days": 7}
    return call


@pytest.fixture
def sample_todo_items() -> list[dict]:
    """Sample todo items for testing."""
    return [
        {"summary": "milk", "status": "needs_action", "uid": "1"},
        {"summary": "bread", "status": "completed", "uid": "2"},
        {"summary": "eggs", "status": "needs_action", "uid": "3"},
        {"summary": "cheese", "status": "completed", "uid": "4"},
        {"summary": "butter", "status": "completed", "uid": "5"},
    ]


@pytest.fixture
def sample_item_data() -> InventoryItem:
    """Sample item data for testing."""
    return {
        "auto_add_enabled": True,
        "auto_add_to_list_quantity": 10,
        "quantity": 5,
        "todo_list": "todo.shopping_list",
    }


@pytest.fixture
def sample_inventory_data() -> dict[str, Any]:
    """Sample inventory data for testing (list-of-items shape)."""
    today = datetime.now().date()

    return {
        "kitchen": {
            "items": [
                {
                    "inventory_id": "kitchen_123",
                    "name": "milk",
                    "auto_add_enabled": True,
                    "auto_add_to_list_quantity": 1,
                    "auto_add_id_to_description_enabled": False,
                    "category": "dairy",
                    "location": "fridge",
                    "expiry_alert_days": 7,
                    "expiry_date": (today + timedelta(days=5)).strftime("%Y-%m-%d"),
                    "quantity": 2,
                    "todo_list": "todo.shopping",
                    "unit": "liters",
                    "description": "",
                    "locations": [],
                    "categories": [],
                },
                {
                    "inventory_id": "kitchen_123",
                    "name": "bread",
                    "auto_add_enabled": False,
                    "auto_add_to_list_quantity": 0,
                    "auto_add_id_to_description_enabled": False,
                    "category": "bakery",
                    "location": "pantry",
                    "expiry_alert_days": 0,
                    "expiry_date": (today + timedelta(days=2)).strftime("%Y-%m-%d"),
                    "quantity": 1,
                    "todo_list": "",
                    "unit": "loaf",
                    "description": "",
                    "locations": [],
                    "categories": [],
                },
                {
                    "inventory_id": "kitchen_123",
                    "name": "expired_yogurt",
                    "auto_add_enabled": False,
                    "auto_add_to_list_quantity": 0,
                    "auto_add_id_to_description_enabled": False,
                    "category": "dairy",
                    "location": "fridge",
                    "expiry_alert_days": 7,
                    "expiry_date": (today - timedelta(days=1)).strftime("%Y-%m-%d"),
                    "quantity": 1,
                    "todo_list": "",
                    "unit": "cup",
                    "description": "",
                    "locations": [],
                    "categories": [],
                },
            ]
        },
        "pantry": {
            "items": [
                {
                    "inventory_id": "pantry_123",
                    "name": "rice",
                    "auto_add_enabled": False,
                    "auto_add_to_list_quantity": 0,
                    "auto_add_id_to_description_enabled": False,
                    "category": "grains",
                    "location": "pantry",
                    "expiry_alert_days": 0,
                    "expiry_date": (today + timedelta(days=365)).strftime("%Y-%m-%d"),
                    "quantity": 5,
                    "todo_list": "",
                    "unit": "kg",
                    "description": "",
                    "locations": [],
                    "categories": [],
                }
            ]
        },
    }


@pytest.fixture
def mock_config_entry() -> config_entries.ConfigEntry:
    """Create a mock config entry."""
    config_entry = MagicMock()
    config_entry.entry_id = "test_entry_123"
    config_entry.data = {"name": "Test Inventory", "icon": "mdi:package"}
    config_entry.options = {"expiry_threshold": 7}
    return config_entry


@pytest.fixture
def mock_config_entries(
    mock_config_entry: config_entries.ConfigEntry,
) -> list[config_entries.ConfigEntry]:
    """Create a list of mock config entries."""
    return [mock_config_entry]


# Utility fixtures
@pytest.fixture
def mock_datetime() -> Generator[MagicMock, None, None]:
    """Create a mock datetime for consistent testing."""
    fixed_datetime = datetime(2024, 6, 15, 12, 0, 0)
    with patch("datetime.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_datetime
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        yield mock_dt


@pytest.fixture
def caplog_info(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    """Set caplog to INFO level for testing."""
    caplog.set_level(logging.INFO)
    return caplog


@pytest.fixture
def caplog_debug(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    """Set caplog to DEBUG level for testing."""
    caplog.set_level(logging.DEBUG)
    return caplog


@pytest.fixture
def async_mock() -> AsyncMock:
    """Create a simple AsyncMock for general use."""
    return AsyncMock()


@pytest.fixture
def full_service_setup(
    hass: HomeAssistant,
    mock_coordinator: MagicMock,
    mock_todo_manager: TodoManager,
) -> dict[str, Any]:
    hass.data["simple_inventory"]["coordinators"]["kitchen"] = mock_coordinator

    return {
        "hass": hass,
        "todo_manager": mock_todo_manager,
        "service_handler": ServiceHandler(hass, mock_todo_manager),
        "inventory_service": InventoryService(hass, mock_todo_manager),
        "quantity_service": QuantityService(hass, mock_todo_manager),
    }


@pytest.fixture
def domain() -> str:
    """Return the domain constant."""
    return "simple_inventory"


@pytest.fixture
def coordinator_with_errors(
    mock_coordinator: MagicMock,
) -> MagicMock:
    """Create a coordinator that simulates various error conditions."""
    coordinator = mock_coordinator

    def simulate_save_error() -> None:
        coordinator.async_save_data.side_effect = Exception("Save failed")

    def simulate_get_error() -> None:
        coordinator.get_item.side_effect = Exception("Get failed")

    def simulate_update_error() -> None:
        coordinator.update_item.side_effect = Exception("Update failed")

    coordinator.simulate_save_error = simulate_save_error
    coordinator.simulate_get_error = simulate_get_error
    coordinator.simulate_update_error = simulate_update_error

    return coordinator


@pytest.fixture
def mock_expiry_sensor_state() -> MagicMock:
    """Create a mock expiry sensor state."""
    state = MagicMock()
    state.attributes = {"unique_id": "simple_inventory_expiring_items"}
    return state


@pytest.fixture
def mock_entity_registry_with_expiry_sensor() -> MagicMock:
    """Create a mock entity registry with expiry sensor."""
    entity_registry = MagicMock()
    expiry_entity = MagicMock()
    expiry_entity.entity_id = "sensor.items_expiring_soon"
    expiry_entity.platform = "simple_inventory"
    entity_registry.entities = {"expiry_sensor_key": expiry_entity}

    return entity_registry


@pytest.fixture
def hass_with_expiry_sensor(
    hass: MagicMock,
    mock_config_entries: list[MagicMock],
    mock_expiry_sensor_state: MagicMock,
    mock_entity_registry_with_expiry_sensor: MagicMock,
) -> MagicMock:
    """Enhanced hass fixture with expiry sensor setup."""
    hass.config_entries.async_entries.return_value = mock_config_entries
    hass.states.async_entity_ids.return_value = ["sensor.items_expiring_soon"]
    hass.states.get.return_value = mock_expiry_sensor_state
    hass.helpers.entity_registry.async_get.return_value = mock_entity_registry_with_expiry_sensor

    return hass
