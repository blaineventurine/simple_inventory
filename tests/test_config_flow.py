"""Tests for the Simple Inventory config flow."""

import asyncio
from typing import Any, Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant import data_entry_flow
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (  # type: ignore[import-untyped]
    MockConfigEntry,
)
from typing_extensions import Self

from custom_components.simple_inventory.config_flow import (
    GLOBAL_ENTRY_UNIQUE_ID,
    OptionsFlowHandler,
    SimpleInventoryConfigFlow,
    _async_validate_inventory_name,
    clean_inventory_name,
)
from custom_components.simple_inventory.const import DOMAIN


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

    result = await flow.async_step_add_inventory({"name": "Garage Fridge", "icon": "mdi:fridge"})

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert not result["data"]["create_global"]


@patch.object(SimpleInventoryConfigFlow, "_async_current_entries")
async def test_add_inventory_first_offers_voice_sentences_checkbox(
    mock_current_entries: MagicMock,
    hass: HomeAssistant,
) -> None:
    """The checkbox appears on the first inventory (no global entry yet) in English."""
    flow = SimpleInventoryConfigFlow()
    flow.hass = hass
    hass.config.language = "en"
    mock_current_entries.return_value = []

    result = await flow.async_step_add_inventory()

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    schema = result["data_schema"]
    assert schema is not None
    assert "install_voice_sentences" in schema.schema


@patch.object(SimpleInventoryConfigFlow, "_async_current_entries")
async def test_add_inventory_second_omits_voice_sentences_checkbox(
    mock_current_entries: MagicMock,
    hass: HomeAssistant,
) -> None:
    """The checkbox does not appear once a global entry already exists."""
    flow = SimpleInventoryConfigFlow()
    flow.hass = hass
    hass.config.language = "en"
    existing_global = MagicMock()
    existing_global.data = {"entry_type": "global"}
    mock_current_entries.return_value = [existing_global]

    result = await flow.async_step_add_inventory()

    schema = result["data_schema"]
    assert schema is not None
    assert "install_voice_sentences" not in schema.schema


@patch.object(SimpleInventoryConfigFlow, "_async_current_entries")
async def test_add_inventory_omits_checkbox_for_unbundled_language(
    mock_current_entries: MagicMock,
    hass: HomeAssistant,
) -> None:
    """The checkbox does not appear when no bundled template matches the language."""
    flow = SimpleInventoryConfigFlow()
    flow.hass = hass
    hass.config.language = "xx"
    mock_current_entries.return_value = []

    result = await flow.async_step_add_inventory()

    schema = result["data_schema"]
    assert schema is not None
    assert "install_voice_sentences" not in schema.schema


@patch.object(SimpleInventoryConfigFlow, "_async_current_entries")
async def test_add_inventory_checked_triggers_install(
    mock_current_entries: MagicMock,
    hass: HomeAssistant,
    mock_setup_entry: MagicMock,
) -> None:
    """Checking the box on submit calls async_install_voice_sentences."""
    flow = SimpleInventoryConfigFlow()
    flow.hass = hass
    hass.config.language = "en"
    mock_current_entries.return_value = []

    with patch(
        "custom_components.simple_inventory.config_flow.async_install_voice_sentences",
        new=AsyncMock(return_value=True),
    ) as mock_install:
        result = await flow.async_step_add_inventory(
            {
                "name": "Garage Fridge",
                "icon": "mdi:fridge",
                "description": "",
                "install_voice_sentences": True,
            }
        )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    mock_install.assert_awaited_once_with(hass)


