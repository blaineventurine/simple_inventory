"""Test configuration and fixtures."""
from custom_components.simple_inventory.services.quantity_service import QuantityService
from custom_components.simple_inventory.services.inventory_service import InventoryService
from custom_components.simple_inventory.services.base_service import BaseServiceHandler
from custom_components.simple_inventory.todo_manager import TodoManager
import sys
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture
def hass():
    """Create a mock Home Assistant instance."""
    hass_mock = MagicMock()
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
    hass_mock.helpers.entity_registry.async_get = AsyncMock(
        return_value=entity_registry)
    hass_mock.helpers.utcnow = MagicMock(return_value=datetime.now())

    hass_mock.config_entries = MagicMock()
    hass_mock.config_entries.async_entries = MagicMock(return_value=[])
    hass_mock.config_entries.async_update_entry = AsyncMock()

    hass_mock.states.async_entity_ids = MagicMock(return_value=[])
    hass_mock.states.get = MagicMock(return_value=None)
    hass_mock.states.async_set = MagicMock()

    return hass_mock


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator with common methods."""
    coordinator = MagicMock()
    coordinator.async_save_data = AsyncMock()

    # Inventory operations
    coordinator.add_item = MagicMock()
    coordinator.remove_item = MagicMock(return_value=True)
    coordinator.update_item = MagicMock(return_value=True)
    coordinator.get_item = MagicMock(
        return_value={"quantity": 5, "auto_add_to_list_quantity": 2})
    coordinator.get_all_items = MagicMock(return_value={})

    # Quantity operations
    coordinator.increment_item = MagicMock(return_value=True)
    coordinator.decrement_item = MagicMock(return_value=True)

    # Data access
    coordinator.get_data = MagicMock(return_value={"inventories": {}})
    coordinator.last_update_success = True
    coordinator.last_update_time = datetime.now()

    return coordinator


@pytest.fixture
def mock_todo_manager():
    """Create a mock todo manager."""
    todo_manager = MagicMock()
    todo_manager.check_and_add_item = AsyncMock(return_value=True)
    return todo_manager


@pytest.fixture
def todo_manager(hass):
    """Create a TodoManager instance with mocked hass."""
    return TodoManager(hass)


@pytest.fixture
def base_service_handler(hass, mock_coordinator):
    """Create a BaseServiceHandler instance."""
    return BaseServiceHandler(hass, mock_coordinator)


@pytest.fixture
def inventory_service(hass, mock_coordinator):
    """Create an InventoryService instance."""
    return InventoryService(hass, mock_coordinator)


@pytest.fixture
def quantity_service(hass, mock_coordinator, mock_todo_manager):
    """Create a QuantityService instance."""
    return QuantityService(hass, mock_coordinator, mock_todo_manager)


@pytest.fixture
def basic_service_call():
    """Create a basic service call with inventory_id and name."""
    call = MagicMock()
    call.data = {
        "inventory_id": "kitchen",
        "name": "milk"
    }
    return call


@pytest.fixture
def add_item_service_call():
    """Create a service call for adding items."""
    call = MagicMock()
    call.data = {
        "auto_add_enabled": True,
        "auto_add_to_list_quantity": 1,
        "category": "dairy",
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
def update_item_service_call():
    """Create a service call for updating items."""
    call = MagicMock()
    call.data = {
        "inventory_id": "kitchen",
        "old_name": "milk",
        "name": "whole_milk",
        "quantity": 3,
        "unit": "liters",
        "category": "dairy"
    }
    return call


@pytest.fixture
def quantity_service_call():
    """Create a service call for quantity operations."""
    call = MagicMock()
    call.data = {
        "inventory_id": "kitchen",
        "name": "milk",
        "amount": 2
    }
    return call


@pytest.fixture
def threshold_service_call():
    """Create a service call for setting expiry threshold."""
    call = MagicMock()
    call.data = {
        "threshold_days": 7
    }
    return call


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
        "auto_add_to_list_quantity": 10,
        "quantity": 5,
        "todo_list": "todo.shopping_list"
    }


@pytest.fixture
def sample_inventory_data():
    """Sample inventory data for testing."""
    today = datetime.now().date()
    return {
        "kitchen": {
            "items": {
                "milk": {
                    "auto_add_enabled": True,
                    "auto_add_to_list_quantity": 1,
                    "category": "dairy",
                    "expiry_alert_days": 7,
                    "expiry_date": (today + timedelta(days=5)).strftime("%Y-%m-%d"),
                    "quantity": 2,
                    "todo_list": "todo.shopping",
                    "unit": "liters",
                },
                "bread": {
                    "auto_add_enabled": False,
                    "auto_add_to_list_quantity": None,
                    "category": "bakery",
                    "expiry_alert_days": None,
                    "expiry_date": (today + timedelta(days=2)).strftime("%Y-%m-%d"),
                    "quantity": 1,
                    "todo_list": "",
                    "unit": "loaf",
                },
                "expired_yogurt": {
                    "auto_add_enabled": False,
                    "auto_add_to_list_quantity": None,
                    "category": "dairy",
                    "expiry_alert_days": 7,
                    "expiry_date": (today - timedelta(days=1)).strftime("%Y-%m-%d"),
                    "quantity": 1,
                    "todo_list": "",
                    "unit": "cup",
                }
            }
        },
        "pantry": {
            "items": {
                "rice": {
                    "auto_add_enabled": False,
                    "auto_add_to_list_quantity": None,
                    "category": "grains",
                    "expiry_alert_days": None,
                    "expiry_date": (today + timedelta(days=365)).strftime("%Y-%m-%d"),
                    "quantity": 5,
                    "todo_list": "",
                    "unit": "kg",
                }
            }
        }
    }


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry."""
    config_entry = MagicMock()
    config_entry.entry_id = "test_entry_123"
    config_entry.data = {"name": "Test Inventory", "icon": "mdi:package"}
    config_entry.options = {"expiry_threshold": 7}
    return config_entry


