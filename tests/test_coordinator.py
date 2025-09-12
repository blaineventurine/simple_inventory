"""Tests for the SimpleInventoryCoordinator class."""

from datetime import datetime, timedelta
from typing import Generator, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from typing_extensions import Self

from custom_components.simple_inventory.const import (
    DEFAULT_EXPIRY_ALERT_DAYS,
    DOMAIN,
)
from custom_components.simple_inventory.coordinator import (
    SimpleInventoryCoordinator,
)
from custom_components.simple_inventory.types import InventoryData


@pytest.fixture
def coordinator(
    hass: MagicMock,
) -> Generator[SimpleInventoryCoordinator, None, None]:
    """Create a SimpleInventoryCoordinator instance."""

    coordinator = SimpleInventoryCoordinator(cast(HomeAssistant, hass))

    with (
        patch.object(coordinator._store, "async_load", new=AsyncMock(return_value=None)),
        patch.object(coordinator._store, "async_save", new=AsyncMock()),
    ):
        yield coordinator


@pytest.fixture
def loaded_coordinator(
    hass: MagicMock,
) -> Generator[SimpleInventoryCoordinator, None, None]:
    """Create a coordinator with pre-loaded data."""
    from typing import cast

    from homeassistant.core import HomeAssistant

    coordinator = SimpleInventoryCoordinator(cast(HomeAssistant, hass))

    # Mock data that would be loaded from storage
    test_data: InventoryData = {
        "inventories": {
            "kitchen": {
                "items": {
                    "milk": {
                        "quantity": 2,
                        "unit": "liters",
                        "category": "dairy",
                        "expiry_date": "2024-12-31",
                        "auto_add_enabled": True,
                        "auto_add_to_list_quantity": 1,
                        "todo_list": "todo.shopping",
                    },
                    "bread": {
                        "quantity": 1,
                        "unit": "loaf",
                        "category": "bakery",
                        "expiry_date": "2024-06-20",
                        "auto_add_enabled": False,
                        "auto_add_to_list_quantity": 0,
                        "todo_list": "",
                    },
                }
            }
        },
        "config": {"expiry_alert_days": 7},
    }

    with (
        patch.object(
            coordinator._store,
            "async_load",
            new=AsyncMock(return_value=test_data),
        ),
        patch.object(coordinator._store, "async_save", new=AsyncMock()),
    ):
        coordinator._data = test_data
        yield coordinator


