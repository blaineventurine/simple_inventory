"""Tests for the Simple Inventory config flow."""

from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
from homeassistant import data_entry_flow
from homeassistant.core import HomeAssistant
from typing_extensions import Self

from custom_components.simple_inventory.config_flow import (
    SimpleInventoryConfigFlow,
    clean_inventory_name,
)


@pytest.fixture
def mock_setup_entry() -> Generator[MagicMock, None, None]:
    """Mock setting up a config entry."""
    with patch(
        "custom_components.simple_inventory.async_setup_entry",
        return_value=True,
    ) as mock_setup:
        yield mock_setup


async def test_user_step_redirects_to_add_inventory(
    hass: HomeAssistant,
) -> None:
    """Test the initial user step redirects to add inventory."""
    flow = SimpleInventoryConfigFlow()
    flow.hass = hass

    result = await flow.async_step_user()

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "add_inventory"


@patch.object(SimpleInventoryConfigFlow, "_async_current_entries")
async def test_add_inventory_step(
    mock_current_entries: MagicMock,
    hass: HomeAssistant,
    mock_setup_entry: MagicMock,
) -> None:
    """Test the add inventory step."""
    flow = SimpleInventoryConfigFlow()
    flow.hass = hass

    mock_current_entries.return_value = []

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


@patch.object(SimpleInventoryConfigFlow, "_async_current_entries")
async def test_add_inventory_duplicate_name(
    mock_current_entries: MagicMock, hass: HomeAssistant
) -> None:
    """Test adding inventory with a duplicate name."""
    flow = SimpleInventoryConfigFlow()
    flow.hass = hass
    existing_entry = MagicMock()
    existing_entry.data = {"name": "Kitchen Fridge"}
    mock_current_entries.return_value = [existing_entry]

    result = await flow.async_step_add_inventory({"name": "Kitchen Fridge"})

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "add_inventory"
    assert result["errors"] == {"name": "name_exists"}


@patch.object(SimpleInventoryConfigFlow, "_async_current_entries")
async def test_add_inventory_with_existing_global_entry(
    mock_current_entries: MagicMock,
    hass: HomeAssistant,
    mock_setup_entry: MagicMock,
) -> None:
    """Test adding inventory when global entry already exists."""
    flow = SimpleInventoryConfigFlow()
    flow.hass = hass

    # Mock existing global entry
    existing_global = MagicMock()
    existing_global.data = {"entry_type": "global"}
    mock_current_entries.return_value = [existing_global]

    result = await flow.async_step_add_inventory(
        {"name": "Garage Fridge", "icon": "mdi:fridge"}
    )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert not result["data"]["create_global"]


async def test_internal_step(hass: HomeAssistant) -> None:
    """Test the internal step for creating global entry."""
    flow = SimpleInventoryConfigFlow()
    flow.hass = hass

    user_input = {"entry_type": "global"}
    result = await flow.async_step_internal(user_input)

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["title"] == "All Items Expiring Soon"
    assert result["data"] == user_input


def test_options_flow_update_logic() -> None:
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


def test_name_exists_excluding_current_logic() -> None:
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
        if (
            entry.entry_id != config_entry.entry_id
            and entry.data.get("name", "").lower() == test_name.lower()
        ):
            name_exists = True
            break

    assert name_exists

    test_name = "New Name"
    name_exists = False
    for entry in entries:
        if (
            entry.entry_id != config_entry.entry_id
            and entry.data.get("name", "").lower() == test_name.lower()
        ):
            name_exists = True
            break

    assert not name_exists


@patch.object(SimpleInventoryConfigFlow, "_async_current_entries")
def test_global_entry_exists(mock_current_entries: MagicMock) -> None:
    """Test checking if global entry exists."""
    flow = SimpleInventoryConfigFlow()

    regular_entry = MagicMock()
    regular_entry.data = {"entry_type": "inventory"}

    mock_current_entries.return_value = [regular_entry]
    assert not flow._global_entry_exists()

    global_entry = MagicMock()
    global_entry.data = {"entry_type": "global"}

    mock_current_entries.return_value = [regular_entry, global_entry]
    assert flow._global_entry_exists()