@patch.object(SimpleInventoryConfigFlow, "_async_current_entries")
async def test_add_inventory_unchecked_skips_install(
    mock_current_entries: MagicMock,
    hass: HomeAssistant,
    mock_setup_entry: MagicMock,
) -> None:
    """Leaving the box unchecked (the default) does not trigger an install."""
    flow = SimpleInventoryConfigFlow()
    flow.hass = hass
    hass.config.language = "en"
    mock_current_entries.return_value = []

    with patch(
        "custom_components.simple_inventory.config_flow.async_install_voice_sentences",
        new=AsyncMock(return_value=True),
    ) as mock_install:
        result = await flow.async_step_add_inventory(
            {
                "name": "Garage Fridge",
                "icon": "mdi:fridge",
                "description": "",
                "install_voice_sentences": False,
            }
        )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    mock_install.assert_not_awaited()


async def test_internal_step(hass: HomeAssistant) -> None:
    """Test the internal step for creating global entry."""
    flow = SimpleInventoryConfigFlow()
    flow.hass = hass
    flow.context = {"source": "internal"}

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


def _options_handler(
    hass: HomeAssistant, data: dict[str, Any], entry_id: str = "kitchen_entry"
) -> tuple[OptionsFlowHandler, MockConfigEntry]:
    """An options flow bound to a real entry, as HA's options flow manager binds it."""
    entry = MockConfigEntry(domain=DOMAIN, data=data, entry_id=entry_id, title=data.get("name", ""))
    entry.add_to_hass(hass)
    handler = OptionsFlowHandler()
    handler.hass = hass
    handler.handler = entry.entry_id
    return handler, entry


_GLOBAL_ENTRY_DATA = {"entry_type": "global", "name": "All Items Expiring Soon"}


async def test_options_flow_global_entry_shows_panel_settings_and_voice(
    hass: HomeAssistant,
) -> None:
    """The global entry offers the sidebar panel settings and, when possible, the voice sentences."""
    hass.config.language = "en"
    handler, _ = _options_handler(hass, _GLOBAL_ENTRY_DATA, "global_entry")

    with patch(
        "custom_components.simple_inventory.config_flow.can_offer_voice_sentences",
        return_value=True,
    ):
        result = await handler.async_step_init()

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "global_settings"
    schema = result["data_schema"]
    assert schema is not None
    assert [str(key) for key in schema.schema] == [
        "show_panel",
        "panel_admin_only",
        "install_voice_sentences",
    ]


async def test_options_flow_global_entry_without_voice_still_shows_panel_settings(
    hass: HomeAssistant,
) -> None:
    handler, _ = _options_handler(hass, _GLOBAL_ENTRY_DATA, "global_entry")

    with patch(
        "custom_components.simple_inventory.config_flow.can_offer_voice_sentences",
        return_value=False,
    ):
        result = await handler.async_step_init()

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    schema = result["data_schema"]
    assert schema is not None
    assert [str(key) for key in schema.schema] == ["show_panel", "panel_admin_only"]


async def test_options_flow_global_entry_saves_panel_options(hass: HomeAssistant) -> None:
    handler, _ = _options_handler(hass, _GLOBAL_ENTRY_DATA, "global_entry")

    with (
        patch(
            "custom_components.simple_inventory.config_flow.can_offer_voice_sentences",
            return_value=True,
        ),
        patch(
            "custom_components.simple_inventory.config_flow.async_install_voice_sentences",
            AsyncMock(),
        ) as install,
    ):
        result = await handler.async_step_global_settings(
            {"show_panel": True, "panel_admin_only": True, "install_voice_sentences": True}
        )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"] == {"show_panel": True, "panel_admin_only": True}
    install.assert_awaited_once_with(hass)


async def test_options_flow_global_settings_default_to_saved_options(hass: HomeAssistant) -> None:
    handler, entry = _options_handler(hass, _GLOBAL_ENTRY_DATA, "global_entry")
    hass.config_entries.async_update_entry(
        entry, options={"show_panel": True, "panel_admin_only": False}
    )

    with patch(
        "custom_components.simple_inventory.config_flow.can_offer_voice_sentences",
        return_value=False,
    ):
        result = await handler.async_step_init()

    schema = result["data_schema"]
    assert schema is not None
    defaults = {str(key): key.default() for key in schema.schema}
    assert defaults == {"show_panel": True, "panel_admin_only": False}


