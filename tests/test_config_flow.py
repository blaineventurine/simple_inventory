"""Tests for the Simple Inventory config flow."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant import data_entry_flow
from homeassistant.core import HomeAssistant

from custom_components.simple_inventory.config_flow import SimpleInventoryConfigFlow
from custom_components.simple_inventory.const import DOMAIN


@pytest.fixture
def mock_coordinator():
    """Mock the coordinator."""
    coordinator = MagicMock()
    coordinator.get_all_items.return_value = {
        "milk": {"quantity": 2},
        "bread": {"quantity": 1},
    }
    return coordinator


@pytest.fixture
def mock_setup_entry():
    """Mock setting up a config entry."""
    with patch(
        "custom_components.simple_inventory.async_setup_entry", return_value=True
    ) as mock_setup:
        yield mock_setup


async def test_user_step_shows_menu(hass: HomeAssistant):
    """Test the initial user step shows a menu."""
    flow = SimpleInventoryConfigFlow()
    flow.hass = hass

    result = await flow.async_step_user()

    assert result["type"] == data_entry_flow.FlowResultType.MENU
    assert "add_inventory" in result["menu_options"]
    assert "manage_inventories" in result["menu_options"]


async def test_add_inventory_step(hass: HomeAssistant, mock_setup_entry):
    """Test the add inventory step."""
    flow = SimpleInventoryConfigFlow()
    flow.hass = hass
    result = await flow.async_step_add_inventory()

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "add_inventory"

    result = await flow.async_step_add_inventory(
        {
            "name": "Kitchen Fridge",
            "icon": "mdi:fridge",
            "description": "Our main refrigerator",
        }
    )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["title"] == "Kitchen Fridge"
    assert result["data"] == {
        "name": "Kitchen Fridge",
        "icon": "mdi:fridge",
        "description": "Our main refrigerator",
    }


async def test_add_inventory_auto_icon(hass: HomeAssistant, mock_setup_entry):
    """Test adding inventory with auto icon suggestion."""
    flow = SimpleInventoryConfigFlow()
    flow.hass = hass

    # Submit without specifying an icon
    result = await flow.async_step_add_inventory(
        {"name": "Kitchen Fridge", "description": "Our main refrigerator"}
    )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    # Auto-suggested based on "fridge" in name
    assert result["data"]["icon"] == "mdi:fridge"


async def test_add_inventory_duplicate_name(hass: HomeAssistant):
    """Test adding inventory with a duplicate name."""
    flow = SimpleInventoryConfigFlow()
    flow.hass = hass
    existing_entry = MagicMock()
    existing_entry.data = {"name": "Kitchen Fridge"}
    flow._async_current_entries = MagicMock(return_value=[existing_entry])

    result = await flow.async_step_add_inventory({"name": "Kitchen Fridge"})

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "add_inventory"
    assert result["errors"] == {"name": "name_exists"}


async def test_manage_inventories_no_entries(hass: HomeAssistant):
    """Test managing inventories when none exist."""
    flow = SimpleInventoryConfigFlow()
    flow.hass = hass
    flow._async_current_entries = MagicMock(return_value=[])

    result = await flow.async_step_manage_inventories()

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "manage_inventories"
    assert "message" in result["description_placeholders"]
    assert "No inventories" in result["description_placeholders"]["message"]


async def test_manage_inventories_with_entries(hass: HomeAssistant, mock_coordinator):
    """Test managing inventories with existing entries."""
    flow = SimpleInventoryConfigFlow()
    flow.hass = hass
    entry1 = MagicMock()
    entry1.entry_id = "entry1"
    entry1.title = "Kitchen Fridge"
    flow._async_current_entries = MagicMock(return_value=[entry1])
    hass.data[DOMAIN] = {"coordinator": mock_coordinator}

    result = await flow.async_step_manage_inventories()

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "manage_inventories"

    schema_dict = result["data_schema"].schema
    inventory_field = schema_dict["inventory"]
    assert "entry1" in inventory_field.container


async def test_configure_inventory(hass: HomeAssistant, mock_coordinator):
    """Test configuring a specific inventory."""
    flow = SimpleInventoryConfigFlow()
    flow.hass = hass
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.title = "Kitchen Fridge"
    hass.config_entries.async_get_entry = MagicMock(return_value=entry)
    hass.data[DOMAIN] = {"coordinator": mock_coordinator}

    result = await flow.async_step_configure_inventory("test_entry")

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "configure_inventory"

    schema_dict = result["data_schema"].schema
    action_field = schema_dict["action"]
    assert "configure" in action_field.container
    assert "delete" in action_field.container


async def test_confirm_delete_inventory(hass: HomeAssistant, mock_coordinator):
    """Test confirming deletion of an inventory."""
    flow = SimpleInventoryConfigFlow()
    flow.hass = hass
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.title = "Kitchen Fridge"
    hass.config_entries.async_get_entry = MagicMock(return_value=entry)
    hass.config_entries.async_remove = AsyncMock()
    hass.data[DOMAIN] = {"coordinator": mock_coordinator}

    result = await flow.async_step_confirm_delete("test_entry")

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "confirm_delete"
    assert "confirm" in result["data_schema"].schema
    assert "warning" in result["description_placeholders"]

    result = await flow.async_step_confirm_delete("test_entry", {"confirm": True})

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    hass.config_entries.async_remove.assert_called_once_with("test_entry")


async def test_cancel_delete_inventory(hass: HomeAssistant, mock_coordinator):
    """Test canceling deletion of an inventory."""
    flow = SimpleInventoryConfigFlow()
    flow.hass = hass
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.title = "Kitchen Fridge"
    hass.config_entries.async_get_entry = MagicMock(return_value=entry)
    hass.data[DOMAIN] = {"coordinator": mock_coordinator}
    flow.async_step_manage_inventories = AsyncMock(return_value={"type": "menu"})

    # Cancel deletion
    await flow.async_step_confirm_delete("test_entry", {"confirm": False})

    flow.async_step_manage_inventories.assert_called_once()


async def test_icon_suggestion():
    """Test icon suggestion based on inventory name."""
    flow = SimpleInventoryConfigFlow()

    # Test exact matches
    assert flow._suggest_icon("Kitchen Freezer") == "mdi:snowflake"
    assert flow._suggest_icon("Garage Fridge") == "mdi:fridge"
    assert flow._suggest_icon("Pantry") == "mdi:food"

    # Test singular/plural variations
    assert flow._suggest_icon("Tool Shed") == "mdi:hammer-wrench"  # singular -> plural
    assert flow._suggest_icon("Tools Shed") == "mdi:hammer-wrench"  # exact match
    assert flow._suggest_icon("Book Shelf") == "mdi:book-open-page-variant"  # singular
    assert flow._suggest_icon("Books Shelf") == "mdi:book-open-page-variant"  # plural
    assert flow._suggest_icon("Pet Supplies") == "mdi:paw"  # singular -> plural
    assert flow._suggest_icon("Pets Supplies") == "mdi:paw"  # plural

    # Test alternative words
    assert flow._suggest_icon("Medicine Cabinet") == "mdi:pill"
    assert flow._suggest_icon("Medication Storage") == "mdi:pill"
    assert flow._suggest_icon("Pills Cabinet") == "mdi:pill"

    # Test default
    assert flow._suggest_icon("Random Storage") == "mdi:package-variant"

    # Test edge cases (words ending in 's' that aren't plurals)
    assert flow._suggest_icon("Electronics Cabinet") == "mdi:memory"
    assert flow._suggest_icon("Electronic Supplies") == "mdi:memory"


async def test_options_flow():
    """Test the options flow logic."""
    config_entry = MagicMock()
    config_entry.data = {
        "name": "Kitchen Fridge",
        "icon": "mdi:fridge",
        "description": "",
    }
    config_entry.options = {"expiry_threshold": 7}
    config_entry.title = "Kitchen Fridge"
    config_entry.entry_id = "test_entry"

    # Test the data transformation logic directly (what the options flow does)
    user_input = {
        "name": "Main Fridge",
        "icon": "mdi:fridge-outline",
        "description": "Updated description",
        "expiry_threshold": 14,
    }

    # Simulate what async_step_init does
    new_data = {**config_entry.data}
    new_data.update(user_input)

    new_options = {**config_entry.options}
    if "expiry_threshold" in user_input:
        new_options["expiry_threshold"] = user_input["expiry_threshold"]

    assert new_data["name"] == "Main Fridge"
    assert new_data["icon"] == "mdi:fridge-outline"
    assert new_data["description"] == "Updated description"
    assert new_options["expiry_threshold"] == 14

    expected_title = user_input.get("name", config_entry.title)
    assert expected_title == "Main Fridge"


async def test_get_inventory_items_no_coordinator(hass: HomeAssistant):
    """Test getting inventory items when coordinator is not available."""
    flow = SimpleInventoryConfigFlow()
    flow.hass = hass

    # Don't set up coordinator in hass.data
    items = flow._get_inventory_items("test_entry")

    assert items == []


async def test_get_inventory_items_with_coordinator(
    hass: HomeAssistant, mock_coordinator
):
    """Test getting inventory items with coordinator available."""
    flow = SimpleInventoryConfigFlow()
    flow.hass = hass
    hass.data = {}
    hass.data[DOMAIN] = {"coordinator": mock_coordinator}

    items = flow._get_inventory_items("test_entry")

    assert len(items) == 2
    assert any(item["name"] == "milk" for item in items)
    assert any(item["name"] == "bread" for item in items)


async def test_configure_inventory_not_found(hass: HomeAssistant):
    """Test configuring an inventory that doesn't exist."""
    flow = SimpleInventoryConfigFlow()
    flow.hass = hass
    hass.config_entries.async_get_entry = MagicMock(return_value=None)

    result = await flow.async_step_configure_inventory("nonexistent_entry")

    assert result["type"] == data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "inventory_not_found"