@patch.object(SimpleInventoryConfigFlow, "_async_current_entries")
async def test_name_exists(mock_current_entries: MagicMock) -> None:
    """Test checking if inventory name exists."""
    flow = SimpleInventoryConfigFlow()

    existing_entry = MagicMock()
    existing_entry.data = {"name": "Kitchen Fridge"}

    mock_current_entries.return_value = [existing_entry]

    # Should return True for existing name (case insensitive)
    assert await flow._async_name_exists("Kitchen Fridge")
    assert await flow._async_name_exists("kitchen fridge")

    # Should return False for non-existing name
    assert not await flow._async_name_exists("Garage Freezer")


class TestCleanInventoryName:
    """Test the clean_inventory_name function."""

    @pytest.fixture
    def mock_hass(self: Self) -> Generator[MagicMock, None, None]:
        """Mock hass for testing."""
        hass = MagicMock()
        hass.config.language = "en"

        async def mock_get_translations(
            hass_obj: HomeAssistant,
            lang: str,
            category: str,
            integrations: set[str],
        ) -> dict[str, str]:
            return {
                "component.simple_inventory.common.inventory_word": "inventory"
            }

        with patch(
            "homeassistant.helpers.translation.async_get_translations",
            side_effect=mock_get_translations,
        ):
            yield hass

    async def test_removes_inventory_word(
        self: Self, mock_hass: HomeAssistant
    ) -> None:
        """Test removing 'inventory' from various positions."""
        assert (
            await clean_inventory_name(mock_hass, "Kitchen Inventory")
            == "Kitchen"
        )
        assert (
            await clean_inventory_name(mock_hass, "Inventory Kitchen")
            == "Kitchen"
        )
        assert (
            await clean_inventory_name(mock_hass, "My Inventory List")
            == "My List"
        )

    async def test_case_insensitive_removal(
        self: Self, mock_hass: HomeAssistant
    ) -> None:
        """Test case-insensitive removal of 'inventory'."""
        assert (
            await clean_inventory_name(mock_hass, "Kitchen INVENTORY")
            == "Kitchen"
        )
        assert (
            await clean_inventory_name(mock_hass, "InVeNtOrY Kitchen")
            == "Kitchen"
        )
        assert (
            await clean_inventory_name(mock_hass, "kitchen inventory")
            == "kitchen"
        )

    async def test_preserves_inventory_if_only_word(
        self: Self, mock_hass: HomeAssistant
    ) -> None:
        """Test that 'inventory' is preserved if it's the only word."""
        assert await clean_inventory_name(mock_hass, "Inventory") == "Inventory"
        assert await clean_inventory_name(mock_hass, "inventory") == "inventory"
        assert (
            await clean_inventory_name(mock_hass, "  INVENTORY  ")
            == "INVENTORY"
        )

    async def test_handles_multiple_spaces(
        self: Self, mock_hass: HomeAssistant
    ) -> None:
        """Test handling of multiple spaces after removal."""
        assert (
            await clean_inventory_name(mock_hass, "Kitchen  Inventory  Items")
            == "Kitchen Items"
        )
        assert (
            await clean_inventory_name(
                mock_hass, "Inventory    Kitchen    Stuff"
            )
            == "Kitchen Stuff"
        )

    async def test_word_boundary_matching(
        self: Self, mock_hass: HomeAssistant
    ) -> None:
        """Test that it only removes complete word 'inventory', not partial matches."""
        assert (
            await clean_inventory_name(mock_hass, "Inventorying Items")
            == "Inventorying Items"
        )
        assert (
            await clean_inventory_name(mock_hass, "MyInventory")
            == "MyInventory"
        )
        assert (
            await clean_inventory_name(mock_hass, "InventoryList")
            == "InventoryList"
        )

    async def test_strips_whitespace(
        self: Self, mock_hass: HomeAssistant
    ) -> None:
        """Test that result is properly trimmed."""
        assert (
            await clean_inventory_name(mock_hass, "  Kitchen Inventory  ")
            == "Kitchen"
        )
        assert (
            await clean_inventory_name(mock_hass, "  Inventory  ")
            == "Inventory"
        )

    async def test_multiple_inventory_words(
        self: Self, mock_hass: HomeAssistant
    ) -> None:
        """Test handling of multiple 'inventory' words."""
        assert (
            await clean_inventory_name(mock_hass, "Inventory Inventory Items")
            == "Items"
        )
        assert (
            await clean_inventory_name(mock_hass, "Kitchen Inventory Inventory")
            == "Kitchen"
        )