async def test_options_flow_omits_checkbox_for_regular_inventory(hass: HomeAssistant) -> None:
    hass.config.language = "en"
    handler, _ = _options_handler(hass, {"entry_type": "inventory", "name": "Kitchen Fridge"})

    result = await handler.async_step_init()

    assert result["step_id"] == "init"
    schema = result["data_schema"]
    assert schema is not None
    assert "install_voice_sentences" not in schema.schema
    assert result["description_placeholders"] == {"current_name": "Kitchen Fridge"}


async def test_options_flow_global_entry_checked_triggers_install(hass: HomeAssistant) -> None:
    """Checking the box calls async_install_voice_sentences and leaves the entry alone."""
    hass.config.language = "en"
    handler, _ = _options_handler(hass, _GLOBAL_ENTRY_DATA, "global_entry")

    with (
        patch(
            "custom_components.simple_inventory.config_flow.async_install_voice_sentences",
            new=AsyncMock(return_value=True),
        ) as mock_install,
        patch.object(hass.config_entries, "async_update_entry") as update_mock,
    ):
        result = await handler.async_step_global_settings({"install_voice_sentences": True})

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    mock_install.assert_awaited_once_with(hass)
    update_mock.assert_not_called()


async def test_options_flow_global_entry_unchecked_skips_install(hass: HomeAssistant) -> None:
    hass.config.language = "en"
    handler, _ = _options_handler(hass, _GLOBAL_ENTRY_DATA, "global_entry")

    with patch(
        "custom_components.simple_inventory.config_flow.async_install_voice_sentences",
        new=AsyncMock(return_value=True),
    ) as mock_install:
        result = await handler.async_step_global_settings({"install_voice_sentences": False})

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    mock_install.assert_not_awaited()


@patch.object(SimpleInventoryConfigFlow, "_async_current_entries")
async def test_add_inventory_preserves_voice_sentences_checkbox_on_error(
    mock_current_entries: MagicMock, hass: HomeAssistant
) -> None:
    hass.config.language = "en"
    existing_entry = MagicMock()
    existing_entry.data = {"name": "Colliding Name"}
    mock_current_entries.return_value = [existing_entry]
    flow = SimpleInventoryConfigFlow()
    flow.hass = hass

    with patch.object(SimpleInventoryConfigFlow, "_global_entry_exists", return_value=False):
        result = await flow.async_step_add_inventory(
            {
                "name": "Colliding Name",
                "icon": "mdi:package-variant",
                "description": "",
                "install_voice_sentences": True,
            }
        )

    assert result["errors"] == {"name": "name_exists"}
    schema = result["data_schema"]
    assert schema is not None
    (marker,) = (key for key in schema.schema if str(key) == "install_voice_sentences")
    assert marker.default() is True