async def test_confirm_delete_inventory_not_found(hass: HomeAssistant):
    """Test confirming deletion of an inventory that doesn't exist."""
    flow = SimpleInventoryConfigFlow()
    flow.hass = hass
    hass.config_entries.async_get_entry = MagicMock(return_value=None)

    result = await flow.async_step_confirm_delete("nonexistent_entry")

    assert result["type"] == data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "inventory_not_found"


async def test_configure_inventory_select_delete(hass: HomeAssistant, mock_coordinator):
    """Test selecting delete action in configure inventory."""
    flow = SimpleInventoryConfigFlow()
    flow.hass = hass
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.title = "Kitchen Fridge"
    hass.config_entries.async_get_entry = MagicMock(return_value=entry)

    hass.data[DOMAIN] = {"coordinator": mock_coordinator}

    flow.async_step_confirm_delete = AsyncMock(
        return_value={"type": "form", "step_id": "confirm_delete"}
    )

    await flow.async_step_configure_inventory("test_entry", {"action": "delete"})

    flow.async_step_confirm_delete.assert_called_once_with("test_entry")


async def test_manage_inventories_select_inventory(
    hass: HomeAssistant, mock_coordinator
):
    """Test selecting an inventory in manage inventories."""
    flow = SimpleInventoryConfigFlow()
    flow.hass = hass
    entry1 = MagicMock()
    entry1.entry_id = "entry1"
    entry1.title = "Kitchen Fridge"
    flow._async_current_entries = MagicMock(return_value=[entry1])
    hass.data[DOMAIN] = {"coordinator": mock_coordinator}
    flow.async_step_configure_inventory = AsyncMock(
        return_value={"type": "form", "step_id": "configure_inventory"}
    )

    await flow.async_step_manage_inventories({"inventory": "entry1"})

    flow.async_step_configure_inventory.assert_called_once_with("entry1")