@pytest.fixture
def mock_config_entries(mock_config_entry):
    """Create a list of mock config entries."""
    return [mock_config_entry]


@pytest.fixture
def mock_sensor_coordinator(sample_inventory_data):
    """Create a mock coordinator specifically for sensor testing."""
    coordinator = MagicMock()
    coordinator.get_data.return_value = {"inventories": sample_inventory_data}
    coordinator.get_all_items.return_value = sample_inventory_data.get(
        "kitchen", {}).get("items", {})
    coordinator.last_update_success = True
    coordinator.last_update_time = datetime.now()
    coordinator.get_inventory_statistics = MagicMock(return_value={
        "total_quantity": 0,
        "total_items": 0,
        "categories": [],
        "below_threshold": [],
        "expiring_items": []
    })

    def mock_get_items_expiring_soon(inventory_id=None):
        """Mock implementation of get_items_expiring_soon."""
        today = datetime.now().date()
        items = []

        inventories_to_check = {}
        if inventory_id:
            inventories_to_check = {
                inventory_id: sample_inventory_data.get(inventory_id, {})}
        else:
            inventories_to_check = sample_inventory_data

        for inv_id, inventory in inventories_to_check.items():
            for item_name, item_data in inventory.get("items", {}).items():
                expiry_date_str = item_data.get("expiry_date", "")
                if expiry_date_str:
                    expiry_date = datetime.strptime(
                        expiry_date_str, "%Y-%m-%d").date()
                    days_until_expiry = (expiry_date - today).days
                    item_threshold = item_data.get("expiry_alert_days", 7)

                    if item_threshold and days_until_expiry <= item_threshold:
                        items.append({
                            "inventory_id": inv_id,
                            "name": item_name,
                            "expiry_date": expiry_date_str,
                            "days_until_expiry": days_until_expiry,
                            "threshold": item_threshold,
                            **item_data
                        })
        return items

    coordinator.get_items_expiring_soon = MagicMock(
        side_effect=mock_get_items_expiring_soon)
    coordinator.async_add_listener = MagicMock(return_value=MagicMock())

    return coordinator


# Utility fixtures
@pytest.fixture
def mock_datetime():
    """Create a mock datetime for consistent testing."""
    fixed_datetime = datetime(2024, 6, 15, 12, 0, 0)
    with patch('datetime.datetime') as mock_dt:
        mock_dt.now.return_value = fixed_datetime
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        yield mock_dt


@pytest.fixture
def caplog_info(caplog):
    """Set caplog to INFO level for testing."""
    import logging
    caplog.set_level(logging.INFO)
    return caplog


@pytest.fixture
def caplog_debug(caplog):
    """Set caplog to DEBUG level for testing."""
    import logging
    caplog.set_level(logging.DEBUG)
    return caplog


@pytest.fixture
def async_mock():
    """Create a simple AsyncMock for general use."""
    return AsyncMock()


@pytest.fixture
def full_service_setup(hass, mock_coordinator, mock_todo_manager):
    """Create a complete service setup for integration testing."""
    from custom_components.simple_inventory.services import ServiceHandler

    return {
        "hass": hass,
        "coordinator": mock_coordinator,
        "todo_manager": mock_todo_manager,
        "service_handler": ServiceHandler(hass, mock_coordinator, mock_todo_manager),
        "inventory_service": InventoryService(hass, mock_coordinator),
        "quantity_service": QuantityService(hass, mock_coordinator, mock_todo_manager),
    }


@pytest.fixture
def domain():
    """Return the domain constant."""
    return "simple_inventory"


@pytest.fixture
def coordinator_with_errors(mock_coordinator):
    """Create a coordinator that simulates various error conditions."""
    coordinator = mock_coordinator

    def simulate_save_error():
        coordinator.async_save_data.side_effect = Exception("Save failed")

    def simulate_get_error():
        coordinator.get_item.side_effect = Exception("Get failed")

    def simulate_update_error():
        coordinator.update_item.side_effect = Exception("Update failed")

    coordinator.simulate_save_error = simulate_save_error
    coordinator.simulate_get_error = simulate_get_error
    coordinator.simulate_update_error = simulate_update_error

    return coordinator


@pytest.fixture
def mock_expiry_sensor_state():
    """Create a mock expiry sensor state."""
    state = MagicMock()
    state.attributes = {"unique_id": "simple_inventory_expiring_items"}
    return state


@pytest.fixture
def mock_entity_registry_with_expiry_sensor():
    """Create a mock entity registry with expiry sensor."""
    entity_registry = MagicMock()
    expiry_entity = MagicMock()
    expiry_entity.entity_id = "sensor.items_expiring_soon"
    expiry_entity.platform = "simple_inventory"
    entity_registry.entities = {
        "expiry_sensor_key": expiry_entity
    }

    return entity_registry


@pytest.fixture
def hass_with_expiry_sensor(hass, mock_config_entries, mock_expiry_sensor_state, mock_entity_registry_with_expiry_sensor):
    """Enhanced hass fixture with expiry sensor setup."""
    hass.config_entries.async_entries.return_value = mock_config_entries
    hass.states.async_entity_ids.return_value = ["sensor.items_expiring_soon"]
    hass.states.get.return_value = mock_expiry_sensor_state
    hass.helpers.entity_registry.async_get.return_value = mock_entity_registry_with_expiry_sensor

    return hass
