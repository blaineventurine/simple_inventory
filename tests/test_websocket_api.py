"""Tests for the WebSocket API."""

from __future__ import annotations

import json
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol
from awesomeversion import AwesomeVersion
from homeassistant.config_entries import ConfigEntryDisabler
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError, Unauthorized
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (  # type: ignore[import-untyped]
    MockConfigEntry,
)
from pytest_homeassistant_custom_component.typing import (  # type: ignore[import-untyped]
    WebSocketGenerator,
)

from custom_components.simple_inventory.const import API_VERSION, DOMAIN
from custom_components.simple_inventory.websocket_api import (
    async_register_websocket_commands,
    ws_export,
    ws_get_barcode_provider_config,
    ws_get_history,
    ws_get_inventory_consumption_rates,
    ws_get_inventory_statistics,
    ws_get_item,
    ws_get_item_consumption_rates,
    ws_import,
    ws_list_items,
    ws_lookup_barcode_product,
    ws_lookup_by_barcode,
    ws_scan_barcode,
    ws_set_barcode_provider_config,
    ws_subscribe,
)

from .harness import add_entry, integration_env, open_database, setup_entry


@pytest.fixture
def mock_connection() -> MagicMock:
    """Create a mock WebSocket connection."""
    conn = MagicMock()
    conn.send_result = MagicMock()
    conn.send_error = MagicMock()
    conn.send_event = MagicMock()
    conn.subscriptions = {}
    return conn


async def _run(
    command: Callable[[Any, Any, dict[str, Any]], None],
    hass: MagicMock,
    connection: MagicMock,
    msg: dict[str, Any],
) -> None:
    """Dispatch *msg* to a registered command the way HA does and await its response task."""
    tasks: list[Coroutine[Any, Any, None]] = []
    hass.async_create_background_task = MagicMock(
        side_effect=lambda coro, *_args, **_kwargs: tasks.append(coro)
    )
    command(hass, connection, msg)
    for task in tasks:
        await task


@pytest.fixture
def mock_coordinator_ws() -> MagicMock:
    """Create a mock coordinator for WS tests."""
    coordinator = MagicMock()
    coordinator.async_list_items = AsyncMock(
        return_value=[
            {"name": "milk", "quantity": 2},
            {"name": "bread", "quantity": 1},
        ]
    )
    coordinator.async_get_item = AsyncMock(return_value={"name": "milk", "quantity": 2})
    coordinator.async_get_item_history = AsyncMock(return_value=[])
    coordinator.async_get_inventory_history = AsyncMock(return_value=[{"event_type": "add"}])
    coordinator.async_export_inventory = AsyncMock(return_value={"version": "1.0", "items": []})
    coordinator.async_import_inventory = AsyncMock(
        return_value={"added": 1, "updated": 0, "skipped": 0, "errors": []}
    )
    coordinator.async_get_item_consumption_rates = AsyncMock(
        return_value={
            "item_name": "milk",
            "current_quantity": 5.0,
            "unit": "liters",
            "daily_rate": 0.5,
            "weekly_rate": 3.5,
            "days_until_depletion": 10.0,
            "has_sufficient_data": True,
        }
    )
    coordinator.async_get_inventory_consumption_rates = AsyncMock(
        return_value={
            "inventory_id": "inv1",
            "window_days": None,
            "items": [],
            "summary": {
                "total_items_tracked": 0,
                "total_consumed": 0.0,
                "most_consumed": [],
                "running_out_soonest": [],
            },
        }
    )
    coordinator.async_get_inventory_statistics = AsyncMock(
        return_value={
            "total_items": 2,
            "total_quantity": 5.0,
            "total_value": 12.50,
            "categories": {"Dairy": 1},
            "locations": {"Fridge": 2},
            "below_threshold": [],
            "expiring_items": [],
        }
    )
    coordinator.hub.async_lookup_by_barcode = AsyncMock(
        return_value=[{"name": "milk", "inventory_id": "inv1", "inventory_name": "Kitchen"}]
    )
    coordinator.async_scan_barcode = AsyncMock(
        return_value={"action": "increment", "success": True, "item_name": "milk"}
    )
    return coordinator


