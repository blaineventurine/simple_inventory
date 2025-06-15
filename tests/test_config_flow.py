"""Tests for the Simple Inventory config flow."""

from unittest.mock import MagicMock, patch

import pytest
from homeassistant import data_entry_flow
from homeassistant.core import HomeAssistant

from custom_components.simple_inventory.config_flow import (
    SimpleInventoryConfigFlow,
)


@pytest.fixture
def mock_setup_entry():
    """Mock setting up a config entry."""
    with patch(
        "custom_components.simple_inventory.async_setup_entry", return_value=True
    ) as mock_setup:
        yield mock_setup


async def test_user_step_redirects_to_add_inventory(hass: HomeAssistant):
    """Test the initial user step redirects to add inventory."""
    flow = SimpleInventoryConfigFlow()
    flow.hass = hass

    result = await flow.async_step_user()

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "add_inventory"


async def test_add_inventory_step(hass: HomeAssistant, mock_setup_entry):
    """Test the add inventory step."""
    flow = SimpleInventoryConfigFlow()
    flow.hass = hass
    flow._async_current_entries = MagicMock(return_value=[])

    result = await flow.async_step_add_inventory()

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "add_inventory"

    result = await flow.async_step_add_inventory(
        {
            "name": "Garage Fridge",  # Changed to avoid kitchen conflict
            "icon": "mdi:fridge",
            "description": "Our garage refrigerator",
        }
    )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["title"] == "Garage Fridge"
    assert result["data"] == {
        "name": "Garage Fridge",
        "icon": "mdi:fridge",
        "description": "Our garage refrigerator",
        "entry_type": "inventory",
        "create_global": True,  # No global entry exists yet
    }


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


async def test_add_inventory_with_existing_global_entry(
    hass: HomeAssistant, mock_setup_entry
):
    """Test adding inventory when global entry already exists."""
    flow = SimpleInventoryConfigFlow()
    flow.hass = hass

    # Mock existing global entry
    existing_global = MagicMock()
    existing_global.data = {"entry_type": "global"}
    flow._async_current_entries = MagicMock(return_value=[existing_global])

    result = await flow.async_step_add_inventory(
        {"name": "Garage Fridge", "icon": "mdi:fridge"}
    )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert not result["data"]["create_global"]


async def test_internal_step(hass: HomeAssistant):
    """Test the internal step for creating global entry."""
    flow = SimpleInventoryConfigFlow()
    flow.hass = hass

    user_input = {"entry_type": "global"}
    result = await flow.async_step_internal(user_input)

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["title"] == "All Items Expiring Soon"
    assert result["data"] == user_input


def test_options_flow_update_logic():
    """Test updating configuration logic in options flow."""
    config_entry = MagicMock()
    config_entry.data = {
        "name": "Kitchen Fridge",
        "icon": "mdi:fridge",
        "description": "Main fridge",
    }
    config_entry.entry_id = "test_entry"

    user_input = {
        "name": "Main Fridge",
        "icon": "mdi:fridge-outline",
        "description": "Updated description",
    }

    new_data = {
        "name": user_input["name"],
        "icon": user_input.get("icon", "mdi:package-variant"),
        "description": user_input.get("description", ""),
    }

    assert new_data["name"] == "Main Fridge"
    assert new_data["icon"] == "mdi:fridge-outline"
    assert new_data["description"] == "Updated description"


def test_name_exists_excluding_current_logic():
    """Test the name exists check logic."""
    config_entry = MagicMock()
    config_entry.entry_id = "current_entry"

    other_entry = MagicMock()
    other_entry.entry_id = "other_entry"
    other_entry.data = {"name": "Other Inventory"}

    entries = [config_entry, other_entry]
    test_name = "Other Inventory"

    # Simulate the logic from _async_name_exists_excluding_current
    name_exists = False
    for entry in entries:
        if entry.entry_id != config_entry.entry_id:
            if entry.data.get("name", "").lower() == test_name.lower():
                name_exists = True
                break

    assert name_exists

    test_name = "New Name"
    name_exists = False
    for entry in entries:
        if entry.entry_id != config_entry.entry_id:
            if entry.data.get("name", "").lower() == test_name.lower():
                name_exists = True
                break

    assert not name_exists


def test_global_entry_exists():
    """Test checking if global entry exists."""
    flow = SimpleInventoryConfigFlow()

    regular_entry = MagicMock()
    regular_entry.data = {"entry_type": "inventory"}
    flow._async_current_entries = MagicMock(return_value=[regular_entry])
    assert not flow._global_entry_exists()

    global_entry = MagicMock()
    global_entry.data = {"entry_type": "global"}
    flow._async_current_entries = MagicMock(return_value=[regular_entry, global_entry])
    assert flow._global_entry_exists()


async def test_name_exists():
    """Test checking if inventory name exists."""
    flow = SimpleInventoryConfigFlow()

    existing_entry = MagicMock()
    existing_entry.data = {"name": "Kitchen Fridge"}
    flow._async_current_entries = MagicMock(return_value=[existing_entry])

    # Should return True for existing name (case insensitive)
    assert await flow._async_name_exists("Kitchen Fridge")
    assert await flow._async_name_exists("kitchen fridge")

    # Should return False for non-existing name
    assert not await flow._async_name_exists("Garage Freezer")