async def test_options_flow_name_check_excludes_current_entry(hass: HomeAssistant) -> None:
    """Keeping the current name is allowed; taking another entry's name is not."""
    handler, entry = _options_handler(hass, {"entry_type": "inventory", "name": "Kitchen"})
    _options_handler(hass, {"entry_type": "inventory", "name": "Pantry"}, "pantry")

    with patch.object(hass.config_entries, "async_update_entry") as update_mock:
        clash = await handler.async_step_init({"name": "pantry"})
        same = await handler.async_step_init({"name": "Kitchen"})

    assert clash["errors"] == {"name": "name_exists"}
    assert same["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    update_mock.assert_called_once()
    assert update_mock.call_args.args == (entry,)


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


async def test_validate_inventory_name(hass: HomeAssistant) -> None:
    """Names are compared case-insensitively against the given entries."""
    existing_entry = MagicMock()
    existing_entry.data = {"name": "Kitchen Fridge"}

    assert await _async_validate_inventory_name(hass, "Kitchen Fridge", [existing_entry]) == (
        "Kitchen Fridge",
        "name_exists",
    )
    assert await _async_validate_inventory_name(hass, "kitchen fridge", [existing_entry]) == (
        "kitchen fridge",
        "name_exists",
    )
    assert await _async_validate_inventory_name(hass, "Garage Freezer", [existing_entry]) == (
        "Garage Freezer",
        None,
    )


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
            return {"component.simple_inventory.common.inventory_word": "inventory"}

        with patch(
            "homeassistant.helpers.translation.async_get_translations",
            side_effect=mock_get_translations,
        ):
            yield hass

    async def test_removes_inventory_word(self: Self, mock_hass: HomeAssistant) -> None:
        """Test removing 'inventory' from various positions."""
        assert await clean_inventory_name(mock_hass, "Kitchen Inventory") == "Kitchen"
        assert await clean_inventory_name(mock_hass, "Inventory Kitchen") == "Kitchen"
        assert await clean_inventory_name(mock_hass, "My Inventory List") == "My List"

    async def test_case_insensitive_removal(self: Self, mock_hass: HomeAssistant) -> None:
        """Test case-insensitive removal of 'inventory'."""
        assert await clean_inventory_name(mock_hass, "Kitchen INVENTORY") == "Kitchen"
        assert await clean_inventory_name(mock_hass, "InVeNtOrY Kitchen") == "Kitchen"
        assert await clean_inventory_name(mock_hass, "kitchen inventory") == "kitchen"

    async def test_preserves_inventory_if_only_word(self: Self, mock_hass: HomeAssistant) -> None:
        """Test that 'inventory' is preserved if it's the only word."""
        assert await clean_inventory_name(mock_hass, "Inventory") == "Inventory"
        assert await clean_inventory_name(mock_hass, "inventory") == "inventory"
        assert await clean_inventory_name(mock_hass, "  INVENTORY  ") == "INVENTORY"

    async def test_handles_multiple_spaces(self: Self, mock_hass: HomeAssistant) -> None:
        """Test handling of multiple spaces after removal."""
        assert await clean_inventory_name(mock_hass, "Kitchen  Inventory  Items") == "Kitchen Items"
        assert (
            await clean_inventory_name(mock_hass, "Inventory    Kitchen    Stuff")
            == "Kitchen Stuff"
        )

    async def test_word_boundary_matching(self: Self, mock_hass: HomeAssistant) -> None:
        """Test that it only removes complete word 'inventory', not partial matches."""
        assert await clean_inventory_name(mock_hass, "Inventorying Items") == "Inventorying Items"
        assert await clean_inventory_name(mock_hass, "MyInventory") == "MyInventory"
        assert await clean_inventory_name(mock_hass, "InventoryList") == "InventoryList"

    async def test_strips_whitespace(self: Self, mock_hass: HomeAssistant) -> None:
        """Test that result is properly trimmed."""
        assert await clean_inventory_name(mock_hass, "  Kitchen Inventory  ") == "Kitchen"
        assert await clean_inventory_name(mock_hass, "  Inventory  ") == "Inventory"

    async def test_multiple_inventory_words(self: Self, mock_hass: HomeAssistant) -> None:
        """Test handling of multiple 'inventory' words."""
        assert await clean_inventory_name(mock_hass, "Inventory Inventory Items") == "Items"
        assert await clean_inventory_name(mock_hass, "Kitchen Inventory Inventory") == "Kitchen"


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


@pytest.mark.parametrize("raw_name", ["   ", "Inventory Inventory", "inventory, inventory"])
@patch.object(SimpleInventoryConfigFlow, "_async_current_entries", return_value=[])
async def test_add_inventory_rejects_name_empty_after_cleaning(
    _mock_current_entries: MagicMock, hass: HomeAssistant, raw_name: str
) -> None:
    flow = SimpleInventoryConfigFlow()
    flow.hass = hass

    result = await flow.async_step_add_inventory({"name": raw_name})

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {"name": "invalid_name"}


@pytest.mark.parametrize("raw_name", ["   ", "Inventory Inventory", "inventory, inventory"])
async def test_options_flow_rejects_name_empty_after_cleaning(
    hass: HomeAssistant, raw_name: str
) -> None:
    handler, _ = _options_handler(hass, {"entry_type": "inventory", "name": "Kitchen"})

    with patch.object(hass.config_entries, "async_update_entry") as update_mock:
        result = await handler.async_step_init({"name": raw_name, "icon": "mdi:fridge"})

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {"name": "invalid_name"}
    update_mock.assert_not_called()


@patch.object(SimpleInventoryConfigFlow, "_async_current_entries")
async def test_add_inventory_does_not_request_global_when_inventories_exist(
    mock_current_entries: MagicMock, hass: HomeAssistant
) -> None:
    """With inventories present but the global entry deleted by the user, adding another
    inventory must not resurrect it."""
    existing_inventory = MagicMock()
    existing_inventory.data = {"name": "Kitchen", "entry_type": "inventory"}
    mock_current_entries.return_value = [existing_inventory]
    flow = SimpleInventoryConfigFlow()
    flow.hass = hass

    result = await flow.async_step_add_inventory({"name": "Garage"})

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"]["create_global"] is False


async def test_options_flow_update_does_not_bypass_reload(hass: HomeAssistant) -> None:
    """The options flow only updates the entry; the update listener reloads it so
    entities, the device and the repository row all pick up the new name/icon."""
    handler, config_entry = _options_handler(
        hass, {"entry_type": "inventory", "name": "Kitchen", "icon": "mdi:fridge"}
    )

    with (
        patch.object(hass.config_entries, "async_entries", return_value=[]),
        patch.object(hass.config_entries, "async_update_entry") as update_mock,
    ):
        result = await handler.async_step_init(
            {"name": "Pantry", "icon": "mdi:cupboard", "description": "Dry goods"}
        )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    update_mock.assert_called_once_with(
        config_entry,
        data={
            "entry_type": "inventory",
            "name": "Pantry",
            "icon": "mdi:cupboard",
            "description": "Dry goods",
        },
        title="Pantry",
    )


_GLOBAL_DATA = {
    "name": "All Items Expiring Soon",
    "icon": "mdi:calendar-alert",
    "description": "Tracks expiring items across all inventories",
    "entry_type": "global",
}


@pytest.fixture
def real_flow_manager(
    hass: HomeAssistant, enable_custom_integrations: None
) -> Generator[None, None, None]:
    """Drive flows through hass.config_entries.flow; created entries are not set up."""
    with (
        patch("homeassistant.config_entries.async_process_deps_reqs", new=AsyncMock()),
        patch.object(hass.config_entries, "async_setup", new=AsyncMock(return_value=True)),
    ):
        yield


async def test_concurrent_internal_flows_create_one_global_entry(
    hass: HomeAssistant, real_flow_manager: None
) -> None:
    """Two entries carrying create_global set up concurrently must not yield two globals."""
    results = await asyncio.gather(
        hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "internal"}, data=dict(_GLOBAL_DATA)
        ),
        hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "internal"}, data=dict(_GLOBAL_DATA)
        ),
    )
    await hass.async_block_till_done()

    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    assert entries[0].unique_id == GLOBAL_ENTRY_UNIQUE_ID
    assert sorted(r["type"] for r in results) == [
        data_entry_flow.FlowResultType.ABORT,
        data_entry_flow.FlowResultType.CREATE_ENTRY,
    ]


async def test_internal_flow_aborts_when_legacy_global_entry_exists(
    hass: HomeAssistant, real_flow_manager: None
) -> None:
    """Global entries created before the unique_id existed have none; still no duplicate."""
    MockConfigEntry(domain=DOMAIN, data=dict(_GLOBAL_DATA), unique_id=None).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "internal"}, data=dict(_GLOBAL_DATA)
    )

    assert result["type"] == data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