class TestHandleListItems:
    async def test_list_items_success(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN].coordinators["inv1"] = mock_coordinator_ws
        msg = {"id": 1, "type": f"{DOMAIN}/list_items", "inventory_id": "inv1"}

        await _run(ws_list_items, hass_mock, mock_connection, msg)

        mock_coordinator_ws.async_list_items.assert_awaited_once_with("inv1")
        mock_connection.send_result.assert_called_once_with(
            1,
            {
                "items": [
                    {"name": "milk", "quantity": 2},
                    {"name": "bread", "quantity": 1},
                ]
            },
        )

    async def test_list_items_inventory_not_found(
        self, hass_mock: MagicMock, mock_connection: MagicMock
    ) -> None:
        msg = {"id": 1, "type": f"{DOMAIN}/list_items", "inventory_id": "missing"}

        await _run(ws_list_items, hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(
            1, "inventory_not_found", "Inventory 'missing' not found"
        )

    async def test_list_items_coordinator_error(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN].coordinators["inv1"] = mock_coordinator_ws
        mock_coordinator_ws.async_list_items = AsyncMock(side_effect=RuntimeError("db error"))
        msg = {"id": 1, "type": f"{DOMAIN}/list_items", "inventory_id": "inv1"}

        await _run(ws_list_items, hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(1, "list_items_failed", "db error")

    async def test_list_items_translated_error_keeps_plain_error_shape(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN].coordinators["inv1"] = mock_coordinator_ws
        mock_coordinator_ws.async_list_items = AsyncMock(
            side_effect=ServiceValidationError(
                "nope", translation_domain=DOMAIN, translation_key="item_not_found"
            )
        )
        msg = {"id": 2, "type": f"{DOMAIN}/list_items", "inventory_id": "inv1"}

        await _run(ws_list_items, hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(2, "list_items_failed", "nope")


class TestHandleGetItem:
    async def test_get_item_success(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN].coordinators["inv1"] = mock_coordinator_ws
        msg = {
            "id": 2,
            "type": f"{DOMAIN}/get_item",
            "inventory_id": "inv1",
            "name": "milk",
        }

        await _run(ws_get_item, hass_mock, mock_connection, msg)

        mock_coordinator_ws.async_get_item.assert_awaited_once_with("inv1", "milk")
        mock_connection.send_result.assert_called_once_with(
            2, {"item": {"name": "milk", "quantity": 2}}
        )

    async def test_get_item_inventory_not_found(
        self, hass_mock: MagicMock, mock_connection: MagicMock
    ) -> None:
        msg = {
            "id": 2,
            "type": f"{DOMAIN}/get_item",
            "inventory_id": "missing",
            "name": "milk",
        }

        await _run(ws_get_item, hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(
            2, "inventory_not_found", "Inventory 'missing' not found"
        )

    async def test_get_item_not_found(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN].coordinators["inv1"] = mock_coordinator_ws
        mock_coordinator_ws.async_get_item.return_value = None
        msg = {
            "id": 3,
            "type": f"{DOMAIN}/get_item",
            "inventory_id": "inv1",
            "name": "nonexistent",
        }

        await _run(ws_get_item, hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(
            3,
            "item_not_found",
            "Item 'nonexistent' not found in inventory 'inv1'",
        )

    async def test_get_item_coordinator_error(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN].coordinators["inv1"] = mock_coordinator_ws
        mock_coordinator_ws.async_get_item = AsyncMock(side_effect=RuntimeError("db error"))
        msg = {
            "id": 3,
            "type": f"{DOMAIN}/get_item",
            "inventory_id": "inv1",
            "name": "milk",
        }

        await _run(ws_get_item, hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(3, "get_item_failed", "db error")


class TestHandleSubscribe:
    def test_subscribe_with_inventory_id(
        self, hass_mock: MagicMock, mock_connection: MagicMock
    ) -> None:
        msg = {
            "id": 4,
            "type": f"{DOMAIN}/subscribe",
            "inventory_id": "inv1",
        }

        ws_subscribe(hass_mock, mock_connection, msg)

        hass_mock.bus.async_listen.assert_called_once()
        event_type = hass_mock.bus.async_listen.call_args[0][0]
        assert event_type == f"{DOMAIN}_updated_inv1"
        assert 4 in mock_connection.subscriptions
        mock_connection.send_result.assert_called_once_with(4)

    def test_subscribe_global(self, hass_mock: MagicMock, mock_connection: MagicMock) -> None:
        msg = {
            "id": 5,
            "type": f"{DOMAIN}/subscribe",
        }

        ws_subscribe(hass_mock, mock_connection, msg)

        hass_mock.bus.async_listen.assert_called_once()
        event_type = hass_mock.bus.async_listen.call_args[0][0]
        assert event_type == f"{DOMAIN}_updated"
        assert 5 in mock_connection.subscriptions
        mock_connection.send_result.assert_called_once_with(5)

    async def test_global_subscription_forwards_an_updated_event(
        self, hass_mock: MagicMock, mock_connection: MagicMock
    ) -> None:
        ws_subscribe(hass_mock, mock_connection, {"id": 8, "type": f"{DOMAIN}/subscribe"})

        listener_callback = hass_mock.bus.async_listen.call_args[0][1]
        await listener_callback(MagicMock())

        mock_connection.send_event.assert_called_once_with(8, {"event": "updated"})

    async def test_subscribe_forwards_events(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN].coordinators["inv1"] = mock_coordinator_ws
        msg = {
            "id": 6,
            "type": f"{DOMAIN}/subscribe",
            "inventory_id": "inv1",
        }

        ws_subscribe(hass_mock, mock_connection, msg)

        # Get the callback that was registered
        listener_callback = hass_mock.bus.async_listen.call_args[0][1]

        # Simulate an event firing
        mock_event = MagicMock()
        await listener_callback(mock_event)

        mock_coordinator_ws.async_list_items.assert_awaited_once_with("inv1")
        mock_connection.send_event.assert_called_once()
        event_data = mock_connection.send_event.call_args[0]
        assert event_data[0] == 6
        assert "items" in event_data[1]

    async def test_forward_event_logs_and_does_not_raise(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN].coordinators["inv1"] = mock_coordinator_ws
        mock_coordinator_ws.async_list_items = AsyncMock(side_effect=RuntimeError("boom"))
        msg = {
            "id": 7,
            "type": f"{DOMAIN}/subscribe",
            "inventory_id": "inv1",
        }

        ws_subscribe(hass_mock, mock_connection, msg)

        listener_callback = hass_mock.bus.async_listen.call_args[0][1]
        mock_event = MagicMock()

        # Should not raise even though the coordinator call fails.
        await listener_callback(mock_event)

        mock_connection.send_event.assert_not_called()


class TestHandleGetHistory:
    async def test_get_inventory_history(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN].coordinators["inv1"] = mock_coordinator_ws
        msg = {
            "id": 20,
            "type": f"{DOMAIN}/get_history",
            "inventory_id": "inv1",
        }

        await _run(ws_get_history, hass_mock, mock_connection, msg)

        mock_coordinator_ws.async_get_inventory_history.assert_awaited_once()
        mock_connection.send_result.assert_called_once()
        result = mock_connection.send_result.call_args[0][1]
        assert "events" in result

    async def test_get_item_history(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN].coordinators["inv1"] = mock_coordinator_ws
        msg = {
            "id": 21,
            "type": f"{DOMAIN}/get_history",
            "inventory_id": "inv1",
            "item_name": "milk",
        }

        await _run(ws_get_history, hass_mock, mock_connection, msg)

        mock_coordinator_ws.async_get_item_history.assert_awaited_once()

    async def test_get_history_inventory_not_found(
        self, hass_mock: MagicMock, mock_connection: MagicMock
    ) -> None:
        msg = {
            "id": 22,
            "type": f"{DOMAIN}/get_history",
            "inventory_id": "missing",
        }

        await _run(ws_get_history, hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(
            22, "inventory_not_found", "Inventory 'missing' not found"
        )

    async def test_get_history_coordinator_error(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN].coordinators["inv1"] = mock_coordinator_ws
        mock_coordinator_ws.async_get_inventory_history = AsyncMock(
            side_effect=RuntimeError("db error")
        )
        msg = {
            "id": 23,
            "type": f"{DOMAIN}/get_history",
            "inventory_id": "inv1",
        }

        await _run(ws_get_history, hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(23, "history_failed", "db error")


class TestHandleExport:
    async def test_export_success(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN].coordinators["inv1"] = mock_coordinator_ws
        msg = {
            "id": 30,
            "type": f"{DOMAIN}/export",
            "inventory_id": "inv1",
            "format": "json",
        }

        await _run(ws_export, hass_mock, mock_connection, msg)

        mock_coordinator_ws.async_export_inventory.assert_awaited_once_with("inv1", "json")
        mock_connection.send_result.assert_called_once()

    async def test_export_inventory_not_found(
        self, hass_mock: MagicMock, mock_connection: MagicMock
    ) -> None:
        msg = {
            "id": 31,
            "type": f"{DOMAIN}/export",
            "inventory_id": "missing",
            "format": "json",
        }

        await _run(ws_export, hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(
            31, "inventory_not_found", "Inventory 'missing' not found"
        )

    async def test_export_value_error_is_export_failed(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN].coordinators["inv1"] = mock_coordinator_ws
        mock_coordinator_ws.async_export_inventory = AsyncMock(side_effect=ValueError("bad"))
        msg = {"id": 32, "type": f"{DOMAIN}/export", "inventory_id": "inv1", "format": "csv"}

        await _run(ws_export, hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(32, "export_failed", "bad")
        mock_connection.send_result.assert_not_called()

    async def test_export_unexpected_error_is_left_to_home_assistant(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        error = RuntimeError("db gone")
        hass_mock.data[DOMAIN].coordinators["inv1"] = mock_coordinator_ws
        mock_coordinator_ws.async_export_inventory = AsyncMock(side_effect=error)
        msg = {"id": 33, "type": f"{DOMAIN}/export", "inventory_id": "inv1", "format": "json"}

        await _run(ws_export, hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_not_called()
        mock_connection.async_handle_exception.assert_called_once_with(msg, error)


class TestHandleImport:
    async def test_import_success(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN].coordinators["inv1"] = mock_coordinator_ws
        msg = {
            "id": 40,
            "type": f"{DOMAIN}/import",
            "inventory_id": "inv1",
            "data": {"items": [{"name": "Apple", "quantity": 5}]},
            "format": "json",
            "merge_strategy": "skip",
        }

        await _run(ws_import, hass_mock, mock_connection, msg)

        mock_coordinator_ws.async_import_inventory.assert_awaited_once()
        mock_connection.send_result.assert_called_once()

    async def test_import_inventory_not_found(
        self, hass_mock: MagicMock, mock_connection: MagicMock
    ) -> None:
        msg = {
            "id": 41,
            "type": f"{DOMAIN}/import",
            "inventory_id": "missing",
            "data": {"items": []},
        }

        await _run(ws_import, hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(
            41, "inventory_not_found", "Inventory 'missing' not found"
        )

    async def test_import_coordinator_error(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN].coordinators["inv1"] = mock_coordinator_ws
        mock_coordinator_ws.async_import_inventory = AsyncMock(
            side_effect=ValueError("malformed data")
        )
        msg = {
            "id": 42,
            "type": f"{DOMAIN}/import",
            "inventory_id": "inv1",
            "data": {"items": [{"name": "Apple", "quantity": 5}]},
            "format": "json",
            "merge_strategy": "skip",
        }

        await _run(ws_import, hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(42, "import_failed", "malformed data")


class TestHandleGetItemConsumptionRates:
    async def test_success(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN].coordinators["inv1"] = mock_coordinator_ws
        msg = {
            "id": 50,
            "type": f"{DOMAIN}/get_item_consumption_rates",
            "inventory_id": "inv1",
            "item_name": "milk",
        }

        await _run(ws_get_item_consumption_rates, hass_mock, mock_connection, msg)

        mock_coordinator_ws.async_get_item_consumption_rates.assert_awaited_once_with(
            "inv1", "milk", window_days=None
        )
        mock_connection.send_result.assert_called_once()
        result = mock_connection.send_result.call_args[0][1]
        assert result["item_name"] == "milk"

    async def test_inventory_not_found(
        self, hass_mock: MagicMock, mock_connection: MagicMock
    ) -> None:
        msg = {
            "id": 51,
            "type": f"{DOMAIN}/get_item_consumption_rates",
            "inventory_id": "missing",
            "item_name": "milk",
        }

        await _run(ws_get_item_consumption_rates, hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(
            51, "inventory_not_found", "Inventory 'missing' not found"
        )

    async def test_item_not_found(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN].coordinators["inv1"] = mock_coordinator_ws
        mock_coordinator_ws.async_get_item_consumption_rates.return_value = None
        msg = {
            "id": 52,
            "type": f"{DOMAIN}/get_item_consumption_rates",
            "inventory_id": "inv1",
            "item_name": "nonexistent",
        }

        await _run(ws_get_item_consumption_rates, hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(
            52,
            "item_not_found",
            "Item 'nonexistent' not found in inventory 'inv1'",
        )

    async def test_window_days_passed_through(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN].coordinators["inv1"] = mock_coordinator_ws
        msg = {
            "id": 53,
            "type": f"{DOMAIN}/get_item_consumption_rates",
            "inventory_id": "inv1",
            "item_name": "milk",
            "window_days": 30,
        }

        await _run(ws_get_item_consumption_rates, hass_mock, mock_connection, msg)

        mock_coordinator_ws.async_get_item_consumption_rates.assert_awaited_once_with(
            "inv1", "milk", window_days=30
        )

    async def test_coordinator_error(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN].coordinators["inv1"] = mock_coordinator_ws
        mock_coordinator_ws.async_get_item_consumption_rates = AsyncMock(
            side_effect=RuntimeError("db error")
        )
        msg = {
            "id": 54,
            "type": f"{DOMAIN}/get_item_consumption_rates",
            "inventory_id": "inv1",
            "item_name": "milk",
        }

        await _run(ws_get_item_consumption_rates, hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(
            54, "item_consumption_rates_failed", "db error"
        )


class TestHandleGetInventoryConsumptionRates:
    async def test_success(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN].coordinators["inv1"] = mock_coordinator_ws
        msg = {
            "id": 60,
            "type": f"{DOMAIN}/get_inventory_consumption_rates",
            "inventory_id": "inv1",
        }

        await _run(ws_get_inventory_consumption_rates, hass_mock, mock_connection, msg)

        mock_coordinator_ws.async_get_inventory_consumption_rates.assert_awaited_once_with(
            "inv1", window_days=None
        )
        mock_connection.send_result.assert_called_once()

    async def test_inventory_not_found(
        self, hass_mock: MagicMock, mock_connection: MagicMock
    ) -> None:
        msg = {
            "id": 61,
            "type": f"{DOMAIN}/get_inventory_consumption_rates",
            "inventory_id": "missing",
        }

        await _run(ws_get_inventory_consumption_rates, hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(
            61, "inventory_not_found", "Inventory 'missing' not found"
        )

    async def test_window_days_passed_through(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN].coordinators["inv1"] = mock_coordinator_ws
        msg = {
            "id": 62,
            "type": f"{DOMAIN}/get_inventory_consumption_rates",
            "inventory_id": "inv1",
            "window_days": 90,
        }

        await _run(ws_get_inventory_consumption_rates, hass_mock, mock_connection, msg)

        mock_coordinator_ws.async_get_inventory_consumption_rates.assert_awaited_once_with(
            "inv1", window_days=90
        )

    async def test_coordinator_error(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN].coordinators["inv1"] = mock_coordinator_ws
        mock_coordinator_ws.async_get_inventory_consumption_rates = AsyncMock(
            side_effect=RuntimeError("db error")
        )
        msg = {
            "id": 63,
            "type": f"{DOMAIN}/get_inventory_consumption_rates",
            "inventory_id": "inv1",
        }

        await _run(ws_get_inventory_consumption_rates, hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(
            63, "inventory_consumption_rates_failed", "db error"
        )


class TestHandleGetInventoryStatistics:
    async def test_success(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN].coordinators["inv1"] = mock_coordinator_ws
        msg = {
            "id": 65,
            "type": f"{DOMAIN}/get_inventory_statistics",
            "inventory_id": "inv1",
        }

        await _run(ws_get_inventory_statistics, hass_mock, mock_connection, msg)

        mock_coordinator_ws.async_get_inventory_statistics.assert_awaited_once_with("inv1")
        mock_connection.send_result.assert_called_once()
        result = mock_connection.send_result.call_args[0][1]
        assert result["total_items"] == 2
        assert "below_threshold" in result
        assert "expiring_items" in result

    async def test_inventory_not_found(
        self, hass_mock: MagicMock, mock_connection: MagicMock
    ) -> None:
        msg = {
            "id": 66,
            "type": f"{DOMAIN}/get_inventory_statistics",
            "inventory_id": "missing",
        }

        await _run(ws_get_inventory_statistics, hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(
            66, "inventory_not_found", "Inventory 'missing' not found"
        )

    async def test_coordinator_error(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN].coordinators["inv1"] = mock_coordinator_ws
        mock_coordinator_ws.async_get_inventory_statistics = AsyncMock(
            side_effect=RuntimeError("db error")
        )
        msg = {
            "id": 67,
            "type": f"{DOMAIN}/get_inventory_statistics",
            "inventory_id": "inv1",
        }

        await _run(ws_get_inventory_statistics, hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(
            67, "inventory_statistics_failed", "db error"
        )


class TestHandleLookupByBarcode:
    async def test_lookup_success(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN].coordinators["inv1"] = mock_coordinator_ws
        hass_mock.data[DOMAIN].hub = mock_coordinator_ws.hub
        msg = {"id": 70, "type": f"{DOMAIN}/lookup_by_barcode", "barcode": "123456"}

        await _run(ws_lookup_by_barcode, hass_mock, mock_connection, msg)

        mock_coordinator_ws.hub.async_lookup_by_barcode.assert_awaited_once_with("123456")
        mock_connection.send_result.assert_called_once()
        result = mock_connection.send_result.call_args[0][1]
        assert "items" in result

    async def test_lookup_no_inventories(
        self, hass_mock: MagicMock, mock_connection: MagicMock
    ) -> None:
        msg = {"id": 71, "type": f"{DOMAIN}/lookup_by_barcode", "barcode": "123456"}

        await _run(ws_lookup_by_barcode, hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(
            71, "no_inventories", "No inventories configured"
        )

    async def test_lookup_coordinator_error(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN].coordinators["inv1"] = mock_coordinator_ws
        hass_mock.data[DOMAIN].hub = mock_coordinator_ws.hub
        mock_coordinator_ws.hub.async_lookup_by_barcode = AsyncMock(
            side_effect=RuntimeError("db error")
        )
        msg = {"id": 72, "type": f"{DOMAIN}/lookup_by_barcode", "barcode": "123456"}

        await _run(ws_lookup_by_barcode, hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(
            72, "lookup_by_barcode_failed", "db error"
        )


def _make_mock_service_handler(
    scan_result: Any = None, scan_error: Exception | None = None
) -> MagicMock:
    """Build a minimal mock service_handler with a quantity_service."""
    mock_qs = MagicMock()
    if scan_error:
        mock_qs.async_scan_barcode = AsyncMock(side_effect=scan_error)
    else:
        mock_qs.async_scan_barcode = AsyncMock(
            return_value=scan_result
            or {"action": "increment", "success": True, "item_name": "milk", "inventory_id": "inv1"}
        )
    handler = MagicMock()
    handler.quantity_service = mock_qs
    return handler


class TestHandleScanBarcode:
    async def test_scan_success(self, hass_mock: MagicMock, mock_connection: MagicMock) -> None:
        mock_sh = _make_mock_service_handler()
        hass_mock.data[DOMAIN].service_handler = mock_sh
        msg = {
            "id": 80,
            "type": f"{DOMAIN}/scan_barcode",
            "barcode": "123456",
            "action": "increment",
            "amount": 1.0,
        }

        await _run(ws_scan_barcode, hass_mock, mock_connection, msg)

        mock_sh.quantity_service.async_scan_barcode.assert_awaited_once_with(
            barcode="123456", action="increment", amount=1.0, inventory_id=None, price=None
        )
        mock_connection.send_result.assert_called_once()

    async def test_scan_with_inventory_id(
        self, hass_mock: MagicMock, mock_connection: MagicMock
    ) -> None:
        mock_sh = _make_mock_service_handler()
        hass_mock.data[DOMAIN].service_handler = mock_sh
        msg = {
            "id": 81,
            "type": f"{DOMAIN}/scan_barcode",
            "barcode": "123456",
            "action": "decrement",
            "inventory_id": "inv1",
        }

        await _run(ws_scan_barcode, hass_mock, mock_connection, msg)

        mock_sh.quantity_service.async_scan_barcode.assert_awaited_once_with(
            barcode="123456", action="decrement", amount=1.0, inventory_id="inv1", price=None
        )

    async def test_scan_forwards_batch_fields_only_when_present(
        self, hass_mock: MagicMock, mock_connection: MagicMock
    ) -> None:
        mock_sh = _make_mock_service_handler()
        hass_mock.data[DOMAIN].service_handler = mock_sh
        msg = {
            "id": 81,
            "type": f"{DOMAIN}/scan_barcode",
            "barcode": "123456",
            "action": "decrement",
            "amount": 1.0,
            "location": "Garage",
            "batch_id": "b1",
        }

        await _run(ws_scan_barcode, hass_mock, mock_connection, msg)

        mock_sh.quantity_service.async_scan_barcode.assert_awaited_once_with(
            barcode="123456",
            action="decrement",
            amount=1.0,
            inventory_id=None,
            price=None,
            location="Garage",
            batch_id="b1",
        )

    async def test_scan_no_service_handler(
        self, hass_mock: MagicMock, mock_connection: MagicMock
    ) -> None:
        """Returns an error when the service handler is not yet available."""
        msg = {
            "id": 82,
            "type": f"{DOMAIN}/scan_barcode",
            "barcode": "123456",
            "action": "lookup",
        }

        await _run(ws_scan_barcode, hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(
            82, "no_inventories", "No inventories configured"
        )

    async def test_scan_error_forwarded(
        self, hass_mock: MagicMock, mock_connection: MagicMock
    ) -> None:
        mock_sh = _make_mock_service_handler(
            scan_error=ServiceValidationError(
                'No item found for barcode "000"',
                translation_domain=DOMAIN,
                translation_key="barcode_not_found",
                translation_placeholders={"barcode": "000"},
            )
        )
        hass_mock.data[DOMAIN].service_handler = mock_sh
        msg = {
            "id": 83,
            "type": f"{DOMAIN}/scan_barcode",
            "barcode": "000",
            "action": "increment",
        }

        await _run(ws_scan_barcode, hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(
            83,
            "scan_failed",
            'No item found for barcode "000"',
            translation_key="barcode_not_found",
            translation_domain=DOMAIN,
            translation_placeholders={"barcode": "000"},
        )

    async def test_scan_unexpected_error_is_left_to_home_assistant(
        self, hass_mock: MagicMock, mock_connection: MagicMock
    ) -> None:
        error = RuntimeError("db gone")
        hass_mock.data[DOMAIN].service_handler = _make_mock_service_handler(scan_error=error)
        msg = {"id": 84, "type": f"{DOMAIN}/scan_barcode", "barcode": "1", "action": "increment"}

        await _run(ws_scan_barcode, hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_not_called()
        mock_connection.async_handle_exception.assert_called_once_with(msg, error)


class TestHandleLookupBarcodeProduct:
    async def test_existing_item_skips_external_lookup(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        mock_coordinator_ws.hub.async_lookup_by_barcode = AsyncMock(
            return_value=[
                {"name": "Milk", "description": "Whole milk", "category": "Dairy", "unit": "L"}
            ]
        )
        hass_mock.data[DOMAIN].coordinators["inv1"] = mock_coordinator_ws
        hass_mock.data[DOMAIN].hub = mock_coordinator_ws.hub

        with patch(
            "custom_components.simple_inventory.websocket_api.async_lookup_barcode_all_providers",
            new_callable=AsyncMock,
        ) as mock_external:
            msg = {"id": 90, "type": f"{DOMAIN}/lookup_barcode_product", "barcode": "123456"}
            await _run(ws_lookup_barcode_product, hass_mock, mock_connection, msg)

        mock_external.assert_not_called()
        mock_connection.send_result.assert_called_once_with(
            90,
            {
                "barcode": "123456",
                "results": [
                    {
                        "provider": "inventory",
                        "found": True,
                        "product": {
                            "name": "Milk",
                            "description": "Whole milk",
                            "category": "Dairy",
                            "unit": "L",
                        },
                    }
                ],
            },
        )

    async def test_external_lookup_when_no_existing_item(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        mock_coordinator_ws.hub.async_lookup_by_barcode = AsyncMock(return_value=[])
        hass_mock.data[DOMAIN].coordinators["inv1"] = mock_coordinator_ws
        hass_mock.data[DOMAIN].hub = mock_coordinator_ws.hub

        results = [
            {"provider": "openfoodfacts", "found": True, "product": {"name": "Tomato Soup"}},
            {"provider": "openbeautyfacts", "found": False},
            {"provider": "openpetfoodfacts", "found": False},
        ]

        with patch(
            "custom_components.simple_inventory.websocket_api.async_lookup_barcode_all_providers",
            new_callable=AsyncMock,
            return_value=results,
        ):
            msg = {"id": 90, "type": f"{DOMAIN}/lookup_barcode_product", "barcode": "123456"}
            await _run(ws_lookup_barcode_product, hass_mock, mock_connection, msg)

        mock_connection.send_result.assert_called_once_with(
            90, {"barcode": "123456", "results": results}
        )

    async def test_external_lookup_when_no_coordinators(
        self, hass_mock: MagicMock, mock_connection: MagicMock
    ) -> None:
        results = [
            {"provider": "openfoodfacts", "found": False},
            {"provider": "openbeautyfacts", "found": False},
            {"provider": "openpetfoodfacts", "found": False},
        ]

        with patch(
            "custom_components.simple_inventory.websocket_api.async_lookup_barcode_all_providers",
            new_callable=AsyncMock,
            return_value=results,
        ):
            msg = {"id": 91, "type": f"{DOMAIN}/lookup_barcode_product", "barcode": "000000"}
            await _run(ws_lookup_barcode_product, hass_mock, mock_connection, msg)

        mock_connection.send_result.assert_called_once_with(
            91, {"barcode": "000000", "results": results}
        )

    async def test_external_lookup_error(
        self, hass_mock: MagicMock, mock_connection: MagicMock
    ) -> None:
        with patch(
            "custom_components.simple_inventory.websocket_api.async_lookup_barcode_all_providers",
            new_callable=AsyncMock,
            side_effect=RuntimeError("provider timeout"),
        ):
            msg = {"id": 92, "type": f"{DOMAIN}/lookup_barcode_product", "barcode": "123456"}
            await _run(ws_lookup_barcode_product, hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(
            92, "lookup_barcode_product_failed", "provider timeout"
        )


class TestHandleGetBarcodeProviderConfig:
    async def test_returns_config(self, hass_mock: MagicMock, mock_connection: MagicMock) -> None:
        mock_repo = MagicMock()
        mock_repo.get_barcode_provider_config = AsyncMock(
            return_value={"provider": "openfoodfacts"}
        )
        hass_mock.data[DOMAIN].repository = mock_repo

        msg = {"id": 100, "type": f"{DOMAIN}/get_barcode_provider_config"}
        await _run(ws_get_barcode_provider_config, hass_mock, mock_connection, msg)

        mock_connection.send_result.assert_called_once_with(100, {"provider": "openfoodfacts"})

    async def test_no_repository_returns_empty(
        self, hass_mock: MagicMock, mock_connection: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN].repository = None

        msg = {"id": 101, "type": f"{DOMAIN}/get_barcode_provider_config"}
        await _run(ws_get_barcode_provider_config, hass_mock, mock_connection, msg)

        mock_connection.send_result.assert_called_once_with(101, {})

    async def test_repository_error(self, hass_mock: MagicMock, mock_connection: MagicMock) -> None:
        mock_repo = MagicMock()
        mock_repo.get_barcode_provider_config = AsyncMock(side_effect=RuntimeError("db error"))
        hass_mock.data[DOMAIN].repository = mock_repo

        msg = {"id": 102, "type": f"{DOMAIN}/get_barcode_provider_config"}
        await _run(ws_get_barcode_provider_config, hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(
            102, "get_barcode_provider_config_failed", "db error"
        )


class TestHandleSetBarcodeProviderConfig:
    async def test_sets_provider(self, hass_mock: MagicMock, mock_connection: MagicMock) -> None:
        mock_repo = MagicMock()
        mock_repo.set_barcode_provider_config = AsyncMock()
        hass_mock.data[DOMAIN].repository = mock_repo

        msg = {
            "id": 110,
            "type": f"{DOMAIN}/set_barcode_provider_config",
            "provider": "openfoodfacts",
        }
        await _run(ws_set_barcode_provider_config, hass_mock, mock_connection, msg)

        mock_repo.set_barcode_provider_config.assert_awaited_once_with(
            {"provider": "openfoodfacts"}
        )
        mock_connection.send_result.assert_called_once_with(110, {"provider": "openfoodfacts"})

    async def test_no_repository_sends_error(
        self, hass_mock: MagicMock, mock_connection: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN].repository = None

        msg = {
            "id": 111,
            "type": f"{DOMAIN}/set_barcode_provider_config",
            "provider": "openfoodfacts",
        }
        await _run(ws_set_barcode_provider_config, hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(
            111, "no_repository", "Repository not available"
        )

    async def test_repository_error(self, hass_mock: MagicMock, mock_connection: MagicMock) -> None:
        mock_repo = MagicMock()
        mock_repo.set_barcode_provider_config = AsyncMock(side_effect=RuntimeError("db error"))
        hass_mock.data[DOMAIN].repository = mock_repo

        msg = {
            "id": 112,
            "type": f"{DOMAIN}/set_barcode_provider_config",
            "provider": "openfoodfacts",
        }
        await _run(ws_set_barcode_provider_config, hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(
            112, "set_barcode_provider_config_failed", "db error"
        )


class TestScanBarcodeSchema:
    """Validated through the real decorated schema HA applies to incoming messages."""

    @staticmethod
    def _validate(**fields: Any) -> dict[str, Any]:
        msg = {"id": 1, "type": f"{DOMAIN}/scan_barcode", "barcode": "123", **fields}
        return cast(dict[str, Any], ws_scan_barcode._ws_schema(msg))  # type: ignore[attr-defined]

    def test_whole_number_amount_and_price_coerced(self) -> None:
        # JS clients serialise 2.0 as 2; the schema must accept it.
        result = self._validate(action="increment", amount=2, price=3)
        assert result["amount"] == 2.0
        assert isinstance(result["amount"], float)
        assert result["price"] == 3.0
        assert isinstance(result["price"], float)

    def test_amount_defaults_to_one(self) -> None:
        assert self._validate(action="decrement")["amount"] == 1.0

    @pytest.mark.parametrize("amount", [0, 0.0, -1])
    def test_non_positive_amount_rejected(self, amount: float) -> None:
        with pytest.raises(vol.Invalid):
            self._validate(action="decrement", amount=amount)

    def test_negative_price_rejected(self) -> None:
        with pytest.raises(vol.Invalid):
            self._validate(action="increment", price=-0.5)

    def test_batch_fields_accepted(self) -> None:
        result = self._validate(
            action="increment",
            expiry_date="2026-11-01",
            location="Fridge",
            purchased_at="2026-10-25",
        )
        assert (result["expiry_date"], result["location"], result["purchased_at"]) == (
            "2026-11-01",
            "Fridge",
            "2026-10-25",
        )

    def test_batch_dates_must_be_iso(self) -> None:
        with pytest.raises(vol.Invalid):
            self._validate(action="increment", expiry_date="11/01/2026")

    def test_blank_purchased_at_rejected(self) -> None:
        with pytest.raises(vol.Invalid):
            self._validate(action="increment", purchased_at="")


class TestGetHistorySchema:
    @staticmethod
    def _validate(**fields: Any) -> dict[str, Any]:
        msg = {"id": 1, "type": f"{DOMAIN}/get_history", "inventory_id": "inv1", **fields}
        return cast(dict[str, Any], ws_get_history._ws_schema(msg))  # type: ignore[attr-defined]

    @pytest.mark.parametrize("field", ["limit", "offset"])
    def test_negative_rejected(self, field: str) -> None:
        with pytest.raises(vol.Invalid):
            self._validate(**{field: -1})

    def test_defaults(self) -> None:
        result = self._validate()
        assert result["limit"] == 100
        assert result["offset"] == 0


class TestImportSchema:
    @staticmethod
    def _validate(**fields: Any) -> dict[str, Any]:
        msg = {"id": 1, "type": f"{DOMAIN}/import", "inventory_id": "inv1", **fields}
        return cast(dict[str, Any], ws_import._ws_schema(msg))  # type: ignore[attr-defined]

    def test_json_string_is_parsed(self) -> None:
        result = self._validate(data='{"items": [{"name": "milk"}]}')
        assert result["data"] == {"items": [{"name": "milk"}]}

    def test_json_string_list_is_parsed(self) -> None:
        result = self._validate(data='[{"name": "milk"}]', format="json")
        assert result["data"] == [{"name": "milk"}]

    def test_invalid_json_string_rejected(self) -> None:
        with pytest.raises(vol.Invalid, match="Invalid JSON"):
            self._validate(data="{not json")

    def test_json_scalar_string_rejected(self) -> None:
        with pytest.raises(vol.Invalid):
            self._validate(data='"just a string"')

    def test_csv_requires_string(self) -> None:
        with pytest.raises(vol.Invalid):
            self._validate(data={"items": []}, format="csv")

    def test_csv_string_passes_through(self) -> None:
        result = self._validate(data="name,quantity\nmilk,1\n", format="csv")
        assert result["data"] == "name,quantity\nmilk,1\n"

    async def test_parsed_json_string_reaches_coordinator_as_object(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN].coordinators = {"inv1": mock_coordinator_ws}
        msg = self._validate(data='{"items": []}')
        await _run(ws_import, hass_mock, mock_connection, msg)
        mock_coordinator_ws.async_import_inventory.assert_awaited_once_with(
            "inv1", {"items": []}, "json", "skip", dry_run=False
        )

    async def test_dry_run_true_reaches_coordinator(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN].coordinators = {"inv1": mock_coordinator_ws}
        msg = self._validate(data='{"items": []}', dry_run=True)
        await _run(ws_import, hass_mock, mock_connection, msg)
        mock_coordinator_ws.async_import_inventory.assert_awaited_once_with(
            "inv1", {"items": []}, "json", "skip", dry_run=True
        )

    def test_dry_run_defaults_to_false(self) -> None:
        result = self._validate(data="{}")
        assert result["dry_run"] is False


class TestSetBarcodeProviderConfigCommand:
    def test_unknown_provider_rejected_by_schema(self) -> None:
        msg = {"id": 1, "type": f"{DOMAIN}/set_barcode_provider_config", "provider": "bogus"}
        with pytest.raises(vol.Invalid):
            ws_set_barcode_provider_config._ws_schema(msg)  # type: ignore[attr-defined]

    def test_registered_provider_accepted_by_schema(self) -> None:
        msg = {"id": 1, "type": f"{DOMAIN}/set_barcode_provider_config", "provider": "upcitemdb"}
        result = ws_set_barcode_provider_config._ws_schema(msg)  # type: ignore[attr-defined]
        assert result["provider"] == "upcitemdb"

    def test_non_admin_is_unauthorized(self, hass_mock: MagicMock) -> None:
        connection = MagicMock()
        connection.user.is_admin = False
        msg = {"id": 1, "type": f"{DOMAIN}/set_barcode_provider_config", "provider": "upcitemdb"}
        with pytest.raises(Unauthorized):
            ws_set_barcode_provider_config(hass_mock, connection, msg)


class TestGetInfoCommand:
    """`simple_inventory/get_info` exercised through the real WS server and schema."""

    async def test_get_info_reports_version_api_version_and_features(
        self, hass: HomeAssistant, hass_ws_client: WebSocketGenerator
    ) -> None:
        integration = MagicMock()
        integration.version = AwesomeVersion("0.7.0")
        async_register_websocket_commands(hass)
        client = await hass_ws_client(hass)

        with patch(
            "custom_components.simple_inventory.websocket_api.async_get_integration",
            AsyncMock(return_value=integration),
        ) as get_integration:
            await client.send_json_auto_id({"type": f"{DOMAIN}/get_info"})
            msg = await client.receive_json()

        get_integration.assert_awaited_once_with(hass, DOMAIN)
        assert msg["success"] is True
        assert msg["result"] == {
            "version": "0.7.0",
            "api_version": 3,
            "features": [
                "batches",
                "transfers",
                "item_icons",
                "item_images",
                "panel",
                "tile_images",
                "search",
                "overview",
            ],
        }

    async def test_get_info_advertises_every_feature(
        self,
        hass: HomeAssistant,
        hass_ws_client: WebSocketGenerator,
        enable_custom_integrations: None,
    ) -> None:
        async_register_websocket_commands(hass)
        client = await hass_ws_client(hass)
        await client.send_json_auto_id({"type": f"{DOMAIN}/get_info"})
        msg = await client.receive_json()
        assert msg["result"]["api_version"] == 3
        assert msg["result"]["features"] == [
            "batches",
            "transfers",
            "item_icons",
            "item_images",
            "panel",
            "tile_images",
            "search",
            "overview",
        ]

    async def test_get_info_reports_feature_list(
        self, hass: HomeAssistant, hass_ws_client: WebSocketGenerator
    ) -> None:
        integration = MagicMock()
        integration.version = AwesomeVersion("0.8.0")
        async_register_websocket_commands(hass)
        client = await hass_ws_client(hass)

        with (
            patch(
                "custom_components.simple_inventory.websocket_api.async_get_integration",
                AsyncMock(return_value=integration),
            ),
            patch("custom_components.simple_inventory.websocket_api.FEATURES", ("batches",)),
        ):
            await client.send_json_auto_id({"type": f"{DOMAIN}/get_info"})
            msg = await client.receive_json()

        assert msg["result"]["features"] == ["batches"]

    async def test_get_info_uses_manifest_version(
        self,
        hass: HomeAssistant,
        hass_ws_client: WebSocketGenerator,
        enable_custom_integrations: None,
    ) -> None:
        manifest = json.loads(
            (
                Path(__file__).parent.parent / "custom_components" / DOMAIN / "manifest.json"
            ).read_text(encoding="utf-8")
        )
        async_register_websocket_commands(hass)
        client = await hass_ws_client(hass)

        await client.send_json_auto_id({"type": f"{DOMAIN}/get_info"})
        msg = await client.receive_json()

        assert msg["result"]["version"] == manifest["version"]
        assert msg["result"]["api_version"] == API_VERSION

    async def test_get_info_rejects_unknown_arguments(
        self, hass: HomeAssistant, hass_ws_client: WebSocketGenerator
    ) -> None:
        async_register_websocket_commands(hass)
        client = await hass_ws_client(hass)

        await client.send_json_auto_id({"type": f"{DOMAIN}/get_info", "bogus": 1})
        msg = await client.receive_json()

        assert msg["success"] is False
        assert msg["error"]["code"] == "invalid_format"

    async def test_get_info_is_available_to_non_admin_users(
        self,
        hass: HomeAssistant,
        hass_ws_client: WebSocketGenerator,
        hass_read_only_access_token: str,
        enable_custom_integrations: None,
    ) -> None:
        async_register_websocket_commands(hass)
        client = await hass_ws_client(hass, hass_read_only_access_token)

        await client.send_json_auto_id({"type": f"{DOMAIN}/get_info"})
        msg = await client.receive_json()

        assert msg["success"] is True


class TestListInventories:
    """`simple_inventory/list_inventories` exercised through the real WS server."""

    async def test_lists_inventories_sorted_with_sensor_entity_ids(
        self, hass: HomeAssistant, hass_ws_client: WebSocketGenerator
    ) -> None:
        registry = er.async_get(hass)
        pantry = MockConfigEntry(
            domain=DOMAIN,
            entry_id="pantry_id",
            title="Pantry",
            data={
                "name": "pantry",
                "icon": "mdi:cupboard",
                "description": "Dry goods",
                "entry_type": "inventory",
            },
        )
        kitchen = MockConfigEntry(
            domain=DOMAIN,
            entry_id="kitchen_id",
            title="Kitchen",
            data={
                "name": "Kitchen",
                "icon": "mdi:fridge",
                "description": "",
                "entry_type": "inventory",
            },
        )
        global_entry = MockConfigEntry(
            domain=DOMAIN,
            entry_id="global_entry",
            data={"entry_type": "global", "name": "All Items Expiring Soon"},
        )
        for entry in (pantry, kitchen, global_entry):
            entry.add_to_hass(hass)
        registry.async_get_or_create(
            "sensor", DOMAIN, "inventory_kitchen_id", suggested_object_id="kitchen_inventory"
        )
        # A renamed entity id still resolves through the registry.
        registry.async_get_or_create(
            "sensor", DOMAIN, "inventory_pantry_id", suggested_object_id="dry_store"
        )
        async_register_websocket_commands(hass)
        client = await hass_ws_client(hass)

        await client.send_json_auto_id({"type": f"{DOMAIN}/list_inventories"})
        msg = await client.receive_json()

        assert msg["success"] is True
        assert msg["result"] == {
            "inventories": [
                {
                    "id": "kitchen_id",
                    "name": "Kitchen",
                    "icon": "mdi:fridge",
                    "description": "",
                    "entity_id": "sensor.kitchen_inventory",
                },
                {
                    "id": "pantry_id",
                    "name": "pantry",
                    "icon": "mdi:cupboard",
                    "description": "Dry goods",
                    "entity_id": "sensor.dry_store",
                },
            ]
        }

    async def test_inventory_without_sensor_has_null_entity_id(
        self, hass: HomeAssistant, hass_ws_client: WebSocketGenerator
    ) -> None:
        MockConfigEntry(
            domain=DOMAIN,
            entry_id="garage_id",
            title="Garage",
            data={"name": "Garage", "entry_type": "inventory"},
        ).add_to_hass(hass)
        async_register_websocket_commands(hass)
        client = await hass_ws_client(hass)

        await client.send_json_auto_id({"type": f"{DOMAIN}/list_inventories"})
        msg = await client.receive_json()

        assert msg["result"] == {
            "inventories": [
                {
                    "id": "garage_id",
                    "name": "Garage",
                    "icon": "",
                    "description": "",
                    "entity_id": None,
                }
            ]
        }

    async def test_disabled_inventory_is_excluded_but_not_loaded_is_listed(
        self, hass: HomeAssistant, hass_ws_client: WebSocketGenerator
    ) -> None:
        MockConfigEntry(
            domain=DOMAIN,
            entry_id="attic_id",
            title="Attic",
            data={"name": "Attic", "entry_type": "inventory"},
            disabled_by=ConfigEntryDisabler.USER,
        ).add_to_hass(hass)
        MockConfigEntry(
            domain=DOMAIN,
            entry_id="garage_id",
            title="Garage",
            data={"name": "Garage", "entry_type": "inventory"},
        ).add_to_hass(hass)
        async_register_websocket_commands(hass)
        client = await hass_ws_client(hass)

        await client.send_json_auto_id({"type": f"{DOMAIN}/list_inventories"})
        msg = await client.receive_json()

        assert [inventory["id"] for inventory in msg["result"]["inventories"]] == ["garage_id"]


_SEARCH_SEED = """
INSERT INTO items (id, inventory_id, name, description, unit)
VALUES ('k_butter', 'kitchen', 'Butter', '', ''),
       ('k_peanut', 'kitchen', 'Peanut butter', '', ''),
       ('k_choc', 'kitchen', 'Chocolate', '', ''),
       ('k_milk', 'kitchen', 'Milk', '', ''),
       ('k_bread', 'kitchen', 'Bread', '', ''),
       ('k_rice', 'kitchen', 'Rice', 'long grain', 'kg'),
       ('k_flour', 'kitchen', 'Flour', '', ''),
       ('g_butter', 'shed', 'Butter', '', ''),
       ('a_butter', 'attic', 'Butter', '', '');
INSERT INTO item_aliases (item_id, inventory_id, alias) VALUES ('k_choc', 'kitchen', 'cocoa');
INSERT INTO item_barcodes (item_id, inventory_id, barcode)
VALUES ('k_milk', 'kitchen', '4006381333931');
INSERT INTO categories (id, name) VALUES (1, 'Bakery');
INSERT INTO item_categories (item_id, category_id) VALUES ('k_bread', 1);
INSERT INTO locations (id, inventory_id, name) VALUES (1, 'kitchen', 'Larder');
INSERT INTO item_locations (item_id, location_id) VALUES ('k_flour', 1);
"""


class TestSearch:
    """`simple_inventory/search` against a real setup with seeded inventories."""

    @pytest.fixture
    async def client(
        self,
        hass: HomeAssistant,
        tmp_path: Path,
        hass_ws_client: WebSocketGenerator,
        enable_custom_integrations: None,
    ) -> Any:
        async with integration_env(hass, tmp_path) as hass_env:
            async with open_database(hass_env) as repository:
                for inventory_id, name in (
                    ("kitchen", "Kitchen"),
                    ("shed", "Garage"),
                    ("attic", "Attic"),
                ):
                    await repository.upsert_inventory(inventory_id, name, entry_type="inventory")
                conn = repository._connection()
                await conn.executescript(_SEARCH_SEED)
                await conn.commit()
            kitchen = add_entry(hass_env, "kitchen", "Kitchen")
            # Id order (kitchen < shed) differs from name order (Garage < Kitchen).
            add_entry(hass_env, "shed", "Garage")
            MockConfigEntry(
                domain=DOMAIN,
                entry_id="attic",
                title="Attic",
                data={"name": "Attic", "entry_type": "inventory"},
                disabled_by=ConfigEntryDisabler.USER,
            ).add_to_hass(hass_env)
            await setup_entry(hass_env, kitchen)
            yield await hass_ws_client(hass_env)

    @staticmethod
    async def _call(client: Any, **data: Any) -> dict[str, Any]:
        await client.send_json_auto_id({"type": f"{DOMAIN}/search", **data})
        return cast(dict[str, Any], await client.receive_json())

    async def _listed(self, client: Any, inventory_id: str) -> dict[str, dict[str, Any]]:
        msg = await self._call_type(client, "list_items", inventory_id=inventory_id)
        return {item["id"]: item for item in msg["result"]["items"]}

    @staticmethod
    async def _call_type(client: Any, command: str, **data: Any) -> dict[str, Any]:
        await client.send_json_auto_id({"type": f"{DOMAIN}/{command}", **data})
        return cast(dict[str, Any], await client.receive_json())

    async def test_results_are_list_items_dicts_in_rank_order(self, client: Any) -> None:
        msg = await self._call(client, query="butter")
        kitchen = await self._listed(client, "kitchen")
        garage = await self._listed(client, "shed")

        assert msg["success"] is True
        assert msg["result"] == {
            "items": [
                {
                    **garage["g_butter"],
                    "inventory_id": "shed",
                    "inventory_name": "Garage",
                    "matched": "name",
                },
                {
                    **kitchen["k_butter"],
                    "inventory_id": "kitchen",
                    "inventory_name": "Kitchen",
                    "matched": "name",
                },
                {
                    **kitchen["k_peanut"],
                    "inventory_id": "kitchen",
                    "inventory_name": "Kitchen",
                    "matched": "name",
                },
            ],
            "truncated": False,
        }

    @pytest.mark.parametrize(
        ("query", "name", "matched"),
        [
            ("cocoa", "Chocolate", "alias"),
            ("63813", "Milk", "barcode"),
            ("bakery", "Bread", "category"),
            ("larder", "Flour", "location"),
            ("long grain", "Rice", "description"),
            ("kg", "Rice", "unit"),
        ],
    )
    async def test_matched_reason(self, client: Any, query: str, name: str, matched: str) -> None:
        msg = await self._call(client, query=query)

        assert [(item["name"], item["matched"]) for item in msg["result"]["items"]] == [
            (name, matched)
        ]

    async def test_limit_truncates(self, client: Any) -> None:
        msg = await self._call(client, query="butter", limit=1)

        assert [item["id"] for item in msg["result"]["items"]] == ["g_butter"]
        assert msg["result"]["truncated"] is True

    async def test_disabled_inventory_excluded(self, client: Any) -> None:
        msg = await self._call(client, query="butter")

        assert "attic" not in {item["inventory_id"] for item in msg["result"]["items"]}

    async def test_blank_query_returns_nothing(self, client: Any) -> None:
        msg = await self._call(client, query="   ")

        assert msg["result"] == {"items": [], "truncated": False}

    @pytest.mark.parametrize(
        "data",
        [{"query": "x" * 101}, {"query": "butter", "limit": 0}, {"query": "butter", "limit": 201}],
    )
    async def test_invalid_arguments(self, client: Any, data: dict[str, Any]) -> None:
        msg = await self._call(client, **data)

        assert msg["success"] is False
        assert msg["error"]["code"] == "invalid_format"


class TestOverview:
    """`simple_inventory/overview` against a real setup."""

    @pytest.fixture
    async def setup(
        self,
        hass: HomeAssistant,
        tmp_path: Path,
        hass_ws_client: WebSocketGenerator,
        enable_custom_integrations: None,
    ) -> Any:
        async with integration_env(hass, tmp_path) as hass_env:
            async with open_database(hass_env) as repository:
                for inventory_id, name in (
                    ("kitchen", "Kitchen"),
                    ("shed", "Garage"),
                    ("attic", "Attic"),
                ):
                    await repository.upsert_inventory(inventory_id, name, entry_type="inventory")
                conn = repository._connection()
                await conn.executescript("""
                    INSERT INTO items (id, inventory_id, name, quantity)
                    VALUES ('k_milk', 'kitchen', 'Milk', 0),
                           ('g_oil', 'shed', 'Oil', 0),
                           ('a_box', 'attic', 'Box', 0);
                    """)
                await conn.commit()
            kitchen = add_entry(hass_env, "kitchen", "Kitchen")
            add_entry(hass_env, "shed", "Garage")
            MockConfigEntry(
                domain=DOMAIN,
                entry_id="attic",
                title="Attic",
                data={"name": "Attic", "entry_type": "inventory"},
                disabled_by=ConfigEntryDisabler.USER,
            ).add_to_hass(hass_env)
            await setup_entry(hass_env, kitchen)
            yield hass_env, await hass_ws_client(hass_env)

    async def test_returns_the_overview_of_enabled_inventories(self, setup: Any) -> None:
        hass, client = setup
        coordinators: dict[str, Any] = hass.data[DOMAIN].coordinators
        expected = await coordinators["kitchen"].hub.async_overview(
            {"kitchen": "Kitchen", "shed": "Garage"}
        )

        await client.send_json_auto_id({"type": f"{DOMAIN}/overview"})
        msg = await client.receive_json()

        assert msg["success"] is True
        assert msg["result"] == expected
        assert [summary["id"] for summary in msg["result"]["inventories"]] == ["shed", "kitchen"]
        assert [entry["id"] for entry in msg["result"]["out_of_stock"]] == ["k_milk", "g_oil"]

    async def test_disabled_inventory_excluded(self, setup: Any) -> None:
        _hass, client = setup

        await client.send_json_auto_id({"type": f"{DOMAIN}/overview"})
        msg = await client.receive_json()

        assert "attic" not in {summary["id"] for summary in msg["result"]["inventories"]}
        assert "a_box" not in {entry["id"] for entry in msg["result"]["out_of_stock"]}

    async def test_rejects_arguments(self, setup: Any) -> None:
        _hass, client = setup

        await client.send_json_auto_id({"type": f"{DOMAIN}/overview", "inventory_id": "kitchen"})
        msg = await client.receive_json()

        assert msg["error"]["code"] == "invalid_format"


async def test_overview_without_loaded_inventories_is_empty(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    async_register_websocket_commands(hass)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id({"type": f"{DOMAIN}/overview"})
    msg = await client.receive_json()

    assert msg["result"] == {
        "inventories": [],
        "expired": [],
        "expiring_soon": [],
        "out_of_stock": [],
        "low_stock": [],
    }