@patch.object(SimpleInventoryConfigFlow, "_async_current_entries")
async def test_add_inventory_cleans_name(
    mock_current_entries: MagicMock,
    hass: HomeAssistant,
    mock_setup_entry: MagicMock,
) -> None:
    """Test that inventory name is cleaned when adding."""
    flow = SimpleInventoryConfigFlow()
    flow.hass = hass

    mock_current_entries.return_value = []

    result = await flow.async_step_add_inventory(
        {
            "name": "Kitchen Inventory",
            "icon": "mdi:fridge",
            "description": "Kitchen items",
        }
    )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["title"] == "Kitchen"  # Name should be cleaned
    assert result["data"]["name"] == "Kitchen"  # Data should have cleaned name


@patch.object(SimpleInventoryConfigFlow, "_async_current_entries")
async def test_add_inventory_preserves_inventory_only_name(
    mock_current_entries: MagicMock,
    hass: HomeAssistant,
    mock_setup_entry: MagicMock,
) -> None:
    """Test that 'Inventory' is preserved when it's the only word."""
    flow = SimpleInventoryConfigFlow()
    flow.hass = hass
    mock_current_entries.return_value = []

    result = await flow.async_step_add_inventory(
        {
            "name": "Inventory",
            "icon": "mdi:package",
            "description": "Main inventory",
        }
    )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["title"] == "Inventory"  # Should be preserved
    assert result["data"]["name"] == "Inventory"


@patch.object(SimpleInventoryConfigFlow, "_async_current_entries")
async def test_duplicate_check_uses_cleaned_name(
    mock_current_entries: MagicMock, hass: HomeAssistant
) -> None:
    """Test that duplicate check uses cleaned name."""
    flow = SimpleInventoryConfigFlow()
    flow.hass = hass

    # Existing entry with name "Kitchen"
    existing_entry = MagicMock()
    existing_entry.data = {"name": "Kitchen"}
    mock_current_entries.return_value = [existing_entry]

    # Try to add "Kitchen Inventory" which cleans to "Kitchen"
    result = await flow.async_step_add_inventory({"name": "Kitchen Inventory"})

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {"name": "name_exists"}


async def test_options_flow_cleaning_logic(hass: HomeAssistant) -> None:
    """Test that the options flow would clean names correctly."""
    # Test the cleaning logic directly
    original_name = "Garage Inventory Storage"
    cleaned = await clean_inventory_name(hass, original_name)
    assert cleaned == "Garage Storage"

    # Test that it would be used in the update
    user_input = {
        "name": "Garage Inventory Storage",
        "icon": "mdi:garage",
        "description": "Garage items",
    }

    new_data = {
        "name": await clean_inventory_name(hass, user_input["name"]),
        "icon": user_input.get("icon", "mdi:package-variant"),
        "description": user_input.get("description", ""),
    }

    assert new_data["name"] == "Garage Storage"
    assert new_data["icon"] == "mdi:garage"
    assert new_data["description"] == "Garage items"
