"""Tests for the WebSocket API."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.simple_inventory.const import DOMAIN
from custom_components.simple_inventory.websocket_api import (
    _handle_export,
    _handle_get_barcode_provider_config,
    _handle_get_history,
    _handle_get_inventory_consumption_rates,
    _handle_get_item,
    _handle_get_item_consumption_rates,
    _handle_import,
    _handle_list_items,
    _handle_lookup_barcode_product,
    _handle_lookup_by_barcode,
    _handle_scan_barcode,
    _handle_set_barcode_provider_config,
    _handle_subscribe,
)


@pytest.fixture
def mock_connection() -> MagicMock:
    """Create a mock WebSocket connection."""
    conn = MagicMock()
    conn.send_result = MagicMock()
    conn.send_error = MagicMock()
    conn.send_event = MagicMock()
    conn.subscriptions = {}
    return conn


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
    coordinator.async_lookup_by_barcode = AsyncMock(
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
        hass_mock.data[DOMAIN]["coordinators"]["inv1"] = mock_coordinator_ws
        msg = {"id": 1, "type": f"{DOMAIN}/list_items", "inventory_id": "inv1"}

        await _handle_list_items(hass_mock, mock_connection, msg)

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

        await _handle_list_items(hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(
            1, "inventory_not_found", "Inventory 'missing' not found"
        )


class TestHandleGetItem:
    async def test_get_item_success(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN]["coordinators"]["inv1"] = mock_coordinator_ws
        msg = {
            "id": 2,
            "type": f"{DOMAIN}/get_item",
            "inventory_id": "inv1",
            "name": "milk",
        }

        await _handle_get_item(hass_mock, mock_connection, msg)

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

        await _handle_get_item(hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(
            2, "inventory_not_found", "Inventory 'missing' not found"
        )

    async def test_get_item_not_found(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN]["coordinators"]["inv1"] = mock_coordinator_ws
        mock_coordinator_ws.async_get_item.return_value = None
        msg = {
            "id": 3,
            "type": f"{DOMAIN}/get_item",
            "inventory_id": "inv1",
            "name": "nonexistent",
        }

        await _handle_get_item(hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(
            3,
            "item_not_found",
            "Item 'nonexistent' not found in inventory 'inv1'",
        )


class TestHandleSubscribe:
    def test_subscribe_with_inventory_id(
        self, hass_mock: MagicMock, mock_connection: MagicMock
    ) -> None:
        msg = {
            "id": 4,
            "type": f"{DOMAIN}/subscribe",
            "inventory_id": "inv1",
        }

        _handle_subscribe(hass_mock, mock_connection, msg)

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

        _handle_subscribe(hass_mock, mock_connection, msg)

        hass_mock.bus.async_listen.assert_called_once()
        event_type = hass_mock.bus.async_listen.call_args[0][0]
        assert event_type == f"{DOMAIN}_updated"
        assert 5 in mock_connection.subscriptions
        mock_connection.send_result.assert_called_once_with(5)

    async def test_subscribe_forwards_events(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN]["coordinators"]["inv1"] = mock_coordinator_ws
        msg = {
            "id": 6,
            "type": f"{DOMAIN}/subscribe",
            "inventory_id": "inv1",
        }

        _handle_subscribe(hass_mock, mock_connection, msg)

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


class TestHandleGetHistory:
    async def test_get_inventory_history(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN]["coordinators"]["inv1"] = mock_coordinator_ws
        msg = {
            "id": 20,
            "type": f"{DOMAIN}/get_history",
            "inventory_id": "inv1",
        }

        await _handle_get_history(hass_mock, mock_connection, msg)

        mock_coordinator_ws.async_get_inventory_history.assert_awaited_once()
        mock_connection.send_result.assert_called_once()
        result = mock_connection.send_result.call_args[0][1]
        assert "events" in result

    async def test_get_item_history(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN]["coordinators"]["inv1"] = mock_coordinator_ws
        msg = {
            "id": 21,
            "type": f"{DOMAIN}/get_history",
            "inventory_id": "inv1",
            "item_name": "milk",
        }

        await _handle_get_history(hass_mock, mock_connection, msg)

        mock_coordinator_ws.async_get_item_history.assert_awaited_once()

    async def test_get_history_inventory_not_found(
        self, hass_mock: MagicMock, mock_connection: MagicMock
    ) -> None:
        msg = {
            "id": 22,
            "type": f"{DOMAIN}/get_history",
            "inventory_id": "missing",
        }

        await _handle_get_history(hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once()


class TestHandleExport:
    async def test_export_success(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN]["coordinators"]["inv1"] = mock_coordinator_ws
        msg = {
            "id": 30,
            "type": f"{DOMAIN}/export",
            "inventory_id": "inv1",
            "format": "json",
        }

        await _handle_export(hass_mock, mock_connection, msg)

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

        await _handle_export(hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once()


class TestHandleImport:
    async def test_import_success(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN]["coordinators"]["inv1"] = mock_coordinator_ws
        msg = {
            "id": 40,
            "type": f"{DOMAIN}/import",
            "inventory_id": "inv1",
            "data": {"items": [{"name": "Apple", "quantity": 5}]},
            "format": "json",
            "merge_strategy": "skip",
        }

        await _handle_import(hass_mock, mock_connection, msg)

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

        await _handle_import(hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once()


class TestHandleGetItemConsumptionRates:
    async def test_success(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN]["coordinators"]["inv1"] = mock_coordinator_ws
        msg = {
            "id": 50,
            "type": f"{DOMAIN}/get_item_consumption_rates",
            "inventory_id": "inv1",
            "item_name": "milk",
        }

        await _handle_get_item_consumption_rates(hass_mock, mock_connection, msg)

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

        await _handle_get_item_consumption_rates(hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(
            51, "inventory_not_found", "Inventory 'missing' not found"
        )

    async def test_item_not_found(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN]["coordinators"]["inv1"] = mock_coordinator_ws
        mock_coordinator_ws.async_get_item_consumption_rates.return_value = None
        msg = {
            "id": 52,
            "type": f"{DOMAIN}/get_item_consumption_rates",
            "inventory_id": "inv1",
            "item_name": "nonexistent",
        }

        await _handle_get_item_consumption_rates(hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(
            52,
            "item_not_found",
            "Item 'nonexistent' not found in inventory 'inv1'",
        )

    async def test_window_days_passed_through(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN]["coordinators"]["inv1"] = mock_coordinator_ws
        msg = {
            "id": 53,
            "type": f"{DOMAIN}/get_item_consumption_rates",
            "inventory_id": "inv1",
            "item_name": "milk",
            "window_days": 30,
        }

        await _handle_get_item_consumption_rates(hass_mock, mock_connection, msg)

        mock_coordinator_ws.async_get_item_consumption_rates.assert_awaited_once_with(
            "inv1", "milk", window_days=30
        )


class TestHandleGetInventoryConsumptionRates:
    async def test_success(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN]["coordinators"]["inv1"] = mock_coordinator_ws
        msg = {
            "id": 60,
            "type": f"{DOMAIN}/get_inventory_consumption_rates",
            "inventory_id": "inv1",
        }

        await _handle_get_inventory_consumption_rates(hass_mock, mock_connection, msg)

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

        await _handle_get_inventory_consumption_rates(hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(
            61, "inventory_not_found", "Inventory 'missing' not found"
        )

    async def test_window_days_passed_through(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN]["coordinators"]["inv1"] = mock_coordinator_ws
        msg = {
            "id": 62,
            "type": f"{DOMAIN}/get_inventory_consumption_rates",
            "inventory_id": "inv1",
            "window_days": 90,
        }

        await _handle_get_inventory_consumption_rates(hass_mock, mock_connection, msg)

        mock_coordinator_ws.async_get_inventory_consumption_rates.assert_awaited_once_with(
            "inv1", window_days=90
        )


class TestHandleLookupByBarcode:
    async def test_lookup_success(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN]["coordinators"]["inv1"] = mock_coordinator_ws
        msg = {"id": 70, "type": f"{DOMAIN}/lookup_by_barcode", "barcode": "123456"}

        await _handle_lookup_by_barcode(hass_mock, mock_connection, msg)

        mock_coordinator_ws.async_lookup_by_barcode.assert_awaited_once_with("123456")
        mock_connection.send_result.assert_called_once()
        result = mock_connection.send_result.call_args[0][1]
        assert "items" in result

    async def test_lookup_no_inventories(
        self, hass_mock: MagicMock, mock_connection: MagicMock
    ) -> None:
        msg = {"id": 71, "type": f"{DOMAIN}/lookup_by_barcode", "barcode": "123456"}

        await _handle_lookup_by_barcode(hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(
            71, "no_inventories", "No inventories configured"
        )


class TestHandleScanBarcode:
    async def test_scan_success(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN]["coordinators"]["inv1"] = mock_coordinator_ws
        msg = {
            "id": 80,
            "type": f"{DOMAIN}/scan_barcode",
            "barcode": "123456",
            "action": "increment",
            "amount": 1.0,
        }

        await _handle_scan_barcode(hass_mock, mock_connection, msg)

        mock_coordinator_ws.async_scan_barcode.assert_awaited_once_with(
            "123456", "increment", 1.0, None, price=None
        )
        mock_connection.send_result.assert_called_once()

    async def test_scan_with_inventory_id(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN]["coordinators"]["inv1"] = mock_coordinator_ws
        msg = {
            "id": 81,
            "type": f"{DOMAIN}/scan_barcode",
            "barcode": "123456",
            "action": "decrement",
            "inventory_id": "inv1",
        }

        await _handle_scan_barcode(hass_mock, mock_connection, msg)

        mock_coordinator_ws.async_scan_barcode.assert_awaited_once()

    async def test_scan_no_inventories(
        self, hass_mock: MagicMock, mock_connection: MagicMock
    ) -> None:
        msg = {
            "id": 82,
            "type": f"{DOMAIN}/scan_barcode",
            "barcode": "123456",
            "action": "lookup",
        }

        await _handle_scan_barcode(hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(
            82, "no_inventories", "No inventories configured"
        )

    async def test_scan_error_forwarded(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN]["coordinators"]["inv1"] = mock_coordinator_ws
        mock_coordinator_ws.async_scan_barcode = AsyncMock(
            side_effect=ValueError("No item found for barcode '000' in any inventory")
        )
        msg = {
            "id": 83,
            "type": f"{DOMAIN}/scan_barcode",
            "barcode": "000",
            "action": "increment",
        }

        await _handle_scan_barcode(hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(
            83, "scan_failed", "No item found for barcode '000' in any inventory"
        )


class TestHandleLookupBarcodeProduct:
    async def test_existing_item_skips_external_lookup(
        self, hass_mock: MagicMock, mock_connection: MagicMock, mock_coordinator_ws: MagicMock
    ) -> None:
        mock_coordinator_ws.async_lookup_by_barcode = AsyncMock(
            return_value=[
                {"name": "Milk", "description": "Whole milk", "category": "Dairy", "unit": "L"}
            ]
        )
        hass_mock.data[DOMAIN]["coordinators"]["inv1"] = mock_coordinator_ws

        with patch(
            "custom_components.simple_inventory.websocket_api.async_lookup_barcode_all_providers",
            new_callable=AsyncMock,
        ) as mock_external:
            msg = {"id": 90, "type": f"{DOMAIN}/lookup_barcode_product", "barcode": "123456"}
            await _handle_lookup_barcode_product(hass_mock, mock_connection, msg)

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
        mock_coordinator_ws.async_lookup_by_barcode = AsyncMock(return_value=[])
        hass_mock.data[DOMAIN]["coordinators"]["inv1"] = mock_coordinator_ws

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
            await _handle_lookup_barcode_product(hass_mock, mock_connection, msg)

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
            await _handle_lookup_barcode_product(hass_mock, mock_connection, msg)

        mock_connection.send_result.assert_called_once_with(
            91, {"barcode": "000000", "results": results}
        )


class TestHandleGetBarcodeProviderConfig:
    async def test_returns_config(self, hass_mock: MagicMock, mock_connection: MagicMock) -> None:
        mock_repo = MagicMock()
        mock_repo.get_barcode_provider_config = AsyncMock(
            return_value={"provider": "openfoodfacts"}
        )
        hass_mock.data[DOMAIN]["repository"] = mock_repo

        msg = {"id": 100, "type": f"{DOMAIN}/get_barcode_provider_config"}
        await _handle_get_barcode_provider_config(hass_mock, mock_connection, msg)

        mock_connection.send_result.assert_called_once_with(100, {"provider": "openfoodfacts"})

    async def test_no_repository_returns_empty(
        self, hass_mock: MagicMock, mock_connection: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN]["repository"] = None

        msg = {"id": 101, "type": f"{DOMAIN}/get_barcode_provider_config"}
        await _handle_get_barcode_provider_config(hass_mock, mock_connection, msg)

        mock_connection.send_result.assert_called_once_with(101, {})


class TestHandleSetBarcodeProviderConfig:
    async def test_sets_provider(self, hass_mock: MagicMock, mock_connection: MagicMock) -> None:
        mock_repo = MagicMock()
        mock_repo.set_barcode_provider_config = AsyncMock()
        hass_mock.data[DOMAIN]["repository"] = mock_repo

        msg = {
            "id": 110,
            "type": f"{DOMAIN}/set_barcode_provider_config",
            "provider": "openfoodfacts",
        }
        await _handle_set_barcode_provider_config(hass_mock, mock_connection, msg)

        mock_repo.set_barcode_provider_config.assert_awaited_once_with(
            {"provider": "openfoodfacts"}
        )
        mock_connection.send_result.assert_called_once_with(110, {"provider": "openfoodfacts"})

    async def test_no_repository_sends_error(
        self, hass_mock: MagicMock, mock_connection: MagicMock
    ) -> None:
        hass_mock.data[DOMAIN]["repository"] = None

        msg = {
            "id": 111,
            "type": f"{DOMAIN}/set_barcode_provider_config",
            "provider": "openfoodfacts",
        }
        await _handle_set_barcode_provider_config(hass_mock, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(
            111, "no_repository", "Repository not available"
        )
