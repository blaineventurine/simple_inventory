"""Tests for the SimpleInventoryCoordinator class (SQLite-backed)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import EventBus, HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from custom_components.simple_inventory.const import (
    DOMAIN,
    EVENT_ITEM_ADDED,
    EVENT_ITEM_DEPLETED,
    EVENT_ITEM_QUANTITY_CHANGED,
    EVENT_ITEM_REMOVED,
    EVENT_ITEM_RESTOCKED,
    FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED,
    FIELD_DESCRIPTION,
    FIELD_DESIRED_QUANTITY,
    FIELD_NAME,
    FIELD_QUANTITY,
    FIELD_TODO_QUANTITY_PLACEMENT,
)
from custom_components.simple_inventory.coordinator import (
    SimpleInventoryCoordinator,
    _compute_avg_restock_days,
)


@pytest.fixture
def mock_entry() -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "kitchen_123"
    entry.data = {"name": "Kitchen", "entry_type": "inventory"}
    entry.title = "Kitchen"
    return entry


@pytest.fixture
def mock_repository(sample_inventory_data: dict) -> MagicMock:
    repo = MagicMock()

    repo.async_initialize = AsyncMock()

    # Basic inventory metadata
    repo.list_inventories = AsyncMock(
        return_value=[
            {
                "id": "kitchen_123",
                "name": "Kitchen",
                "description": "",
                "icon": "",
                "entry_type": "inventory",
            },
            {
                "id": "pantry_123",
                "name": "Pantry",
                "description": "",
                "icon": "",
                "entry_type": "inventory",
            },
        ]
    )

    # Use fixture items as "DB rows"
    repo.list_items_with_details = AsyncMock(
        side_effect=lambda inv_id: {
            "kitchen_123": sample_inventory_data["kitchen"]["items"],
            "pantry_123": sample_inventory_data["pantry"]["items"],
        }.get(inv_id, [])
    )

    async def _get_item_by_name(inv_id: str, name: str) -> dict[str, Any] | None:
        items = await repo.list_items_with_details(inv_id)
        for it in items:
            if str(it.get("name", "")).lower() == name.lower():
                return {"id": it.get("id", f"{inv_id}:{it['name']}"), **it}
        return None

    repo.get_item_by_name = AsyncMock(side_effect=_get_item_by_name)

    repo.create_item = AsyncMock(return_value="new-item-id")
    repo.update_item = AsyncMock(return_value=True)
    repo.delete_item = AsyncMock(return_value=True)

    repo.ensure_location = AsyncMock(return_value=1)
    repo.set_item_locations = AsyncMock()
    repo.ensure_category = AsyncMock(return_value=1)
    repo.set_item_categories = AsyncMock()

    repo.upsert_inventory = AsyncMock()

    repo.add_item_barcode = AsyncMock()
    repo.remove_item_barcode = AsyncMock()
    repo.get_item_by_barcode = AsyncMock(return_value=None)
    repo.get_item_by_barcode_global = AsyncMock(return_value=[])
    repo.get_barcodes_for_item = AsyncMock(return_value=[])
    repo.set_item_barcodes = AsyncMock()

    repo.record_history_event = AsyncMock(return_value="event-id")
    repo.get_item_history = AsyncMock(return_value=[])
    repo.get_inventory_history = AsyncMock(return_value=[])

    return repo


@pytest.fixture
def coordinator(
    hass: HomeAssistant, mock_entry: MagicMock, mock_repository: MagicMock
) -> SimpleInventoryCoordinator:
    return SimpleInventoryCoordinator(hass, mock_entry, mock_repository)


@pytest.mark.asyncio
async def test_async_unload_removes_listeners(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    listener = MagicMock()
    remove = coordinator.async_add_listener(listener)
    assert listener in coordinator._listeners

    await coordinator.async_unload()
    assert coordinator._listeners == []

    # remove callback should be safe even after unload
    remove()
    assert coordinator._listeners == []


@pytest.mark.asyncio
async def test_async_initialize_is_idempotent(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    await coordinator.async_initialize()
    await coordinator.async_initialize()
    # Coordinator init should not call repo.async_initialize (repo is initialized in __init__.py),
    # but if you ever add it back, this test will catch multiple calls.
    mock_repository.async_initialize.assert_not_awaited()


@pytest.mark.asyncio
async def test_async_save_data_fires_events(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    with patch.object(EventBus, "async_fire") as mock_fire:
        await coordinator.async_save_data("kitchen_123")

        mock_fire.assert_any_call(f"{DOMAIN}_updated_kitchen_123")
        mock_fire.assert_any_call(f"{DOMAIN}_updated")


@pytest.mark.asyncio
async def test_async_add_item_applies_description_suffix(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.create_item.reset_mock()

    with patch.object(EventBus, "async_fire"):
        item_id = await coordinator.async_add_item(
            "kitchen_123",
            name="coffee",
            quantity=1,
            description="Pantry staple",
            auto_add_id_to_description_enabled=True,
        )

    assert item_id == "new-item-id"
    assert mock_repository.create_item.await_count == 1

    # Verify payload passed to repository includes suffix
    _, args, _ = mock_repository.create_item.mock_calls[0]
    assert args[0] == "kitchen_123"
    payload = args[1]
    assert payload[FIELD_NAME] == "coffee"
    assert payload[FIELD_DESCRIPTION] == "Pantry staple (kitchen_123)"
    assert payload[FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED] is True


@pytest.mark.asyncio
async def test_async_add_item_empty_description_with_id_suffix(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    """Empty description + auto_add_id should produce '(inv_id)' and not double on re-edit."""
    mock_repository.create_item.reset_mock()

    with patch.object(EventBus, "async_fire"):
        await coordinator.async_add_item(
            "kitchen_123",
            name="sugar",
            quantity=1,
            description="",
            auto_add_id_to_description_enabled=True,
        )

    _, args, _ = mock_repository.create_item.mock_calls[0]
    payload = args[1]
    assert payload[FIELD_DESCRIPTION] == "(kitchen_123)"

    # Simulate editing the item: the frontend sends back the stored description
    mock_repository.get_item_by_name = AsyncMock(
        return_value={
            "id": "sugar-id",
            "name": "sugar",
            "description": "(kitchen_123)",
            "quantity": 1,
            "auto_add_id_to_description_enabled": True,
        }
    )
    mock_repository.update_item.reset_mock()

    with patch.object(EventBus, "async_fire"):
        ok = await coordinator.async_update_item(
            "kitchen_123",
            old_name="sugar",
            new_name="sugar",
            description="(kitchen_123)",
            auto_add_id_to_description_enabled=True,
        )

    assert ok is True
    _, args, _ = mock_repository.update_item.mock_calls[0]
    update_payload = args[1]
    # Must NOT double to "(kitchen_123) (kitchen_123)"
    assert update_payload[FIELD_DESCRIPTION] == "(kitchen_123)"


@pytest.mark.asyncio
async def test_async_add_item_empty_name_raises(coordinator: SimpleInventoryCoordinator) -> None:
    with pytest.raises(ValueError):
        await coordinator.async_add_item("kitchen_123", name="", quantity=1)

    with pytest.raises(ValueError):
        await coordinator.async_add_item("kitchen_123", name="   ", quantity=1)


@pytest.mark.asyncio
async def test_async_increment_item_item_missing_returns_false(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_name = AsyncMock(return_value=None)

    ok = await coordinator.async_increment_item("kitchen_123", "nope", 1)
    assert ok is False
    mock_repository.update_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_async_increment_item_update_fails_returns_false(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_name = AsyncMock(return_value={"id": "x", "quantity": 1})
    mock_repository.update_item = AsyncMock(return_value=False)

    with patch.object(EventBus, "async_fire"):
        ok = await coordinator.async_increment_item("kitchen_123", "milk", 1)

    assert ok is False


@pytest.mark.asyncio
async def test_async_update_item_updates_location_and_category(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_name = AsyncMock(
        return_value={"id": "item1", "name": "milk", "quantity": 2}
    )
    mock_repository.update_item = AsyncMock(return_value=True)
    mock_repository.ensure_location = AsyncMock(return_value=7)
    mock_repository.ensure_category = AsyncMock(return_value=9)

    with patch.object(EventBus, "async_fire"):
        ok = await coordinator.async_update_item(
            "kitchen_123",
            old_name="milk",
            new_name="milk",
            location="Fridge",
            category="Dairy",
            quantity=2,
        )

    assert ok is True
    mock_repository.ensure_location.assert_awaited_once_with("kitchen_123", "Fridge")
    mock_repository.set_item_locations.assert_awaited_once_with("item1", [7])
    mock_repository.ensure_category.assert_awaited_once_with("Dairy")
    mock_repository.set_item_categories.assert_awaited_once_with("item1", [9])


@pytest.mark.asyncio
async def test_async_update_item_comma_separated_locations(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    """Comma-separated location string should ensure each location individually."""
    mock_repository.get_item_by_name = AsyncMock(
        return_value={"id": "item1", "name": "milk", "quantity": 2}
    )
    mock_repository.update_item = AsyncMock(return_value=True)

    loc_id_map = {"Fridge": 7, "Pantry": 8}
    mock_repository.ensure_location = AsyncMock(side_effect=lambda inv_id, name: loc_id_map[name])

    with patch.object(EventBus, "async_fire"):
        ok = await coordinator.async_update_item(
            "kitchen_123",
            old_name="milk",
            new_name="milk",
            location="Fridge, Pantry",
            quantity=2,
        )

    assert ok is True
    assert mock_repository.ensure_location.await_count == 2
    mock_repository.ensure_location.assert_any_await("kitchen_123", "Fridge")
    mock_repository.ensure_location.assert_any_await("kitchen_123", "Pantry")
    mock_repository.set_item_locations.assert_awaited_once_with("item1", [7, 8])


@pytest.mark.asyncio
async def test_async_update_item_comma_separated_categories(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    """Comma-separated category string should ensure each category individually."""
    mock_repository.get_item_by_name = AsyncMock(
        return_value={"id": "item1", "name": "milk", "quantity": 2}
    )
    mock_repository.update_item = AsyncMock(return_value=True)

    cat_id_map = {"Dairy": 9, "Refrigerated": 10}
    mock_repository.ensure_category = AsyncMock(side_effect=lambda name: cat_id_map[name])

    with patch.object(EventBus, "async_fire"):
        ok = await coordinator.async_update_item(
            "kitchen_123",
            old_name="milk",
            new_name="milk",
            category="Dairy, Refrigerated",
        )

    assert ok is True
    assert mock_repository.ensure_category.await_count == 2
    mock_repository.ensure_category.assert_any_await("Dairy")
    mock_repository.ensure_category.assert_any_await("Refrigerated")
    mock_repository.set_item_categories.assert_awaited_once_with("item1", [9, 10])


@pytest.mark.asyncio
async def test_async_add_item_comma_separated_locations_trimmed(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    """Extra spaces in comma-separated values should be trimmed."""
    mock_repository.create_item.reset_mock()

    loc_id_map = {"Fridge": 7, "Pantry": 8}
    mock_repository.ensure_location = AsyncMock(side_effect=lambda inv_id, name: loc_id_map[name])

    with patch.object(EventBus, "async_fire"):
        await coordinator.async_add_item(
            "kitchen_123",
            name="milk",
            quantity=2,
            location="  Fridge ,  Pantry  ",
        )

    assert mock_repository.ensure_location.await_count == 2
    mock_repository.ensure_location.assert_any_await("kitchen_123", "Fridge")
    mock_repository.ensure_location.assert_any_await("kitchen_123", "Pantry")
    mock_repository.set_item_locations.assert_awaited_once_with("new-item-id", [7, 8])


@pytest.mark.asyncio
async def test_async_get_items_expiring_soon_skips_invalid_date(
    coordinator: SimpleInventoryCoordinator,
    mock_repository: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock_repository.list_items_with_details = AsyncMock(
        return_value=[
            {"name": "bad", "expiry_date": "not-a-date", "expiry_alert_days": 7, "quantity": 1},
        ]
    )

    with caplog.at_level("WARNING"):
        items = await coordinator.async_get_items_expiring_soon("kitchen_123")

    assert items == []
    assert "Invalid expiry date format" in caplog.text


@pytest.mark.asyncio
async def test_async_get_items_expiring_soon_global_uses_list_inventories(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    today = datetime.now().date()
    soon = (today + timedelta(days=1)).strftime("%Y-%m-%d")

    mock_repository.list_inventories = AsyncMock(
        return_value=[{"id": "kitchen_123"}, {"id": "pantry_123"}]
    )
    mock_repository.list_items_with_details = AsyncMock(
        side_effect=lambda inv_id: [
            {"name": f"{inv_id}_item", "expiry_date": soon, "expiry_alert_days": 7, "quantity": 1}
        ]
    )

    items = await coordinator.async_get_items_expiring_soon()

    assert len(items) == 2
    assert {i["inventory_id"] for i in items} == {"kitchen_123", "pantry_123"}


@pytest.mark.asyncio
async def test_expiry_cache_returns_cached_result_within_ttl(
    coordinator: SimpleInventoryCoordinator,
    mock_repository: MagicMock,
) -> None:
    """Second call within TTL should not hit the repository again."""
    today = datetime.now().date()
    soon = (today + timedelta(days=1)).strftime("%Y-%m-%d")

    mock_repository.list_items_with_details = AsyncMock(
        return_value=[{"name": "milk", "expiry_date": soon, "expiry_alert_days": 7, "quantity": 1}]
    )

    first = await coordinator.async_get_items_expiring_soon("kitchen_123")
    second = await coordinator.async_get_items_expiring_soon("kitchen_123")

    assert first == second
    # Repository should only have been called once despite two coordinator calls
    mock_repository.list_items_with_details.assert_awaited_once()


@pytest.mark.asyncio
async def test_expiry_cache_misses_after_ttl(
    coordinator: SimpleInventoryCoordinator,
    mock_repository: MagicMock,
) -> None:
    """Call after TTL expiry should hit the repository again."""
    today = datetime.now().date()
    soon = (today + timedelta(days=1)).strftime("%Y-%m-%d")

    mock_repository.list_items_with_details = AsyncMock(
        return_value=[{"name": "milk", "expiry_date": soon, "expiry_alert_days": 7, "quantity": 1}]
    )

    await coordinator.async_get_items_expiring_soon("kitchen_123")

    # Expire the cache by backdating its timestamp
    coordinator._expiry_cache["kitchen_123"] = (0.0, coordinator._expiry_cache["kitchen_123"][1])

    await coordinator.async_get_items_expiring_soon("kitchen_123")

    assert mock_repository.list_items_with_details.await_count == 2


@pytest.mark.asyncio
async def test_async_add_item_invalid_auto_add_config_returns_none(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    # auto_add_enabled=True but todo_list empty => should fail validation
    item_id = await coordinator.async_add_item(
        "kitchen_123",
        name="butter",
        quantity=1,
        auto_add_enabled=True,
        auto_add_to_list_quantity=0,
        todo_list="",
    )
    assert item_id is None


@pytest.mark.asyncio
async def test_async_update_item_recalculates_description_on_flag_toggle(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    # Existing item in repository without suffix
    mock_repository.get_item_by_name = AsyncMock(
        return_value={
            "id": "milk-id",
            "name": "milk",
            "description": "Fresh milk (kitchen_123)",
            "quantity": 2,
            "auto_add_id_to_description_enabled": True,
        }
    )

    with patch.object(EventBus, "async_fire"):
        ok = await coordinator.async_update_item(
            "kitchen_123",
            old_name="milk",
            new_name="milk",
            auto_add_id_to_description_enabled=False,
            description="Fresh milk (kitchen_123)",
        )

    assert ok is True
    assert mock_repository.update_item.await_count == 1

    # update_item(item_id, payload)
    _, args, _ = mock_repository.update_item.mock_calls[0]
    assert args[0] == "milk-id"
    payload = args[1]
    assert payload[FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED] is False
    assert payload[FIELD_DESCRIPTION] == "Fresh milk"


@pytest.mark.asyncio
async def test_async_remove_item_deletes_when_present(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_name = AsyncMock(return_value={"id": "x", "name": "milk"})

    with patch.object(EventBus, "async_fire"):
        ok = await coordinator.async_remove_item("kitchen_123", "milk")

    assert ok is True
    mock_repository.delete_item.assert_awaited_once_with("x")


@pytest.mark.asyncio
async def test_async_remove_item_returns_false_when_missing(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_name = AsyncMock(return_value=None)
    ok = await coordinator.async_remove_item("kitchen_123", "nope")
    assert ok is False
    mock_repository.delete_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_async_increment_item_adjusts_quantity(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_name = AsyncMock(return_value={"id": "milk-id", "quantity": 2})
    mock_repository.update_item = AsyncMock(return_value=True)

    with patch.object(EventBus, "async_fire"):
        ok = await coordinator.async_increment_item("kitchen_123", "milk", 3)

    assert ok is True
    mock_repository.update_item.assert_awaited_once_with("milk-id", {FIELD_QUANTITY: 5})


@pytest.mark.asyncio
async def test_async_increment_item_decimal_amount(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_name = AsyncMock(return_value={"id": "bacon-id", "quantity": 1.0})
    mock_repository.update_item = AsyncMock(return_value=True)

    with patch.object(EventBus, "async_fire"):
        ok = await coordinator.async_increment_item("kitchen_123", "bacon", 0.5)

    assert ok is True
    mock_repository.update_item.assert_awaited_once_with("bacon-id", {FIELD_QUANTITY: 1.5})


@pytest.mark.asyncio
async def test_async_decrement_item_decimal_amount(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_name = AsyncMock(return_value={"id": "bacon-id", "quantity": 1.5})
    mock_repository.update_item = AsyncMock(return_value=True)

    with patch.object(EventBus, "async_fire"):
        ok = await coordinator.async_decrement_item("kitchen_123", "bacon", 0.5)

    assert ok is True
    mock_repository.update_item.assert_awaited_once_with("bacon-id", {FIELD_QUANTITY: 1.0})


@pytest.mark.asyncio
async def test_async_increment_item_negative_amount_fails(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    ok = await coordinator.async_increment_item("kitchen_123", "milk", -1)
    assert ok is False
    mock_repository.get_item_by_name.assert_not_awaited()


@pytest.mark.asyncio
async def test_async_decrement_item_does_not_go_below_zero(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_name = AsyncMock(return_value={"id": "milk-id", "quantity": 2})
    mock_repository.update_item = AsyncMock(return_value=True)

    with patch.object(EventBus, "async_fire"):
        ok = await coordinator.async_decrement_item("kitchen_123", "milk", 99)

    assert ok is True
    mock_repository.update_item.assert_awaited_once_with("milk-id", {FIELD_QUANTITY: 0})


@pytest.mark.asyncio
async def test_async_get_item_passthrough(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_name = AsyncMock(return_value={"id": "x", "name": "milk"})
    item = await coordinator.async_get_item("kitchen_123", "milk")
    assert item is not None
    assert item["name"] == "milk"


@pytest.mark.asyncio
async def test_async_list_items_passthrough(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.list_items_with_details = AsyncMock(return_value=[{"name": "milk"}])
    items = await coordinator.async_list_items("kitchen_123")
    assert items == [{"name": "milk"}]


@pytest.mark.asyncio
async def test_async_get_inventory_statistics_counts(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    # minimal two items
    mock_repository.list_items_with_details = AsyncMock(
        return_value=[
            {
                "name": "milk",
                "quantity": 2,
                "category": "dairy",
                "location": "fridge",
                "locations": [],
            },
            {
                "name": "bread",
                "quantity": 1,
                "category": "bakery",
                "location": "pantry",
                "locations": [],
            },
        ]
    )

    with patch.object(coordinator, "async_get_items_expiring_soon", new=AsyncMock(return_value=[])):
        stats = await coordinator.async_get_inventory_statistics("kitchen_123")

    assert stats["total_items"] == 2
    assert stats["total_quantity"] == 3
    assert stats["categories"]["dairy"] == 1
    assert stats["categories"]["bakery"] == 1


@pytest.mark.asyncio
async def test_async_get_items_expiring_soon_includes_expired_with_zero_threshold(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    """Items already past expiry with threshold=0 must still appear."""
    today = datetime.now().date()
    expired = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    future = (today + timedelta(days=30)).strftime("%Y-%m-%d")

    mock_repository.list_items_with_details = AsyncMock(
        return_value=[
            {
                "name": "expired_no_threshold",
                "expiry_date": expired,
                "expiry_alert_days": 0,
                "quantity": 1,
            },
            {
                "name": "future_no_threshold",
                "expiry_date": future,
                "expiry_alert_days": 0,
                "quantity": 1,
            },
            {
                "name": "expired_with_threshold",
                "expiry_date": expired,
                "expiry_alert_days": 7,
                "quantity": 1,
            },
        ]
    )

    items = await coordinator.async_get_items_expiring_soon("kitchen_123")

    names = [it["name"] for it in items]
    # expired items included regardless of threshold; future item with threshold=0 excluded
    assert "expired_no_threshold" in names
    assert "expired_with_threshold" in names
    assert "future_no_threshold" not in names


@pytest.mark.asyncio
async def test_async_get_items_expiring_soon_null_expiry_alert_days(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    """NULL expiry_alert_days (old DB rows before migration) must not crash and must include expired items."""
    today = datetime.now().date()
    expired = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    future = (today + timedelta(days=30)).strftime("%Y-%m-%d")

    mock_repository.list_items_with_details = AsyncMock(
        return_value=[
            # Expired item with NULL threshold — was causing TypeError before fix
            {
                "name": "null_threshold_expired",
                "expiry_date": expired,
                "expiry_alert_days": None,
                "quantity": 1,
            },
            # No expiry date + NULL threshold — should be skipped, not crash
            {
                "name": "null_threshold_no_date",
                "expiry_date": "",
                "expiry_alert_days": None,
                "quantity": 1,
            },
            # Future item with NULL threshold — threshold defaults to 0, so not included
            {
                "name": "null_threshold_future",
                "expiry_date": future,
                "expiry_alert_days": None,
                "quantity": 1,
            },
            # Normal expired item for comparison
            {
                "name": "normal_expired",
                "expiry_date": expired,
                "expiry_alert_days": 1,
                "quantity": 1,
            },
        ]
    )

    items = await coordinator.async_get_items_expiring_soon("kitchen_123")

    names = [it["name"] for it in items]
    assert "null_threshold_expired" in names, "expired item with NULL threshold must be included"
    assert "normal_expired" in names, "normal expired item must be included"
    assert "null_threshold_no_date" not in names, "item with no expiry date must be skipped"
    assert (
        "null_threshold_future" not in names
    ), "future item with NULL (→0) threshold must be excluded"


@pytest.mark.asyncio
async def test_async_get_items_expiring_soon_negative_expiry_alert_days(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    """Negative expiry_alert_days (e.g. from unvalidated import) must not exclude expired items."""
    today = datetime.now().date()
    expired_3_days_ago = (today - timedelta(days=3)).strftime("%Y-%m-%d")

    mock_repository.list_items_with_details = AsyncMock(
        return_value=[
            # expiry_alert_days=-5 would create threshold=-5, excluding items expired <5 days ago
            # With max(0, threshold), this becomes threshold=0 and the item IS included
            {
                "name": "negative_threshold_expired",
                "expiry_date": expired_3_days_ago,
                "expiry_alert_days": -5,
                "quantity": 1,
            },
        ]
    )

    items = await coordinator.async_get_items_expiring_soon("kitchen_123")

    names = [it["name"] for it in items]
    assert (
        "negative_threshold_expired" in names
    ), "expired item with negative threshold must be included (threshold clamped to 0)"
    expired_items = [it for it in items if it["days_until_expiry"] < 0]
    assert len(expired_items) == 1, "item must be classified as expired (days_until_expiry < 0)"


@pytest.mark.asyncio
async def test_async_get_items_expiring_soon_filters_and_sorts(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    today = datetime.now().date()
    soon = (today + timedelta(days=2)).strftime("%Y-%m-%d")
    later = (today + timedelta(days=30)).strftime("%Y-%m-%d")
    expired = (today - timedelta(days=1)).strftime("%Y-%m-%d")

    mock_repository.list_items_with_details = AsyncMock(
        return_value=[
            {"name": "soon", "expiry_date": soon, "expiry_alert_days": 7, "quantity": 1},
            {"name": "later", "expiry_date": later, "expiry_alert_days": 7, "quantity": 1},
            {"name": "expired", "expiry_date": expired, "expiry_alert_days": 7, "quantity": 1},
            {"name": "no_date", "expiry_date": "", "expiry_alert_days": 7, "quantity": 1},
            {"name": "zero_qty", "expiry_date": soon, "expiry_alert_days": 7, "quantity": 0},
        ]
    )

    items = await coordinator.async_get_items_expiring_soon("kitchen_123")

    # later/no_date/zero_qty excluded, remaining expired + soon
    names = [it["name"] for it in items]
    assert names == ["expired", "soon"]
    assert items[0]["days_until_expiry"] < items[1]["days_until_expiry"]


def test_async_add_listener_and_notify(coordinator: SimpleInventoryCoordinator) -> None:
    listener1 = MagicMock()
    listener2 = MagicMock()

    remove1 = coordinator.async_add_listener(listener1)
    coordinator.async_add_listener(listener2)

    coordinator.notify_listeners()

    listener1.assert_called_once()
    listener2.assert_called_once()

    remove1()
    assert listener1 not in coordinator._listeners


@pytest.mark.asyncio
async def test_async_add_item_passes_desired_quantity(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    """Test async_add_item passes desired_quantity through to repository."""
    mock_repository.create_item.reset_mock()

    with patch.object(EventBus, "async_fire"):
        item_id = await coordinator.async_add_item(
            "kitchen_123",
            name="Bacon",
            quantity=2,
            desired_quantity=10,
        )

    assert item_id == "new-item-id"
    assert mock_repository.create_item.await_count == 1

    _, args, _ = mock_repository.create_item.mock_calls[0]
    payload = args[1]
    assert payload[FIELD_DESIRED_QUANTITY] == 10.0


@pytest.mark.asyncio
async def test_below_threshold_includes_quantity_needed_legacy(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    """Test below_threshold uses legacy formula when desired_quantity is 0."""
    mock_repository.list_items_with_details = AsyncMock(
        return_value=[
            {
                "name": "Bacon",
                "quantity": 2,
                "auto_add_to_list_quantity": 5,
                "desired_quantity": 0,
                "category": "",
                "location": "",
                "locations": [],
                "unit": "",
            },
        ]
    )

    with patch.object(coordinator, "async_get_items_expiring_soon", new=AsyncMock(return_value=[])):
        stats = await coordinator.async_get_inventory_statistics("kitchen_123")

    assert len(stats["below_threshold"]) == 1
    entry = stats["below_threshold"][0]
    assert entry["name"] == "Bacon"
    assert entry["quantity"] == 2
    assert entry["threshold"] == 5
    assert entry["desired_quantity"] == 0
    # Legacy: 5 - 2 + 1 = 4
    assert entry["quantity_needed"] == 4


@pytest.mark.asyncio
async def test_below_threshold_includes_quantity_needed_desired(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    """Test below_threshold uses desired_quantity formula when desired_quantity > 0."""
    mock_repository.list_items_with_details = AsyncMock(
        return_value=[
            {
                "name": "Bacon",
                "quantity": 2,
                "auto_add_to_list_quantity": 3,
                "desired_quantity": 10,
                "category": "",
                "location": "",
                "locations": [],
                "unit": "",
            },
        ]
    )

    with patch.object(coordinator, "async_get_items_expiring_soon", new=AsyncMock(return_value=[])):
        stats = await coordinator.async_get_inventory_statistics("kitchen_123")

    assert len(stats["below_threshold"]) == 1
    entry = stats["below_threshold"][0]
    assert entry["name"] == "Bacon"
    assert entry["quantity"] == 2
    assert entry["threshold"] == 3
    assert entry["desired_quantity"] == 10
    # Desired: 10 - 2 = 8
    assert entry["quantity_needed"] == 8


@pytest.mark.asyncio
async def test_async_add_item_passes_todo_quantity_placement(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    """Test async_add_item passes todo_quantity_placement through to repository."""
    mock_repository.create_item.reset_mock()

    with patch.object(EventBus, "async_fire"):
        item_id = await coordinator.async_add_item(
            "kitchen_123",
            name="Milk",
            quantity=2,
            todo_quantity_placement="description",
        )

    assert item_id == "new-item-id"
    assert mock_repository.create_item.await_count == 1

    _, args, _ = mock_repository.create_item.mock_calls[0]
    payload = args[1]
    assert payload[FIELD_TODO_QUANTITY_PLACEMENT] == "description"


@pytest.mark.asyncio
async def test_async_add_item_defaults_todo_quantity_placement_to_name(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    """Test async_add_item defaults todo_quantity_placement to 'name'."""
    mock_repository.create_item.reset_mock()

    with patch.object(EventBus, "async_fire"):
        await coordinator.async_add_item(
            "kitchen_123",
            name="Bread",
            quantity=1,
        )

    _, args, _ = mock_repository.create_item.mock_calls[0]
    payload = args[1]
    assert payload[FIELD_TODO_QUANTITY_PLACEMENT] == "name"


# ---------------------------------------------------------------------------
# Barcode tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_add_item_with_barcode(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.create_item.reset_mock()

    with patch.object(EventBus, "async_fire"):
        item_id = await coordinator.async_add_item(
            "kitchen_123",
            name="Milk",
            quantity=2,
            barcode="123456789012",
        )

    assert item_id == "new-item-id"
    mock_repository.set_item_barcodes.assert_awaited_once_with(
        "new-item-id", "kitchen_123", ["123456789012"]
    )


@pytest.mark.asyncio
async def test_async_add_item_without_barcode_skips_barcode(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.create_item.reset_mock()

    with patch.object(EventBus, "async_fire"):
        await coordinator.async_add_item(
            "kitchen_123",
            name="Bread",
            quantity=1,
        )

    mock_repository.set_item_barcodes.assert_awaited_once_with("new-item-id", "kitchen_123", [])


@pytest.mark.asyncio
async def test_resolve_item_name_with_name(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    result = await coordinator._resolve_item_name("kitchen_123", "milk", None)
    assert result == "milk"


@pytest.mark.asyncio
async def test_resolve_item_name_with_barcode(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_barcode = AsyncMock(return_value={"id": "item1", "name": "Milk"})

    result = await coordinator._resolve_item_name("kitchen_123", None, "BC-123")
    assert result == "Milk"
    mock_repository.get_item_by_barcode.assert_awaited_once_with("kitchen_123", "BC-123")


@pytest.mark.asyncio
async def test_resolve_item_name_barcode_not_found(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_barcode = AsyncMock(return_value=None)

    with pytest.raises(ServiceValidationError, match="No item found for barcode"):
        await coordinator._resolve_item_name("kitchen_123", None, "MISSING")


@pytest.mark.asyncio
async def test_resolve_item_name_neither(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    with pytest.raises(ServiceValidationError, match="Either 'name' or 'barcode' is required"):
        await coordinator._resolve_item_name("kitchen_123", None, None)


@pytest.mark.asyncio
async def test_resolve_item_name_empty_strings(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    with pytest.raises(ServiceValidationError, match="Either 'name' or 'barcode' is required"):
        await coordinator._resolve_item_name("kitchen_123", "", "")


@pytest.mark.asyncio
async def test_async_increment_item_by_barcode(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_barcode = AsyncMock(return_value={"id": "milk-id", "name": "Milk"})
    mock_repository.get_item_by_name = AsyncMock(return_value={"id": "milk-id", "quantity": 2})
    mock_repository.update_item = AsyncMock(return_value=True)

    with patch.object(EventBus, "async_fire"):
        ok = await coordinator.async_increment_item("kitchen_123", barcode="BC-MILK", amount=3)

    assert ok is True
    mock_repository.get_item_by_barcode.assert_awaited_once_with("kitchen_123", "BC-MILK")
    mock_repository.update_item.assert_awaited_once_with("milk-id", {FIELD_QUANTITY: 5})


@pytest.mark.asyncio
async def test_async_decrement_item_by_barcode(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_barcode = AsyncMock(return_value={"id": "milk-id", "name": "Milk"})
    mock_repository.get_item_by_name = AsyncMock(return_value={"id": "milk-id", "quantity": 5})
    mock_repository.update_item = AsyncMock(return_value=True)

    with patch.object(EventBus, "async_fire"):
        ok = await coordinator.async_decrement_item("kitchen_123", barcode="BC-MILK", amount=2)

    assert ok is True
    mock_repository.update_item.assert_awaited_once_with("milk-id", {FIELD_QUANTITY: 3})


@pytest.mark.asyncio
async def test_async_remove_item_by_barcode(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_barcode = AsyncMock(return_value={"id": "milk-id", "name": "Milk"})
    mock_repository.get_item_by_name = AsyncMock(return_value={"id": "milk-id", "name": "Milk"})

    with patch.object(EventBus, "async_fire"):
        ok = await coordinator.async_remove_item("kitchen_123", barcode="BC-MILK")

    assert ok is True
    mock_repository.delete_item.assert_awaited_once_with("milk-id")


@pytest.mark.asyncio
async def test_apply_location_updates(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.ensure_location = AsyncMock(side_effect=[1, 2])

    with patch.object(EventBus, "async_fire"):
        await coordinator._apply_location_updates(
            "kitchen_123",
            "item-1",
            "Fridge, Pantry",
        )

    mock_repository.set_item_locations.assert_awaited_once()
    loc_ids = mock_repository.set_item_locations.call_args[0][1]
    assert loc_ids == [1, 2]


# --- Feature 2: History recording tests ---


@pytest.mark.asyncio
async def test_adjust_quantity_records_history(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_name = AsyncMock(
        return_value={"id": "milk-id", "name": "Milk", "quantity": 5}
    )

    with patch.object(EventBus, "async_fire"):
        ok = await coordinator.async_increment_item("kitchen_123", "Milk", 2)

    assert ok is True
    mock_repository.record_history_event.assert_awaited_once()
    call_kwargs = mock_repository.record_history_event.call_args.kwargs
    assert call_kwargs["event_type"] == "increment"
    assert call_kwargs["amount"] == 2
    assert call_kwargs["quantity_before"] == 5
    assert call_kwargs["quantity_after"] == 7


@pytest.mark.asyncio
async def test_add_item_records_history(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.create_item.reset_mock()

    with patch.object(EventBus, "async_fire"):
        item_id = await coordinator.async_add_item("kitchen_123", name="Apple", quantity=3)

    assert item_id is not None
    mock_repository.record_history_event.assert_awaited()
    call_kwargs = mock_repository.record_history_event.call_args.kwargs
    assert call_kwargs["event_type"] == "add"
    assert call_kwargs["quantity_after"] == 3


@pytest.mark.asyncio
async def test_remove_item_does_not_record_history(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    """History is not recorded for removes because ON DELETE CASCADE would
    delete the history row along with the item."""
    mock_repository.get_item_by_name = AsyncMock(
        return_value={"id": "milk-id", "name": "Milk", "quantity": 5}
    )

    with patch.object(EventBus, "async_fire"):
        ok = await coordinator.async_remove_item("kitchen_123", "Milk")

    assert ok is True
    mock_repository.record_history_event.assert_not_awaited()


# --- Feature 4: Import/Export tests ---


@pytest.mark.asyncio
async def test_export_json(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.fetch_inventory = AsyncMock(
        return_value={"id": "kitchen_123", "name": "Kitchen", "description": ""}
    )

    result = await coordinator.async_export_inventory("kitchen_123", "json")
    assert isinstance(result, dict)
    assert result["version"] == "1.0"
    assert "items" in result
    assert "exported_at" in result


@pytest.mark.asyncio
async def test_export_csv(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.fetch_inventory = AsyncMock(
        return_value={"id": "kitchen_123", "name": "Kitchen", "description": ""}
    )

    result = await coordinator.async_export_inventory("kitchen_123", "csv")
    assert isinstance(result, str)
    assert "name" in result  # CSV header


@pytest.mark.asyncio
async def test_import_json_skip(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_name = AsyncMock(
        return_value={"id": "existing", "name": "Milk", "quantity": 5}
    )

    data = {"items": [{"name": "Milk", "quantity": 3}]}

    with patch.object(EventBus, "async_fire"):
        summary = await coordinator.async_import_inventory("kitchen_123", data, "json", "skip")

    assert summary["skipped"] == 1
    assert summary["added"] == 0


@pytest.mark.asyncio
async def test_import_json_overwrite(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_name = AsyncMock(
        return_value={"id": "existing", "name": "Milk", "quantity": 5}
    )

    data = {"items": [{"name": "Milk", "quantity": 10}]}

    with patch.object(EventBus, "async_fire"):
        summary = await coordinator.async_import_inventory("kitchen_123", data, "json", "overwrite")

    assert summary["updated"] == 1
    mock_repository.update_item.assert_awaited()


@pytest.mark.asyncio
async def test_import_json_merge_quantities(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_name = AsyncMock(
        return_value={"id": "existing", "name": "Milk", "quantity": 5}
    )

    data = {"items": [{"name": "Milk", "quantity": 3}]}

    with patch.object(EventBus, "async_fire"):
        summary = await coordinator.async_import_inventory(
            "kitchen_123", data, "json", "merge_quantities"
        )

    assert summary["updated"] == 1
    mock_repository.update_item.assert_awaited_once()
    update_args = mock_repository.update_item.call_args
    assert update_args[0][1]["quantity"] == 8  # 5 + 3


@pytest.mark.asyncio
async def test_import_new_item(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_name = AsyncMock(return_value=None)
    mock_repository.create_item.reset_mock()

    data = {"items": [{"name": "NewItem", "quantity": 7}]}

    with patch.object(EventBus, "async_fire"):
        summary = await coordinator.async_import_inventory("kitchen_123", data, "json", "skip")

    assert summary["added"] == 1
    mock_repository.create_item.assert_awaited_once()


@pytest.mark.asyncio
async def test_csv_round_trip(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    items = [
        {
            "name": "Milk",
            "description": "Fresh",
            "quantity": 3,
            "unit": "gallons",
            "location": "Fridge",
            "category": "Dairy",
            "locations": ["Fridge"],
            "categories": ["Dairy"],
            "barcodes": ["123"],
            "expiry_date": "2025-12-31",
            "expiry_alert_days": 7,
            "auto_add_enabled": True,
            "auto_add_to_list_quantity": 1,
            "desired_quantity": 5,
            "todo_list": "todo.shopping",
        }
    ]
    csv_str = coordinator._items_to_csv(items)
    parsed = coordinator._csv_to_items(csv_str)

    assert len(parsed) == 1
    assert parsed[0]["name"] == "Milk"
    assert parsed[0]["quantity"] == 3.0
    assert parsed[0]["unit"] == "gallons"


# ---------------------------------------------------------------------------
# Consumption analytics: pure function tests
# ---------------------------------------------------------------------------


class TestComputeAvgRestockDays:
    def test_single_timestamp_returns_none(self) -> None:
        assert _compute_avg_restock_days(["2025-01-01T00:00:00"]) is None

    def test_two_timestamps_returns_gap(self) -> None:
        result = _compute_avg_restock_days(
            [
                "2025-01-01T00:00:00",
                "2025-01-11T00:00:00",
            ]
        )
        assert result == 10.0

    def test_multiple_timestamps_returns_average(self) -> None:
        result = _compute_avg_restock_days(
            [
                "2025-01-01T00:00:00",
                "2025-01-11T00:00:00",
                "2025-01-21T00:00:00",
            ]
        )
        assert result == 10.0

    def test_unsorted_timestamps_still_works(self) -> None:
        result = _compute_avg_restock_days(
            [
                "2025-01-21T00:00:00",
                "2025-01-01T00:00:00",
                "2025-01-11T00:00:00",
            ]
        )
        assert result == 10.0

    def test_empty_list_returns_none(self) -> None:
        assert _compute_avg_restock_days([]) is None


class TestComputeConsumptionRates:
    def test_sufficient_data_correct_rates(self) -> None:
        raw = {
            "decrement_count": 5,
            "total_consumed": 10.0,
            "window_days": 30,
            "first_event_ts": "2025-01-01T00:00:00",
            "last_event_ts": "2025-01-30T00:00:00",
            "restock_timestamps": [
                "2025-01-05T00:00:00",
                "2025-01-15T00:00:00",
            ],
        }
        result = SimpleInventoryCoordinator._compute_consumption_rates(raw, 5.0)

        assert result["has_sufficient_data"] is True
        expected_daily = round(10.0 / 30, 4)
        assert result["daily_rate"] == expected_daily
        assert result["weekly_rate"] == round(expected_daily * 7, 4)
        assert result["days_until_depletion"] is not None
        assert result["avg_restock_days"] == 10.0

    def test_insufficient_data_returns_none_rates(self) -> None:
        raw = {
            "decrement_count": 1,
            "total_consumed": 1.0,
            "window_days": 30,
            "first_event_ts": "2025-01-01T00:00:00",
            "last_event_ts": "2025-01-01T00:00:00",
            "restock_timestamps": [],
        }
        result = SimpleInventoryCoordinator._compute_consumption_rates(raw, 5.0)

        assert result["has_sufficient_data"] is False
        assert result["daily_rate"] is None
        assert result["weekly_rate"] is None
        assert result["days_until_depletion"] is None

    def test_zero_consumed_no_depletion(self) -> None:
        raw = {
            "decrement_count": 3,
            "total_consumed": 0.0,
            "window_days": 30,
            "first_event_ts": "2025-01-01T00:00:00",
            "last_event_ts": "2025-01-30T00:00:00",
            "restock_timestamps": [],
        }
        result = SimpleInventoryCoordinator._compute_consumption_rates(raw, 5.0)

        assert result["has_sufficient_data"] is True
        assert result["daily_rate"] is None
        assert result["days_until_depletion"] is None

    def test_no_window_uses_span_from_first_event(self) -> None:
        now = datetime.utcnow()
        first = (now - timedelta(days=50)).isoformat()
        raw: dict[str, Any] = {
            "decrement_count": 5,
            "total_consumed": 10.0,
            "window_days": None,
            "first_event_ts": first,
            "last_event_ts": now.isoformat(),
            "restock_timestamps": [],
        }
        result = SimpleInventoryCoordinator._compute_consumption_rates(raw, 5.0)

        assert result["has_sufficient_data"] is True
        assert result["daily_rate"] is not None
        # Rate should be ~0.2/day (10 consumed / 50 days)
        assert 0.15 < result["daily_rate"] < 0.25


# ---------------------------------------------------------------------------
# Consumption analytics: coordinator method tests (mocked repo)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_get_item_consumption_rates_unknown_item(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_name = AsyncMock(return_value=None)

    result = await coordinator.async_get_item_consumption_rates("kitchen_123", "nope")
    assert result is None


@pytest.mark.asyncio
async def test_async_get_item_consumption_rates_known_item(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_name = AsyncMock(
        return_value={"id": "milk-id", "name": "Milk", "quantity": 5.0, "unit": "liters"}
    )
    mock_repository.get_item_consumption_stats = AsyncMock(
        return_value={
            "item_id": "milk-id",
            "window_days": 30,
            "window_start": "2025-01-01T00:00:00",
            "decrement_count": 10,
            "total_consumed": 20.0,
            "first_event_ts": "2025-01-01T00:00:00",
            "last_event_ts": "2025-01-30T00:00:00",
            "restock_count": 2,
            "restock_timestamps": ["2025-01-10T00:00:00", "2025-01-20T00:00:00"],
        }
    )

    result = await coordinator.async_get_item_consumption_rates(
        "kitchen_123", "Milk", window_days=30
    )

    assert result is not None
    assert result["item_name"] == "Milk"
    assert result["current_quantity"] == 5.0
    assert result["unit"] == "liters"
    assert result["has_sufficient_data"] is True
    assert result["daily_rate"] is not None


@pytest.mark.asyncio
async def test_async_get_inventory_consumption_rates_shape(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_inventory_consumption_stats = AsyncMock(
        return_value=[
            {
                "item_id": "a",
                "item_name": "Apple",
                "current_quantity": 10.0,
                "unit": "pcs",
                "window_days": 30,
                "window_start": "",
                "decrement_count": 5,
                "total_consumed": 15.0,
                "first_event_ts": "2025-01-01T00:00:00",
                "last_event_ts": "2025-01-30T00:00:00",
                "restock_count": 0,
                "restock_timestamps": [],
            },
            {
                "item_id": "b",
                "item_name": "Banana",
                "current_quantity": 2.0,
                "unit": "pcs",
                "window_days": 30,
                "window_start": "",
                "decrement_count": 3,
                "total_consumed": 6.0,
                "first_event_ts": "2025-01-05T00:00:00",
                "last_event_ts": "2025-01-25T00:00:00",
                "restock_count": 0,
                "restock_timestamps": [],
            },
            {
                "item_id": "c",
                "item_name": "Cherry",
                "current_quantity": 5.0,
                "unit": "",
                "window_days": 30,
                "window_start": "",
                "decrement_count": 0,
                "total_consumed": 0.0,
                "first_event_ts": None,
                "last_event_ts": None,
                "restock_count": 0,
                "restock_timestamps": [],
            },
        ]
    )

    result = await coordinator.async_get_inventory_consumption_rates("kitchen_123", window_days=30)

    assert result["inventory_id"] == "kitchen_123"
    assert result["window_days"] == 30
    assert len(result["items"]) == 3
    assert result["summary"]["total_items_tracked"] == 2
    assert result["summary"]["total_consumed"] == 21.0

    # most_consumed sorted desc
    most = result["summary"]["most_consumed"]
    assert most[0]["item_name"] == "Apple"
    assert most[1]["item_name"] == "Banana"

    # running_out_soonest sorted asc, Cherry excluded (no rate)
    running_out = result["summary"]["running_out_soonest"]
    assert len(running_out) >= 1
    assert all(r["days_until_depletion"] is not None for r in running_out)


# ---------------------------------------------------------------------------
# HA event tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_item_added_fires(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.create_item.reset_mock()

    with patch.object(EventBus, "async_fire") as mock_fire:
        await coordinator.async_add_item("kitchen_123", name="Apple", quantity=3)

    event_calls = [c for c in mock_fire.call_args_list if c[0][0] == EVENT_ITEM_ADDED]
    assert len(event_calls) == 1
    payload = event_calls[0][0][1]
    assert payload["item_name"] == "Apple"
    assert payload["inventory_id"] == "kitchen_123"
    assert payload["quantity"] == 3


@pytest.mark.asyncio
async def test_event_item_removed_fires(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_name = AsyncMock(return_value={"id": "x", "name": "Milk"})

    with patch.object(EventBus, "async_fire") as mock_fire:
        ok = await coordinator.async_remove_item("kitchen_123", "Milk")

    assert ok is True
    event_calls = [c for c in mock_fire.call_args_list if c[0][0] == EVENT_ITEM_REMOVED]
    assert len(event_calls) == 1
    payload = event_calls[0][0][1]
    assert payload["item_name"] == "Milk"
    assert payload["inventory_id"] == "kitchen_123"


@pytest.mark.asyncio
async def test_event_item_removed_does_not_fire_when_missing(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_name = AsyncMock(return_value=None)

    with patch.object(EventBus, "async_fire") as mock_fire:
        ok = await coordinator.async_remove_item("kitchen_123", "nope")

    assert ok is False
    event_calls = [c for c in mock_fire.call_args_list if c[0][0] == EVENT_ITEM_REMOVED]
    assert len(event_calls) == 0


@pytest.mark.asyncio
async def test_event_item_depleted_fires(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_name = AsyncMock(
        return_value={"id": "milk-id", "name": "Milk", "quantity": 1}
    )
    mock_repository.update_item = AsyncMock(return_value=True)

    with patch.object(EventBus, "async_fire") as mock_fire:
        ok = await coordinator.async_decrement_item("kitchen_123", "Milk", 1)

    assert ok is True
    depleted_calls = [c for c in mock_fire.call_args_list if c[0][0] == EVENT_ITEM_DEPLETED]
    assert len(depleted_calls) == 1
    payload = depleted_calls[0][0][1]
    assert payload["item_name"] == "Milk"
    assert payload["previous_quantity"] == 1


@pytest.mark.asyncio
async def test_event_item_depleted_does_not_fire_when_not_zero(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_name = AsyncMock(
        return_value={"id": "milk-id", "name": "Milk", "quantity": 5}
    )
    mock_repository.update_item = AsyncMock(return_value=True)

    with patch.object(EventBus, "async_fire") as mock_fire:
        await coordinator.async_decrement_item("kitchen_123", "Milk", 2)

    depleted_calls = [c for c in mock_fire.call_args_list if c[0][0] == EVENT_ITEM_DEPLETED]
    assert len(depleted_calls) == 0


@pytest.mark.asyncio
async def test_event_item_restocked_fires(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_name = AsyncMock(
        return_value={"id": "milk-id", "name": "Milk", "quantity": 0}
    )
    mock_repository.update_item = AsyncMock(return_value=True)

    with patch.object(EventBus, "async_fire") as mock_fire:
        ok = await coordinator.async_increment_item("kitchen_123", "Milk", 3)

    assert ok is True
    restocked_calls = [c for c in mock_fire.call_args_list if c[0][0] == EVENT_ITEM_RESTOCKED]
    assert len(restocked_calls) == 1
    payload = restocked_calls[0][0][1]
    assert payload["item_name"] == "Milk"
    assert payload["quantity"] == 3


@pytest.mark.asyncio
async def test_event_item_restocked_does_not_fire_when_already_stocked(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_name = AsyncMock(
        return_value={"id": "milk-id", "name": "Milk", "quantity": 2}
    )
    mock_repository.update_item = AsyncMock(return_value=True)

    with patch.object(EventBus, "async_fire") as mock_fire:
        await coordinator.async_increment_item("kitchen_123", "Milk", 3)

    restocked_calls = [c for c in mock_fire.call_args_list if c[0][0] == EVENT_ITEM_RESTOCKED]
    assert len(restocked_calls) == 0


@pytest.mark.asyncio
async def test_event_quantity_changed_fires_on_increment(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_name = AsyncMock(
        return_value={"id": "milk-id", "name": "Milk", "quantity": 2}
    )
    mock_repository.update_item = AsyncMock(return_value=True)

    with patch.object(EventBus, "async_fire") as mock_fire:
        await coordinator.async_increment_item("kitchen_123", "Milk", 3)

    qty_calls = [c for c in mock_fire.call_args_list if c[0][0] == EVENT_ITEM_QUANTITY_CHANGED]
    assert len(qty_calls) == 1
    payload = qty_calls[0][0][1]
    assert payload["item_name"] == "Milk"
    assert payload["inventory_id"] == "kitchen_123"
    assert payload["quantity_before"] == 2
    assert payload["quantity_after"] == 5
    assert payload["amount"] == 3
    assert payload["direction"] == "increment"


@pytest.mark.asyncio
async def test_event_quantity_changed_fires_on_decrement(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_name = AsyncMock(
        return_value={"id": "milk-id", "name": "Milk", "quantity": 5}
    )
    mock_repository.update_item = AsyncMock(return_value=True)

    with patch.object(EventBus, "async_fire") as mock_fire:
        await coordinator.async_decrement_item("kitchen_123", "Milk", 2)

    qty_calls = [c for c in mock_fire.call_args_list if c[0][0] == EVENT_ITEM_QUANTITY_CHANGED]
    assert len(qty_calls) == 1
    payload = qty_calls[0][0][1]
    assert payload["quantity_before"] == 5
    assert payload["quantity_after"] == 3
    assert payload["amount"] == 2
    assert payload["direction"] == "decrement"


# ---------------------------------------------------------------------------
# Barcode lookup & scan tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lookup_by_barcode_found(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_barcode_global = AsyncMock(
        return_value=[
            {
                "id": "item-1",
                "inventory_id": "kitchen_123",
                "inventory_name": "Kitchen",
                FIELD_NAME: "Milk",
                FIELD_QUANTITY: 3.0,
            }
        ]
    )

    results = await coordinator.async_lookup_by_barcode("123456")
    assert len(results) == 1
    assert results[0][FIELD_NAME] == "Milk"
    mock_repository.get_item_by_barcode_global.assert_awaited_once_with("123456")


@pytest.mark.asyncio
async def test_lookup_by_barcode_not_found(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_barcode_global = AsyncMock(return_value=[])

    results = await coordinator.async_lookup_by_barcode("000000")
    assert results == []


@pytest.mark.asyncio
async def test_lookup_by_barcode_multiple_inventories(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_barcode_global = AsyncMock(
        return_value=[
            {"id": "a", "inventory_id": "inv1", "inventory_name": "Kitchen", FIELD_NAME: "Milk"},
            {"id": "b", "inventory_id": "inv2", "inventory_name": "Pantry", FIELD_NAME: "Milk"},
        ]
    )

    results = await coordinator.async_lookup_by_barcode("123456")
    assert len(results) == 2


@pytest.mark.asyncio
async def test_scan_barcode_increment(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_barcode_global = AsyncMock(
        return_value=[
            {
                "id": "milk-id",
                "inventory_id": "kitchen_123",
                "inventory_name": "Kitchen",
                FIELD_NAME: "Milk",
                FIELD_QUANTITY: 3.0,
            }
        ]
    )
    mock_repository.get_item_by_name = AsyncMock(
        return_value={"id": "milk-id", "name": "Milk", "quantity": 3}
    )
    mock_repository.update_item = AsyncMock(return_value=True)

    with patch.object(EventBus, "async_fire"):
        result = await coordinator.async_scan_barcode("123456", "increment", 2.0)

    assert result["action"] == "increment"
    assert result["success"] is True
    assert result["item_name"] == "Milk"
    assert result["amount"] == 2.0


@pytest.mark.asyncio
async def test_scan_barcode_decrement(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_barcode_global = AsyncMock(
        return_value=[
            {
                "id": "milk-id",
                "inventory_id": "kitchen_123",
                "inventory_name": "Kitchen",
                FIELD_NAME: "Milk",
                FIELD_QUANTITY: 5.0,
            }
        ]
    )
    mock_repository.get_item_by_name = AsyncMock(
        return_value={"id": "milk-id", "name": "Milk", "quantity": 5}
    )
    mock_repository.update_item = AsyncMock(return_value=True)

    with patch.object(EventBus, "async_fire"):
        result = await coordinator.async_scan_barcode("123456", "decrement", 1.0)

    assert result["action"] == "decrement"
    assert result["success"] is True


@pytest.mark.asyncio
async def test_scan_barcode_lookup(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_barcode_global = AsyncMock(
        return_value=[
            {
                "id": "milk-id",
                "inventory_id": "kitchen_123",
                "inventory_name": "Kitchen",
                FIELD_NAME: "Milk",
                FIELD_QUANTITY: 3.0,
            }
        ]
    )

    result = await coordinator.async_scan_barcode("123456", "lookup")

    assert result["action"] == "lookup"
    assert result["item"][FIELD_NAME] == "Milk"
    assert result["inventory_id"] == "kitchen_123"


@pytest.mark.asyncio
async def test_scan_barcode_with_inventory_id(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_barcode = AsyncMock(
        return_value={
            "id": "milk-id",
            "inventory_id": "kitchen_123",
            FIELD_NAME: "Milk",
            FIELD_QUANTITY: 3.0,
        }
    )
    mock_repository.get_item_by_name = AsyncMock(
        return_value={"id": "milk-id", "name": "Milk", "quantity": 3}
    )
    mock_repository.update_item = AsyncMock(return_value=True)

    with patch.object(EventBus, "async_fire"):
        result = await coordinator.async_scan_barcode(
            "123456", "increment", 1.0, inventory_id="kitchen_123"
        )

    assert result["action"] == "increment"
    mock_repository.get_item_by_barcode.assert_awaited_once_with("kitchen_123", "123456")


@pytest.mark.asyncio
async def test_scan_barcode_not_found(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_barcode_global = AsyncMock(return_value=[])

    with pytest.raises(ServiceValidationError, match="No item found for barcode"):
        await coordinator.async_scan_barcode("000000", "lookup")


@pytest.mark.asyncio
async def test_scan_barcode_ambiguous(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    mock_repository.get_item_by_barcode_global = AsyncMock(
        return_value=[
            {"id": "a", "inventory_id": "inv1", "inventory_name": "Kitchen", FIELD_NAME: "Milk"},
            {"id": "b", "inventory_id": "inv2", "inventory_name": "Pantry", FIELD_NAME: "Milk"},
        ]
    )

    with pytest.raises(ServiceValidationError, match="multiple inventories"):
        await coordinator.async_scan_barcode("123456", "increment")


@pytest.mark.asyncio
async def test_apply_barcode_updates_comma_separated(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    await coordinator._apply_barcode_updates("kitchen_123", "item-1", "BC-001, BC-002, BC-003")

    mock_repository.set_item_barcodes.assert_awaited_once_with(
        "item-1", "kitchen_123", ["BC-001", "BC-002", "BC-003"]
    )


@pytest.mark.asyncio
async def test_apply_barcode_updates_empty_clears(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    await coordinator._apply_barcode_updates("kitchen_123", "item-1", "")

    mock_repository.set_item_barcodes.assert_awaited_once_with("item-1", "kitchen_123", [])


@pytest.mark.asyncio
async def test_apply_barcode_updates_duplicate_raises_ha_error(
    coordinator: SimpleInventoryCoordinator, mock_repository: MagicMock
) -> None:
    """IntegrityError from duplicate barcode should surface as HomeAssistantError."""
    import aiosqlite
    from homeassistant.exceptions import HomeAssistantError

    mock_repository.set_item_barcodes.side_effect = aiosqlite.IntegrityError(
        "UNIQUE constraint failed"
    )

    with pytest.raises(HomeAssistantError, match="barcodes are already assigned"):
        await coordinator._apply_barcode_updates("kitchen_123", "item-1", "DUPE-BC")
