"""Tests for QuantityService."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError

from custom_components.simple_inventory.const import DOMAIN
from custom_components.simple_inventory.services.base_service import BaseServiceHandler
from custom_components.simple_inventory.services.quantity_service import QuantityService


@pytest.fixture
def mock_todo_manager() -> MagicMock:
    todo = MagicMock()
    todo.check_and_add_item = AsyncMock()
    todo.check_and_remove_item = AsyncMock()
    return todo


@pytest.fixture
def mock_coordinator() -> MagicMock:
    coordinator = MagicMock()
    coordinator.async_increment_item = AsyncMock(return_value=True)
    coordinator.async_decrement_item = AsyncMock(return_value=True)
    coordinator.async_get_item = AsyncMock(
        return_value={"quantity": 5, "auto_add_to_list_quantity": 2}
    )
    coordinator.async_save_data = AsyncMock()
    coordinator.async_lookup_by_barcode = AsyncMock(return_value=[])
    return coordinator


@pytest.fixture
def hass_with_coordinator(hass: HomeAssistant, mock_coordinator: MagicMock) -> HomeAssistant:
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["coordinators"] = {"kitchen": mock_coordinator}
    return hass


@pytest.fixture
def quantity_service(
    hass_with_coordinator: HomeAssistant, mock_todo_manager: MagicMock
) -> QuantityService:
    return QuantityService(hass_with_coordinator, mock_todo_manager)


@pytest.fixture
def quantity_service_call() -> ServiceCall:
    call = MagicMock(spec=ServiceCall)
    call.data = {"inventory_id": "kitchen", "name": "milk", "amount": 2}
    call.context.id = "ctx-1"
    return call


@pytest.fixture
def basic_service_call() -> ServiceCall:
    call = MagicMock(spec=ServiceCall)
    call.data = {"inventory_id": "kitchen", "name": "milk"}  # no amount -> default 1
    call.context.id = "ctx-2"
    return call


def test_init(hass_with_coordinator: HomeAssistant, mock_todo_manager: MagicMock) -> None:
    service = QuantityService(hass_with_coordinator, mock_todo_manager)
    assert service.hass is hass_with_coordinator
    assert service.todo_manager is mock_todo_manager


def test_inheritance(quantity_service: QuantityService) -> None:
    assert isinstance(quantity_service, BaseServiceHandler)
    assert hasattr(quantity_service, "_save_and_log_success")
    assert hasattr(quantity_service, "_get_inventory_and_name")
    assert hasattr(quantity_service, "_log_item_not_found")


@pytest.mark.asyncio
async def test_async_increment_item_success(
    quantity_service: QuantityService,
    quantity_service_call: ServiceCall,
    mock_coordinator: MagicMock,
    mock_todo_manager: MagicMock,
) -> None:
    await quantity_service.async_increment_item(quantity_service_call)

    mock_coordinator.async_increment_item.assert_awaited_once_with(
        "kitchen", "milk", 2.0, barcode=None, price=None
    )
    mock_coordinator.async_get_item.assert_awaited_once_with("kitchen", "milk")
    mock_todo_manager.check_and_remove_item.assert_awaited_once_with(
        "milk", {"quantity": 5, "auto_add_to_list_quantity": 2}
    )
    mock_coordinator.async_save_data.assert_awaited_once_with("kitchen")


@pytest.mark.asyncio
async def test_async_increment_item_default_amount(
    quantity_service: QuantityService,
    basic_service_call: ServiceCall,
    mock_coordinator: MagicMock,
) -> None:
    await quantity_service.async_increment_item(basic_service_call)

    mock_coordinator.async_increment_item.assert_awaited_once_with(
        "kitchen", "milk", 1.0, barcode=None, price=None
    )
    mock_coordinator.async_save_data.assert_awaited_once_with("kitchen")


@pytest.mark.asyncio
async def test_async_increment_item_not_found_logs_warning(
    quantity_service: QuantityService,
    quantity_service_call: ServiceCall,
    mock_coordinator: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock_coordinator.async_increment_item.return_value = False

    with caplog.at_level(logging.WARNING):
        await quantity_service.async_increment_item(quantity_service_call)

    mock_coordinator.async_increment_item.assert_awaited_once_with(
        "kitchen", "milk", 2.0, barcode=None, price=None
    )
    mock_coordinator.async_save_data.assert_not_awaited()

    assert "Item not found" in caplog.text


@pytest.mark.asyncio
async def test_async_increment_item_coordinator_exception_logged(
    quantity_service: QuantityService,
    quantity_service_call: ServiceCall,
    mock_coordinator: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock_coordinator.async_increment_item.side_effect = Exception("Database error")

    with caplog.at_level(logging.ERROR):
        await quantity_service.async_increment_item(quantity_service_call)

    assert "Failed to increment item" in caplog.text
    mock_coordinator.async_save_data.assert_not_awaited()


@pytest.mark.asyncio
async def test_async_decrement_item_success_with_todo_check(
    quantity_service: QuantityService,
    quantity_service_call: ServiceCall,
    mock_coordinator: MagicMock,
    mock_todo_manager: MagicMock,
) -> None:
    await quantity_service.async_decrement_item(quantity_service_call)

    mock_coordinator.async_decrement_item.assert_awaited_once_with(
        "kitchen", "milk", 2.0, barcode=None, price=None
    )
    mock_coordinator.async_get_item.assert_awaited_once_with("kitchen", "milk")
    mock_todo_manager.check_and_add_item.assert_awaited_once_with(
        "milk", {"quantity": 5, "auto_add_to_list_quantity": 2}
    )
    mock_coordinator.async_save_data.assert_awaited_once_with("kitchen")


@pytest.mark.asyncio
async def test_async_decrement_item_default_amount(
    quantity_service: QuantityService,
    basic_service_call: ServiceCall,
    mock_coordinator: MagicMock,
) -> None:
    await quantity_service.async_decrement_item(basic_service_call)

    mock_coordinator.async_decrement_item.assert_awaited_once_with(
        "kitchen", "milk", 1.0, barcode=None, price=None
    )
    mock_coordinator.async_save_data.assert_awaited_once_with("kitchen")


@pytest.mark.asyncio
async def test_async_decrement_item_no_item_data(
    quantity_service: QuantityService,
    quantity_service_call: ServiceCall,
    mock_coordinator: MagicMock,
    mock_todo_manager: MagicMock,
) -> None:
    mock_coordinator.async_get_item.return_value = None

    await quantity_service.async_decrement_item(quantity_service_call)

    mock_coordinator.async_decrement_item.assert_awaited_once()
    mock_coordinator.async_get_item.assert_awaited_once()
    mock_todo_manager.check_and_add_item.assert_not_awaited()
    mock_coordinator.async_save_data.assert_awaited_once()


@pytest.mark.asyncio
async def test_async_decrement_item_not_found_logs_warning(
    quantity_service: QuantityService,
    quantity_service_call: ServiceCall,
    mock_coordinator: MagicMock,
    mock_todo_manager: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock_coordinator.async_decrement_item.return_value = False

    with caplog.at_level(logging.WARNING):
        await quantity_service.async_decrement_item(quantity_service_call)

    mock_coordinator.async_decrement_item.assert_awaited_once_with(
        "kitchen", "milk", 2.0, barcode=None, price=None
    )

    mock_coordinator.async_get_item.assert_not_awaited()
    mock_todo_manager.check_and_add_item.assert_not_awaited()
    mock_coordinator.async_save_data.assert_not_awaited()

    assert "Item not found" in caplog.text


@pytest.mark.asyncio
async def test_async_decrement_item_coordinator_exception_logged(
    quantity_service: QuantityService,
    quantity_service_call: ServiceCall,
    mock_coordinator: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock_coordinator.async_decrement_item.side_effect = Exception("Decrement failed")

    with caplog.at_level(logging.ERROR):
        await quantity_service.async_decrement_item(quantity_service_call)

    assert "Failed to decrement item" in caplog.text
    mock_coordinator.async_save_data.assert_not_awaited()


@pytest.mark.asyncio
async def test_async_decrement_item_todo_manager_exception_logged(
    quantity_service: QuantityService,
    quantity_service_call: ServiceCall,
    mock_coordinator: MagicMock,
    mock_todo_manager: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock_todo_manager.check_and_add_item.side_effect = Exception("Todo check failed")

    with caplog.at_level(logging.ERROR):
        await quantity_service.async_decrement_item(quantity_service_call)

    # decrement happened, but save should not
    mock_coordinator.async_decrement_item.assert_awaited_once()
    mock_coordinator.async_save_data.assert_not_awaited()
    assert "Failed to decrement item" in caplog.text


@pytest.mark.parametrize("amount", [1, 5, 10, 100, 0])
@pytest.mark.asyncio
async def test_increment_various_amounts(
    quantity_service: QuantityService,
    mock_coordinator: MagicMock,
    amount: int,
) -> None:
    call = MagicMock(spec=ServiceCall)
    call.data = {"inventory_id": "kitchen", "name": "milk", "amount": amount}
    call.context.id = "ctx-x"

    await quantity_service.async_increment_item(call)

    mock_coordinator.async_increment_item.assert_awaited_once_with(
        "kitchen", "milk", float(amount), barcode=None, price=None
    )


@pytest.mark.asyncio
async def test_concurrent_decrement_operations(
    hass: HomeAssistant,
    mock_todo_manager: MagicMock,
) -> None:
    # Build a hass with coordinators for 3 inventories
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["coordinators"] = {}

    coordinators: dict[str, MagicMock] = {}
    for i in range(3):
        inv_id = f"inventory_{i}"
        c = MagicMock()
        c.async_decrement_item = AsyncMock(return_value=True)
        c.async_get_item = AsyncMock(return_value={"quantity": 1, "auto_add_to_list_quantity": 2})
        c.async_save_data = AsyncMock()
        c.async_lookup_by_barcode = AsyncMock(return_value=[])
        coordinators[inv_id] = c
        hass.data[DOMAIN]["coordinators"][inv_id] = c

    service = QuantityService(hass, mock_todo_manager)

    calls = []
    for i in range(3):
        call = MagicMock(spec=ServiceCall)
        call.data = {"inventory_id": f"inventory_{i}", "name": f"item_{i}", "amount": i + 1}
        call.context.id = f"ctx-{i}"
        calls.append(call)

    await asyncio.gather(*(service.async_decrement_item(call) for call in calls))

    for i in range(3):
        inv_id = f"inventory_{i}"
        coordinators[inv_id].async_decrement_item.assert_awaited_once()
        coordinators[inv_id].async_save_data.assert_awaited_once_with(inv_id)

    assert mock_todo_manager.check_and_add_item.await_count == 3


# ---------------------------------------------------------------------------
# Barcode tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_increment_item_with_barcode(
    quantity_service: QuantityService,
    mock_coordinator: MagicMock,
    mock_todo_manager: MagicMock,
) -> None:
    mock_coordinator.async_lookup_by_barcode = AsyncMock(
        return_value=[{"name": "milk", "inventory_id": "kitchen"}]
    )

    call = MagicMock(spec=ServiceCall)
    call.data = {"inventory_id": "kitchen", "barcode": "BC-123", "amount": 2}
    call.context.id = "ctx-bc"

    await quantity_service.async_increment_item(call)

    mock_coordinator.async_increment_item.assert_awaited_once_with(
        "kitchen", None, 2, barcode="BC-123", price=None
    )
    mock_coordinator.async_save_data.assert_awaited_once_with("kitchen")


@pytest.mark.asyncio
async def test_async_decrement_item_with_barcode(
    quantity_service: QuantityService,
    mock_coordinator: MagicMock,
    mock_todo_manager: MagicMock,
) -> None:
    mock_coordinator.async_lookup_by_barcode = AsyncMock(
        return_value=[{"name": "milk", "inventory_id": "kitchen"}]
    )

    call = MagicMock(spec=ServiceCall)
    call.data = {"inventory_id": "kitchen", "barcode": "BC-456", "amount": 1}
    call.context.id = "ctx-bc2"

    await quantity_service.async_decrement_item(call)

    mock_coordinator.async_decrement_item.assert_awaited_once_with(
        "kitchen", None, 1, barcode="BC-456", price=None
    )
    mock_coordinator.async_save_data.assert_awaited_once_with("kitchen")


# ---------------------------------------------------------------------------
# async_scan_barcode tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_barcode_decrement_calls_todo_add(
    quantity_service: QuantityService,
    mock_coordinator: MagicMock,
    mock_todo_manager: MagicMock,
) -> None:
    """Decrement via scan_barcode must call check_and_add_item."""
    item_data = {"name": "Milk", "quantity": 0.0}
    mock_coordinator.async_scan_barcode = AsyncMock(
        return_value={
            "action": "decrement",
            "success": True,
            "item_name": "Milk",
            "inventory_id": "kitchen",
            "amount": 1.0,
        }
    )
    mock_coordinator.async_get_item = AsyncMock(return_value=item_data)

    await quantity_service.async_scan_barcode("BC-123", "decrement", 1.0, "kitchen")

    mock_todo_manager.check_and_add_item.assert_awaited_once_with("Milk", item_data)
    mock_todo_manager.check_and_remove_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_scan_barcode_increment_calls_todo_remove(
    quantity_service: QuantityService,
    mock_coordinator: MagicMock,
    mock_todo_manager: MagicMock,
) -> None:
    """Increment via scan_barcode must call check_and_remove_item."""
    item_data = {"name": "Milk", "quantity": 2.0}
    mock_coordinator.async_scan_barcode = AsyncMock(
        return_value={
            "action": "increment",
            "success": True,
            "item_name": "Milk",
            "inventory_id": "kitchen",
            "amount": 1.0,
        }
    )
    mock_coordinator.async_get_item = AsyncMock(return_value=item_data)

    await quantity_service.async_scan_barcode("BC-123", "increment", 1.0, "kitchen")

    mock_todo_manager.check_and_remove_item.assert_awaited_once_with("Milk", item_data)
    mock_todo_manager.check_and_add_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_scan_barcode_lookup_skips_todo(
    quantity_service: QuantityService,
    mock_coordinator: MagicMock,
    mock_todo_manager: MagicMock,
) -> None:
    """Lookup action must not touch the todo manager."""
    mock_coordinator.async_scan_barcode = AsyncMock(
        return_value={"action": "lookup", "item": {}, "inventory_id": "kitchen"}
    )

    await quantity_service.async_scan_barcode("BC-123", "lookup", inventory_id="kitchen")

    mock_todo_manager.check_and_add_item.assert_not_awaited()
    mock_todo_manager.check_and_remove_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_scan_barcode_no_inventories_raises(
    quantity_service: QuantityService,
    hass_with_coordinator: HomeAssistant,
) -> None:
    """Should raise ServiceValidationError when no inventories are configured."""
    hass_with_coordinator.data[DOMAIN]["coordinators"] = {}

    with pytest.raises(ServiceValidationError, match="No inventories configured"):
        await quantity_service.async_scan_barcode("BC-123", "increment")


@pytest.mark.asyncio
async def test_scan_barcode_unknown_inventory_raises(
    quantity_service: QuantityService,
) -> None:
    """Should raise ServiceValidationError for an unknown inventory_id."""
    with pytest.raises(ServiceValidationError, match="No coordinator available"):
        await quantity_service.async_scan_barcode("BC-123", "increment", inventory_id="unknown")