class TestSimpleInventoryCoordinator:
    """Tests for SimpleInventoryCoordinator class."""

    async def test_init(self: Self, coordinator: SimpleInventoryCoordinator) -> None:
        """Test coordinator initialization."""
        assert coordinator.hass is not None
        assert coordinator._store is not None
        assert coordinator._data == cast(
            InventoryData,
            {
                "inventories": {},
                "config": {"expiry_alert_days": DEFAULT_EXPIRY_ALERT_DAYS},
            },
        )
        assert "config" in coordinator._data
        assert "expiry_alert_days" in coordinator._data["config"]
        assert coordinator._data["config"]["expiry_alert_days"] == DEFAULT_EXPIRY_ALERT_DAYS

    async def test_async_load_data_empty(
        self: Self, coordinator: SimpleInventoryCoordinator
    ) -> None:
        """Test loading data when storage is empty."""
        with patch.object(coordinator._store, "async_load", new=AsyncMock(return_value=None)):

            data = await coordinator.async_load_data()

            assert "inventories" in data
            assert "config" in data
            assert data["inventories"] == {}

            assert coordinator._data["inventories"] == {}

    async def test_async_load_data_with_content(
        self: Self, coordinator: SimpleInventoryCoordinator
    ) -> None:
        """Test loading data with existing content."""
        test_data: InventoryData = {
            "inventories": {"kitchen": {"items": {"milk": {"quantity": 1}}}},
            "config": {"expiry_alert_days": 14},
        }

        with patch.object(
            coordinator._store,
            "async_load",
            new=AsyncMock(return_value=test_data),
        ):

            data = await coordinator.async_load_data()

            assert data == test_data
            assert coordinator._data == test_data

    async def test_async_load_data_missing_config(
        self: Self, coordinator: SimpleInventoryCoordinator
    ) -> None:
        """Test loading data with missing config section."""
        test_data: InventoryData = {"inventories": {"kitchen": {"items": {}}}}
        with patch.object(
            coordinator._store,
            "async_load",
            new=AsyncMock(return_value=test_data),
        ):

            data = await coordinator.async_load_data()

            # Should add config section
            assert "config" in data
            assert coordinator._data["config"] == {}

    async def test_async_save_data(self: Self, coordinator: SimpleInventoryCoordinator) -> None:
        """Test saving data."""
        from typing import cast

        from custom_components.simple_inventory.types import InventoryData

        coordinator._data = cast(
            InventoryData,
            {
                "inventories": {"kitchen": {"items": {}}},
                "config": {"expiry_alert_days": 7},
            },
        )

        with (
            patch.object(coordinator._store, "async_save", new=AsyncMock()) as mock_save,
            patch.object(coordinator.hass.bus, "async_fire") as mock_fire,
        ):

            await coordinator.async_save_data()

            mock_save.assert_called_once_with(coordinator._data)
            # Should fire events for all inventories
            # One for inventory, one for general update
            assert mock_fire.call_count == 2
            mock_fire.assert_any_call(f"{DOMAIN}_updated_kitchen")
            mock_fire.assert_any_call(f"{DOMAIN}_updated")

    async def test_async_save_data_specific_inventory(
        self: Self, coordinator: SimpleInventoryCoordinator
    ) -> None:
        """Test saving data for a specific inventory."""
        from typing import cast

        from custom_components.simple_inventory.types import InventoryData

        coordinator._data = cast(
            InventoryData,
            {
                "inventories": {
                    "kitchen": {"items": {}},
                    "pantry": {"items": {}},
                },
                "config": {"expiry_alert_days": 7},
            },
        )

        with (
            patch.object(coordinator._store, "async_save", new=AsyncMock()) as mock_save,
            patch.object(coordinator.hass.bus, "async_fire") as mock_fire,
        ):

            await coordinator.async_save_data(inventory_id="kitchen")

            mock_save.assert_called_once_with(coordinator._data)
            mock_fire.assert_called_once_with(f"{DOMAIN}_updated_kitchen")

    async def test_get_data(self: Self, loaded_coordinator: SimpleInventoryCoordinator) -> None:
        """Test getting all data."""
        data = loaded_coordinator.get_data()
        assert "inventories" in data
        assert "kitchen" in data["inventories"]
        assert "config" in data
        assert "expiry_alert_days" in data["config"]
        assert data["config"]["expiry_alert_days"] == 7

    async def test_get_inventory(
        self: Self, loaded_coordinator: SimpleInventoryCoordinator
    ) -> None:
        """Test getting a specific inventory."""
        inventory = loaded_coordinator.get_inventory("kitchen")
        assert "items" in inventory
        assert "milk" in inventory["items"]

        # Test getting non-existent inventory
        empty_inventory = loaded_coordinator.get_inventory("non_existent")
        assert empty_inventory == {"items": {}}

    async def test_ensure_inventory_exists(
        self: Self, coordinator: SimpleInventoryCoordinator
    ) -> None:
        """Test ensuring an inventory exists."""
        # Initially empty
        assert "pantry" not in coordinator._data["inventories"]

        # After ensuring
        inventory = coordinator.ensure_inventory_exists("pantry")
        assert "pantry" in coordinator._data["inventories"]
        assert inventory == {"items": {}}

        # Ensuring an existing inventory
        coordinator._data["inventories"]["kitchen"] = {"items": {"milk": {"quantity": 1}}}
        inventory = coordinator.ensure_inventory_exists("kitchen")
        assert inventory == {"items": {"milk": {"quantity": 1}}}

    async def test_get_item(self: Self, loaded_coordinator: SimpleInventoryCoordinator) -> None:
        """Test getting a specific item."""
        item = loaded_coordinator.get_item("kitchen", "milk")
        assert item is not None
        assert item["quantity"] == 2
        assert item["unit"] == "liters"

        # Test getting non-existent item
        non_existent = loaded_coordinator.get_item("kitchen", "non_existent")
        assert non_existent is None

    async def test_get_all_items(
        self: Self, loaded_coordinator: SimpleInventoryCoordinator
    ) -> None:
        """Test getting all items from an inventory."""
        items = loaded_coordinator.get_all_items("kitchen")
        assert len(items) == 2
        assert "milk" in items
        assert "bread" in items

        # Test getting items from non-existent inventory
        empty_items = loaded_coordinator.get_all_items("non_existent")
        assert empty_items == {}

    async def test_update_item(self: Self, loaded_coordinator: SimpleInventoryCoordinator) -> None:
        """Test updating an existing item."""
        # Update milk quantity
        result = loaded_coordinator.update_item(
            "kitchen", "milk", "milk", quantity=3, unit="gallons"
        )
        assert result is True

        # Verify update
        item = loaded_coordinator.get_item("kitchen", "milk")
        assert item is not None
        assert item["quantity"] == 3
        assert item["unit"] == "gallons"

        # Test updating non-existent item
        result = loaded_coordinator.update_item(
            "kitchen", "non_existent", "non_existent", quantity=1
        )
        assert result is False

    async def test_update_item_rename(
        self: Self, loaded_coordinator: SimpleInventoryCoordinator
    ) -> None:
        """Test updating an item with a name change."""
        # Rename milk to whole_milk
        result = loaded_coordinator.update_item("kitchen", "milk", "whole_milk", quantity=3)
        assert result is True

        # Verify rename
        assert loaded_coordinator.get_item("kitchen", "milk") is None
        item = loaded_coordinator.get_item("kitchen", "whole_milk")
        assert item is not None
        assert item["quantity"] == 3

    async def test_add_item(self: Self, coordinator: SimpleInventoryCoordinator) -> None:
        """Test adding a new item."""
        # Add new item
        result = coordinator.add_item(
            "kitchen",
            name="milk",
            quantity=2,
            unit="liters",
            category="dairy",
            expiry_date="2024-12-31",
            auto_add_enabled=True,
            auto_add_to_list_quantity=1,
            todo_list="todo.shopping",
        )
        assert result is True

        # Verify item was added
        item = coordinator.get_item("kitchen", "milk")
        assert item is not None
        assert item["quantity"] == 2
        assert item["unit"] == "liters"
        assert item["category"] == "dairy"
        assert item["expiry_date"] == "2024-12-31"
        assert item["auto_add_enabled"] is True
        assert item["auto_add_to_list_quantity"] == 1
        assert item["todo_list"] == "todo.shopping"

    async def test_add_item_with_zero_auto_add_quantity(
        self: Self, coordinator: SimpleInventoryCoordinator
    ) -> None:
        """Test adding item with auto-add quantity set to 0."""
        result = coordinator.add_item(
            "kitchen",
            name="bread",
            quantity=3,
            auto_add_enabled=True,
            auto_add_to_list_quantity=0,
            todo_list="todo.shopping",
        )
        assert result is True

        item = coordinator.get_item("kitchen", "bread")
        assert item is not None
        assert item["auto_add_to_list_quantity"] == 0

    async def test_add_item_auto_add_with_none_todo_list_fails(
        self: Self, coordinator: SimpleInventoryCoordinator
    ) -> None:
        """Test that auto-add enabled with None todo list fails."""
        result = coordinator.add_item(
            "kitchen",
            name="butter",
            quantity=1,
            auto_add_enabled=True,
            auto_add_to_list_quantity=0,
            todo_list=cast(str, None),  # None todo list should fail
        )
        assert result is False

        item = coordinator.get_item("kitchen", "butter")
        assert item is None

    async def test_add_item_existing(
        self: Self, loaded_coordinator: SimpleInventoryCoordinator
    ) -> None:
        """Test adding an existing item (should update quantity)."""
        # Initial quantity is 2
        initial_item = loaded_coordinator.get_item("kitchen", "milk")
        assert initial_item is not None
        assert initial_item["quantity"] == 2

        # Add 3 more
        result = loaded_coordinator.add_item("kitchen", name="milk", quantity=3)
        assert result is True

        # Verify quantity was updated
        updated_item = loaded_coordinator.get_item("kitchen", "milk")
        assert updated_item is not None
        assert updated_item["quantity"] == 5  # 2 + 3

    async def test_add_item_empty_name(self: Self, coordinator: SimpleInventoryCoordinator) -> None:
        """Test adding an item with empty name."""
        with pytest.raises(ValueError, match="Item name cannot be empty"):
            coordinator.add_item("kitchen", name="", quantity=1)

        with pytest.raises(ValueError, match="Item name cannot be empty"):
            coordinator.add_item("kitchen", name="  ", quantity=1)

    async def test_add_item_negative_quantity(
        self: Self, coordinator: SimpleInventoryCoordinator
    ) -> None:
        """Test adding an item with negative quantity."""
        result = coordinator.add_item("kitchen", name="milk", quantity=-3)
        assert result is True

        # Quantity should be set to 0 (max of 0 and -3)
        item = coordinator.get_item("kitchen", "milk")
        assert item is not None
        assert item["quantity"] == 0

    async def test_add_item_negative_auto_add_quantity(
        self: Self, coordinator: SimpleInventoryCoordinator
    ) -> None:
        """Test adding an item with negative auto add quantity."""
        result = coordinator.add_item(
            "kitchen", name="milk", quantity=1, auto_add_to_list_quantity=-2
        )
        assert result is True

        # Auto add quantity should be set to 0 (max of 0 and -2)
        item = coordinator.get_item("kitchen", "milk")
        assert item is not None
        assert item["auto_add_to_list_quantity"] == 0

    async def test_remove_item(self: Self, loaded_coordinator: SimpleInventoryCoordinator) -> None:
        """Test removing an item."""
        # Verify item exists
        assert loaded_coordinator.get_item("kitchen", "milk") is not None

        # Remove item
        result = loaded_coordinator.remove_item("kitchen", "milk")
        assert result is True

        # Verify item was removed
        assert loaded_coordinator.get_item("kitchen", "milk") is None

        # Test removing non-existent item
        result = loaded_coordinator.remove_item("kitchen", "non_existent")
        assert result is False

        # Test removing with empty name
        result = loaded_coordinator.remove_item("kitchen", "")
        assert result is False

    async def test_increment_item(
        self: Self, loaded_coordinator: SimpleInventoryCoordinator
    ) -> None:
        """Test incrementing item quantity."""
        # Initial quantity is 2
        initial_item = loaded_coordinator.get_item("kitchen", "milk")
        assert initial_item is not None
        assert initial_item["quantity"] == 2

        # Increment by default (1)
        result = loaded_coordinator.increment_item("kitchen", "milk")
        assert result is True

        # Verify quantity was incremented
        updated_item = loaded_coordinator.get_item("kitchen", "milk")
        assert updated_item is not None
        assert updated_item["quantity"] == 3

        # Increment by specific amount
        result = loaded_coordinator.increment_item("kitchen", "milk", 2)
        assert result is True
        updated_item = loaded_coordinator.get_item("kitchen", "milk")
        assert updated_item is not None
        assert updated_item["quantity"] == 5

        # Test incrementing non-existent item
        result = loaded_coordinator.increment_item("kitchen", "non_existent")
        assert result is False

        # Test incrementing with empty name
        result = loaded_coordinator.increment_item("kitchen", "")
        assert result is False

        # Test incrementing with negative amount
        result = loaded_coordinator.increment_item("kitchen", "milk", -1)
        assert result is False

    async def test_decrement_item(
        self: Self, loaded_coordinator: SimpleInventoryCoordinator
    ) -> None:
        """Test decrementing item quantity."""
        # Initial quantity is 2
        initial_item = loaded_coordinator.get_item("kitchen", "milk")
        assert initial_item is not None
        assert initial_item["quantity"] == 2

        # Decrement by default (1)
        result = loaded_coordinator.decrement_item("kitchen", "milk")
        assert result is True

        # Verify quantity was decremented
        updated_item = loaded_coordinator.get_item("kitchen", "milk")
        assert updated_item is not None
        assert updated_item["quantity"] == 1

        # Decrement by specific amount
        result = loaded_coordinator.decrement_item("kitchen", "milk", 1)
        assert result is True
        updated_item = loaded_coordinator.get_item("kitchen", "milk")
        assert updated_item is not None
        assert updated_item["quantity"] == 0

        # Test decrementing below 0 (should stay at 0)
        result = loaded_coordinator.decrement_item("kitchen", "milk", 5)
        assert result is True
        updated_item = loaded_coordinator.get_item("kitchen", "milk")
        assert updated_item is not None
        assert updated_item["quantity"] == 0

        # Test decrementing non-existent item
        result = loaded_coordinator.decrement_item("kitchen", "non_existent")
        assert result is False

        # Test decrementing with empty name
        result = loaded_coordinator.decrement_item("kitchen", "")
        assert result is False

        # Test decrementing with negative amount
        result = loaded_coordinator.decrement_item("kitchen", "milk", -1)
        assert result is False

    @patch("datetime.datetime")
    async def test_get_items_expiring_soon(
        self: Self,
        mock_datetime: MagicMock,
        loaded_coordinator: SimpleInventoryCoordinator,
    ) -> None:
        """Test getting items expiring soon."""
        # Set up a fixed current date for testing
        fixed_date = datetime(2024, 6, 15)
        today = fixed_date.date()

        # Configure the mock
        mock_datetime.now.return_value = fixed_date
        mock_datetime.strptime.side_effect = datetime.strptime

        # Calculate dates relative to the fixed date
        date_1_day_ahead = (today + timedelta(days=1)).strftime("%Y-%m-%d")  # 1 day from now
        date_5_days_ahead = (today + timedelta(days=5)).strftime("%Y-%m-%d")  # 5 days from now
        date_15_days_ahead = (today + timedelta(days=15)).strftime("%Y-%m-%d")  # 15 days from now

        # Set up test data with calculated dates
        loaded_coordinator._data = {
            "inventories": {
                "kitchen": {
                    "items": {
                        "milk": {
                            "quantity": 1,
                            "expiry_date": date_5_days_ahead,  # 5 days from now
                            "expiry_alert_days": 7,
                        },
                        "yogurt": {
                            "quantity": 1,
                            "expiry_date": date_1_day_ahead,  # 1 day from now
                            "expiry_alert_days": 7,
                        },
                        "cheese": {
                            "quantity": 1,
                            # 15 days from now (beyond default threshold)
                            "expiry_date": date_15_days_ahead,
                            "expiry_alert_days": 7,
                        },
                        # No expiry date
                        "bread": {"quantity": 1, "expiry_date": ""},
                    }
                }
            },
            "config": {"expiry_alert_days": 7},
        }

        # Patch the datetime in the method directly
        with patch("custom_components.simple_inventory.coordinator.datetime") as patched_dt:
            patched_dt.now.return_value = fixed_date
            patched_dt.strptime = datetime.strptime

            # Call the method
            expiring_items = loaded_coordinator.get_items_expiring_soon("kitchen")

        # Print debug info
        print(f"Fixed date: {fixed_date}")
        print(f"Found {len(expiring_items)} expiring items:")
        for item in expiring_items:
            print(
                f"  - {item['name']}: expiry={item['expiry_date']
                                              }, days={item['days_until_expiry']}"
            )

        # Should include milk and yogurt (within 7 days), but not cheese
        # (beyond threshold) or bread (no date)
        assert (
            len(expiring_items) == 2
        ), f"Expected 2 items but found {
            len(expiring_items)}: {[item['name'] for item in expiring_items]}"

        # Items should be sorted by days until expiry (soonest first)
        assert (
            expiring_items[0]["name"] == "yogurt"
        ), f"Expected yogurt but got {
            expiring_items[0]['name']}"
        assert (
            expiring_items[1]["name"] == "milk"
        ), f"Expected milk but got {
            expiring_items[1]['name']}"

        # Check days_until_expiry calculation
        assert (
            expiring_items[0]["days_until_expiry"] == 1
        ), f"Expected 1 day but got {
            expiring_items[0]['days_until_expiry']}"
        assert (
            expiring_items[1]["days_until_expiry"] == 5
        ), f"Expected 5 days but got {
            expiring_items[1]['days_until_expiry']}"

    async def test_async_add_listener(self: Self, coordinator: SimpleInventoryCoordinator) -> None:
        """Test adding a listener."""
        listener = MagicMock()

        remove_listener = coordinator.async_add_listener(listener)

        assert listener in coordinator._listeners

        remove_listener()

        assert listener not in coordinator._listeners

    async def test_notify_listeners(self: Self, coordinator: SimpleInventoryCoordinator) -> None:
        """Test notifying listeners."""
        listener1 = MagicMock()
        listener2 = MagicMock()

        coordinator.async_add_listener(listener1)
        coordinator.async_add_listener(listener2)

        coordinator.notify_listeners()

        listener1.assert_called_once()
        listener2.assert_called_once()

    async def test_get_inventory_statistics(
        self: Self, loaded_coordinator: SimpleInventoryCoordinator
    ) -> None:
        """Test getting inventory statistics."""
        loaded_coordinator._data["inventories"]["kitchen"]["items"]["yogurt"] = {
            "quantity": 1,
            "unit": "cup",
            "category": "dairy",
            "expiry_date": "2024-06-16",  # Expiring soon
            "auto_add_enabled": False,
            "auto_add_to_list_quantity": 2,  # Below threshold
            "todo_list": "",
        }

        loaded_coordinator._data["inventories"]["kitchen"]["items"]["rice"] = {
            "quantity": 5,
            "unit": "kg",
            "category": "grains",
            "expiry_date": "2025-06-15",
            "auto_add_enabled": False,
            "auto_add_to_list_quantity": 2,
            "todo_list": "",
        }

        with patch.object(
            loaded_coordinator,
            "get_items_expiring_soon",
            return_value=[
                {"name": "yogurt", "days_until_expiry": 1},
                {"name": "milk", "days_until_expiry": 5},
            ],
        ):

            stats = loaded_coordinator.get_inventory_statistics("kitchen")

            # Verify statistics
            assert stats["total_items"] == 4  # milk, bread, yogurt, rice
            assert stats["total_quantity"] == 9  # 2 + 1 + 1 + 5

            # Verify categories
            assert "dairy" in stats["categories"]
            assert stats["categories"]["dairy"] == 2  # milk, yogurt
            assert "bakery" in stats["categories"]
            assert stats["categories"]["bakery"] == 1  # bread
            assert "grains" in stats["categories"]
            assert stats["categories"]["grains"] == 1  # rice

            # Verify below threshold
            assert len(stats["below_threshold"]) == 1  # yogurt
            assert stats["below_threshold"][0]["name"] == "yogurt"

            # Verify expiring items
            assert len(stats["expiring_items"]) == 2  # milk, yogurt
