"""Tests for the Simple Inventory integration initialization."""

from typing import Any
from unittest.mock import ANY, AsyncMock, MagicMock, call, patch

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from typing_extensions import Self

from custom_components.simple_inventory import (
    PLATFORMS,
    async_setup,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.simple_inventory.const import (
    DOMAIN,
    SERVICE_ADD_ITEM,
    SERVICE_DECREMENT_ITEM,
    SERVICE_INCREMENT_ITEM,
    SERVICE_REMOVE_ITEM,
    SERVICE_UPDATE_ITEM,
)


class TestSimpleInventoryInit:
    """Test Simple Inventory integration initialization."""

    @pytest.fixture
    def mock_config_entry(self: Self) -> MagicMock:
        """Create a mock config entry."""
        entry = MagicMock(spec=ConfigEntry)
        entry.entry_id = "test_entry_123"
        entry.data = {"name": "Test Inventory", "icon": "mdi:package"}
        return entry

    @pytest.fixture
    def mock_config_entry_2(self: Self) -> MagicMock:
        """Create a second mock config entry."""
        entry = MagicMock(spec=ConfigEntry)
        entry.entry_id = "test_entry_456"
        entry.data = {"name": "Second Inventory", "icon": "mdi:fridge"}
        return entry

    @pytest.fixture
    def mock_hass(self: Self) -> MagicMock:
        """Create a mock Home Assistant instance."""
        hass = MagicMock(spec=HomeAssistant)
        hass.data = {}
        hass.services = MagicMock()
        hass.services.async_register = MagicMock()
        hass.services.async_remove = MagicMock()
        hass.config_entries = MagicMock()
        hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)
        hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
        hass.config_entries.async_entries = MagicMock(return_value=[])
        return hass

    @pytest.mark.asyncio
    async def test_async_setup_entry_first_entry(
        self: Self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """Test setting up the first config entry."""
        with (
            patch(
                "custom_components.simple_inventory.SimpleInventoryCoordinator"
            ) as mock_coord_class,
            patch("custom_components.simple_inventory.TodoManager") as mock_todo_class,
            patch("custom_components.simple_inventory.ServiceHandler") as mock_service_class,
        ):

            mock_coordinator = MagicMock()
            mock_coordinator.async_load_data = AsyncMock()
            mock_coord_class.return_value = mock_coordinator

            mock_todo_manager = MagicMock()
            mock_todo_class.return_value = mock_todo_manager

            mock_service_handler = MagicMock()
            mock_service_handler.async_add_item = AsyncMock()
            mock_service_handler.async_update_item = AsyncMock()
            mock_service_handler.async_remove_item = AsyncMock()
            mock_service_handler.async_increment_item = AsyncMock()
            mock_service_handler.async_decrement_item = AsyncMock()
            mock_service_class.return_value = mock_service_handler

            result = await async_setup_entry(mock_hass, mock_config_entry)

            assert result is True
            assert DOMAIN in mock_hass.data
            assert "coordinator" in mock_hass.data[DOMAIN]
            assert "todo_manager" in mock_hass.data[DOMAIN]
            assert mock_config_entry.entry_id in mock_hass.data[DOMAIN]

            mock_coord_class.assert_called_once_with(mock_hass)
            mock_coordinator.async_load_data.assert_called_once()
            mock_todo_class.assert_called_once_with(mock_hass)
            mock_service_class.assert_called_once_with(
                mock_hass, mock_coordinator, mock_todo_manager
            )

            expected_service_calls = [
                call(
                    DOMAIN,
                    SERVICE_UPDATE_ITEM,
                    mock_service_handler.async_update_item,
                    schema=ANY,
                ),
                call(
                    DOMAIN,
                    SERVICE_ADD_ITEM,
                    mock_service_handler.async_add_item,
                    schema=ANY,
                ),
                call(
                    DOMAIN,
                    SERVICE_REMOVE_ITEM,
                    mock_service_handler.async_remove_item,
                    schema=ANY,
                ),
                call(
                    DOMAIN,
                    SERVICE_INCREMENT_ITEM,
                    mock_service_handler.async_increment_item,
                    schema=ANY,
                ),
                call(
                    DOMAIN,
                    SERVICE_DECREMENT_ITEM,
                    mock_service_handler.async_decrement_item,
                    schema=ANY,
                ),
            ]
            mock_hass.services.async_register.assert_has_calls(
                expected_service_calls, any_order=True
            )
            assert mock_hass.services.async_register.call_count == 5

            entry_data = mock_hass.data[DOMAIN][mock_config_entry.entry_id]
            assert entry_data["coordinator"] is mock_coordinator
            assert entry_data["todo_manager"] is mock_todo_manager
            assert entry_data["config"] == mock_config_entry.data

            mock_hass.config_entries.async_forward_entry_setups.assert_called_once_with(
                mock_config_entry, PLATFORMS
            )

    @pytest.mark.asyncio
    async def test_async_setup_entry_second_entry(
        self: Self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_config_entry_2: MagicMock,
    ) -> None:
        """Test setting up a second config entry when coordinator already exists."""
        mock_coordinator = MagicMock()
        mock_todo_manager = MagicMock()

        mock_hass.data[DOMAIN] = {
            "coordinator": mock_coordinator,
            "todo_manager": mock_todo_manager,
            mock_config_entry.entry_id: {
                "coordinator": mock_coordinator,
                "todo_manager": mock_todo_manager,
                "config": mock_config_entry.data,
            },
        }

        with (
            patch(
                "custom_components.simple_inventory.SimpleInventoryCoordinator"
            ) as mock_coord_class,
            patch("custom_components.simple_inventory.TodoManager") as mock_todo_class,
            patch("custom_components.simple_inventory.ServiceHandler") as mock_service_class,
        ):

            result = await async_setup_entry(mock_hass, mock_config_entry_2)

            assert result is True

            mock_coord_class.assert_not_called()
            mock_todo_class.assert_not_called()
            mock_service_class.assert_not_called()

            mock_hass.services.async_register.assert_not_called()

            assert mock_config_entry_2.entry_id in mock_hass.data[DOMAIN]
            entry_data = mock_hass.data[DOMAIN][mock_config_entry_2.entry_id]
            assert entry_data["coordinator"] is mock_coordinator
            assert entry_data["todo_manager"] is mock_todo_manager
            assert entry_data["config"] == mock_config_entry_2.data

            mock_hass.config_entries.async_forward_entry_setups.assert_called_once_with(
                mock_config_entry_2, PLATFORMS
            )

    @pytest.mark.asyncio
    async def test_async_setup_entry_data_loading_failure(
        self: Self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """Test handling data loading failure during setup."""
        with (
            patch(
                "custom_components.simple_inventory.SimpleInventoryCoordinator"
            ) as mock_coord_class,
            patch("custom_components.simple_inventory.TodoManager") as mock_todo_class,
            patch("custom_components.simple_inventory.ServiceHandler") as mock_service_class,
        ):

            mock_coordinator = MagicMock()
            mock_coordinator.async_load_data = AsyncMock(side_effect=Exception("Load failed"))
            mock_coord_class.return_value = mock_coordinator

            mock_todo_manager = MagicMock()
            mock_todo_class.return_value = mock_todo_manager

            mock_service_handler = MagicMock()
            mock_service_class.return_value = mock_service_handler

            with pytest.raises(Exception, match="Load failed"):
                await async_setup_entry(mock_hass, mock_config_entry)

            mock_coord_class.assert_called_once_with(mock_hass)
            mock_coordinator.async_load_data.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_setup_entry_platform_setup_failure(
        self: Self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """Test handling platform setup failure."""
        with (
            patch(
                "custom_components.simple_inventory.SimpleInventoryCoordinator"
            ) as mock_coord_class,
            patch("custom_components.simple_inventory.TodoManager") as mock_todo_class,
            patch("custom_components.simple_inventory.ServiceHandler") as mock_service_class,
        ):

            mock_coordinator = MagicMock()
            mock_coordinator.async_load_data = AsyncMock()
            mock_coord_class.return_value = mock_coordinator
            mock_todo_manager = MagicMock()
            mock_todo_class.return_value = mock_todo_manager
            mock_service_handler = MagicMock()
            mock_service_class.return_value = mock_service_handler

            mock_hass.config_entries.async_forward_entry_setups.side_effect = Exception(
                "Platform setup failed"
            )

            with pytest.raises(Exception, match="Platform setup failed"):
                await async_setup_entry(mock_hass, mock_config_entry)

    @pytest.mark.asyncio
    async def test_async_unload_entry_with_remaining_entries(
        self: Self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """Test unloading an entry when other entries remain."""
        mock_coordinator = MagicMock()
        mock_todo_manager = MagicMock()

        mock_hass.data[DOMAIN] = {
            "coordinator": mock_coordinator,
            "todo_manager": mock_todo_manager,
            mock_config_entry.entry_id: {"coordinator": mock_coordinator},
            "entry_2": {"coordinator": mock_coordinator},
        }

        result = await async_unload_entry(mock_hass, mock_config_entry)

        assert result is True

        mock_hass.config_entries.async_unload_platforms.assert_called_once_with(
            mock_config_entry, PLATFORMS
        )

        assert mock_config_entry.entry_id not in mock_hass.data[DOMAIN]
        assert "coordinator" in mock_hass.data[DOMAIN]
        assert "todo_manager" in mock_hass.data[DOMAIN]

        mock_hass.services.async_remove.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_unload_entry_last_entry(
        self: Self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """Test unloading the last entry."""
        mock_coordinator = MagicMock()
        mock_todo_manager = MagicMock()

        mock_hass.data[DOMAIN] = {
            "coordinator": mock_coordinator,
            "todo_manager": mock_todo_manager,
            mock_config_entry.entry_id: {"coordinator": mock_coordinator},
        }

        result = await async_unload_entry(mock_hass, mock_config_entry)

        assert result is True

        mock_hass.config_entries.async_unload_platforms.assert_called_once_with(
            mock_config_entry, PLATFORMS
        )

        expected_service_removals = [
            call(DOMAIN, SERVICE_ADD_ITEM),
            call(DOMAIN, SERVICE_DECREMENT_ITEM),
            call(DOMAIN, SERVICE_INCREMENT_ITEM),
            call(DOMAIN, SERVICE_REMOVE_ITEM),
            call(DOMAIN, SERVICE_UPDATE_ITEM),
        ]
        mock_hass.services.async_remove.assert_has_calls(expected_service_removals, any_order=True)
        assert mock_hass.services.async_remove.call_count == 5

        assert DOMAIN not in mock_hass.data

    @pytest.mark.asyncio
    async def test_async_unload_entry_platform_unload_failure(
        self: Self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """Test handling platform unload failure."""
        mock_hass.data[DOMAIN] = {
            "coordinator": MagicMock(),
            "todo_manager": MagicMock(),
            mock_config_entry.entry_id: {"coordinator": MagicMock()},
        }

        mock_hass.config_entries.async_unload_platforms.return_value = False

        result = await async_unload_entry(mock_hass, mock_config_entry)

        assert result is False
        assert mock_config_entry.entry_id in mock_hass.data[DOMAIN]

        mock_hass.services.async_remove.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_unload_entry_empty_domain_data(
        self: Self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """Test unloading when domain has no entry data."""
        mock_hass.data[DOMAIN] = {
            "coordinator": MagicMock(),
            "todo_manager": MagicMock(),
            mock_config_entry.entry_id: {"coordinator": MagicMock()},
        }

        result = await async_unload_entry(mock_hass, mock_config_entry)

        assert result is True

        mock_hass.config_entries.async_unload_platforms.assert_called_once()

        assert mock_hass.services.async_remove.call_count == 5
        assert DOMAIN not in mock_hass.data

    @pytest.mark.asyncio
    async def test_async_setup_legacy_yaml(self: Self, mock_hass: MagicMock) -> None:
        """Test legacy YAML setup."""
        config: dict[str, Any] = {"simple_inventory": {}}

        result = await async_setup(mock_hass, config)

        # Should always return True for legacy support
        assert result is True

    @pytest.mark.asyncio
    async def test_service_registration_schemas(
        self: Self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """Test that services are registered with correct schemas."""
        with (
            patch(
                "custom_components.simple_inventory.SimpleInventoryCoordinator"
            ) as mock_coord_class,
            patch("custom_components.simple_inventory.TodoManager") as mock_todo_class,
            patch("custom_components.simple_inventory.ServiceHandler") as mock_service_class,
            patch("custom_components.simple_inventory.ADD_ITEM_SCHEMA"),
            patch("custom_components.simple_inventory.UPDATE_ITEM_SCHEMA"),
            patch("custom_components.simple_inventory.REMOVE_ITEM_SCHEMA"),
            patch("custom_components.simple_inventory.QUANTITY_UPDATE_SCHEMA"),
        ):

            mock_coordinator = MagicMock()
            mock_coordinator.async_load_data = AsyncMock()
            mock_coord_class.return_value = mock_coordinator

            mock_todo_manager = MagicMock()
            mock_todo_class.return_value = mock_todo_manager

            mock_service_handler = MagicMock()
            mock_service_class.return_value = mock_service_handler

            result = await async_setup_entry(mock_hass, mock_config_entry)

            assert result is True

            service_calls = mock_hass.services.async_register.call_args_list
            service_registrations = {call[0][1]: call[1]["schema"] for call in service_calls}

            assert SERVICE_ADD_ITEM in service_registrations
            assert SERVICE_UPDATE_ITEM in service_registrations
            assert SERVICE_REMOVE_ITEM in service_registrations
            assert SERVICE_INCREMENT_ITEM in service_registrations
            assert SERVICE_DECREMENT_ITEM in service_registrations

    @pytest.mark.asyncio
    async def test_entry_data_structure(
        self: Self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """Test that entry data is stored with correct structure."""
        with (
            patch(
                "custom_components.simple_inventory.SimpleInventoryCoordinator"
            ) as mock_coord_class,
            patch("custom_components.simple_inventory.TodoManager") as mock_todo_class,
            patch("custom_components.simple_inventory.ServiceHandler") as mock_service_class,
        ):

            mock_coordinator = MagicMock()
            mock_coordinator.async_load_data = AsyncMock()
            mock_coord_class.return_value = mock_coordinator
            mock_todo_manager = MagicMock()
            mock_todo_class.return_value = mock_todo_manager
            mock_service_handler = MagicMock()
            mock_service_class.return_value = mock_service_handler

            await async_setup_entry(mock_hass, mock_config_entry)

            entry_data = mock_hass.data[DOMAIN][mock_config_entry.entry_id]

            assert "coordinator" in entry_data
            assert "todo_manager" in entry_data
            assert "config" in entry_data

            assert entry_data["coordinator"] is mock_coordinator
            assert entry_data["todo_manager"] is mock_todo_manager
            assert entry_data["config"] == mock_config_entry.data

    @pytest.mark.asyncio
    async def test_domain_data_persistence_across_entries(
        self: Self,
        mock_hass: MagicMock,
        mock_config_entry: MagicMock,
        mock_config_entry_2: MagicMock,
    ) -> None:
        """Test that domain-level data persists across multiple entries."""
        with (
            patch(
                "custom_components.simple_inventory.SimpleInventoryCoordinator"
            ) as mock_coord_class,
            patch("custom_components.simple_inventory.TodoManager") as mock_todo_class,
            patch("custom_components.simple_inventory.ServiceHandler") as mock_service_class,
        ):

            mock_coordinator = MagicMock()
            mock_coordinator.async_load_data = AsyncMock()
            mock_coord_class.return_value = mock_coordinator
            mock_todo_manager = MagicMock()
            mock_todo_class.return_value = mock_todo_manager
            mock_service_handler = MagicMock()
            mock_service_class.return_value = mock_service_handler

            await async_setup_entry(mock_hass, mock_config_entry)

            first_coordinator = mock_hass.data[DOMAIN]["coordinator"]
            first_todo_manager = mock_hass.data[DOMAIN]["todo_manager"]

            await async_setup_entry(mock_hass, mock_config_entry_2)

            assert mock_hass.data[DOMAIN]["coordinator"] is first_coordinator
            assert mock_hass.data[DOMAIN]["todo_manager"] is first_todo_manager

            entry1_data = mock_hass.data[DOMAIN][mock_config_entry.entry_id]
            entry2_data = mock_hass.data[DOMAIN][mock_config_entry_2.entry_id]

            assert entry1_data["coordinator"] is entry2_data["coordinator"]
            assert entry1_data["todo_manager"] is entry2_data["todo_manager"]

    @pytest.mark.asyncio
    async def test_async_setup_entry_creates_global_when_needed(
        self: Self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """Test that global entry is created when create_global is True and no global exists."""
        mock_config_entry.data = {
            "name": "Test Inventory",
            "icon": "mdi:package",
            "create_global": True,
        }

        # Mock no existing global entries
        mock_hass.config_entries.async_entries.return_value = []

        with (
            patch(
                "custom_components.simple_inventory.SimpleInventoryCoordinator"
            ) as mock_coord_class,
            patch("custom_components.simple_inventory.TodoManager") as mock_todo_class,
            patch("custom_components.simple_inventory.ServiceHandler") as mock_service_class,
            patch(
                "custom_components.simple_inventory._create_global_entry", new_callable=AsyncMock
            ) as mock_create_global,
        ):
            mock_coordinator = MagicMock()
            mock_coordinator.async_load_data = AsyncMock()
            mock_coord_class.return_value = mock_coordinator
            mock_todo_class.return_value = MagicMock()
            mock_service_class.return_value = MagicMock()

            result = await async_setup_entry(mock_hass, mock_config_entry)

            assert result is True
            mock_create_global.assert_called_once_with(mock_hass)

    @pytest.mark.asyncio
    async def test_async_setup_entry_skips_global_when_exists(
        self: Self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """Test that global entry is not created when create_global is True but global already exists."""
        mock_config_entry.data = {
            "name": "Test Inventory",
            "icon": "mdi:package",
            "create_global": True,
        }

        # Mock existing global entry
        existing_global = MagicMock()
        existing_global.data = {"entry_type": "global"}
        mock_hass.config_entries.async_entries.return_value = [existing_global]

        with (
            patch(
                "custom_components.simple_inventory.SimpleInventoryCoordinator"
            ) as mock_coord_class,
            patch("custom_components.simple_inventory.TodoManager") as mock_todo_class,
            patch("custom_components.simple_inventory.ServiceHandler") as mock_service_class,
            patch("custom_components.simple_inventory._create_global_entry") as mock_create_global,
        ):
            mock_coordinator = MagicMock()
            mock_coordinator.async_load_data = AsyncMock()
            mock_coord_class.return_value = mock_coordinator
            mock_todo_class.return_value = MagicMock()
            mock_service_class.return_value = MagicMock()

            result = await async_setup_entry(mock_hass, mock_config_entry)

            assert result is True
            mock_create_global.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_setup_entry_no_global_when_flag_false(
        self: Self, mock_hass: MagicMock, mock_config_entry: MagicMock
    ) -> None:
        """Test that global entry is not created when create_global is False."""
        mock_config_entry.data = {
            "name": "Test Inventory",
            "icon": "mdi:package",
            "create_global": False,
        }

        with (
            patch(
                "custom_components.simple_inventory.SimpleInventoryCoordinator"
            ) as mock_coord_class,
            patch("custom_components.simple_inventory.TodoManager") as mock_todo_class,
            patch("custom_components.simple_inventory.ServiceHandler") as mock_service_class,
            patch("custom_components.simple_inventory._create_global_entry") as mock_create_global,
        ):
            mock_coordinator = MagicMock()
            mock_coordinator.async_load_data = AsyncMock()
            mock_coord_class.return_value = mock_coordinator
            mock_todo_class.return_value = MagicMock()
            mock_service_class.return_value = MagicMock()

            result = await async_setup_entry(mock_hass, mock_config_entry)

            assert result is True
            mock_create_global.assert_not_called()
