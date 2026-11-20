"""Repository integration tests for consumption analytics queries."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime, timedelta
from typing import Any

import pytest
from homeassistant.core import HomeAssistant

from custom_components.simple_inventory.const import FIELD_NAME, FIELD_QUANTITY
from custom_components.simple_inventory.coordinator import SimpleInventoryCoordinator
from custom_components.simple_inventory.storage.repository import InventoryRepository


@pytest.fixture
async def repo(hass_with_tmp_config: HomeAssistant) -> AsyncGenerator[InventoryRepository, None]:
    repository = InventoryRepository(hass_with_tmp_config, db_filename="test_analytics.db")
    await repository.async_initialize()
    try:
        yield repository
    finally:
        await repository.async_close()


async def _seed_history(
    repo: InventoryRepository,
    item_id: str,
    inventory_id: str,
    events: list[dict[str, Any]],
) -> None:
    """Insert history events with controlled timestamps.

    Each event dict has: event_type, amount, and either days_ago (int) or an
    explicit ISO timestamp ``ts``; ``price`` is optional (default 0).
    """
    for ev in events:
        ts = ev.get("ts") or (datetime.utcnow() - timedelta(days=ev["days_ago"])).isoformat()
        conn = repo._connection()
        import uuid

        await conn.execute(
            """
            INSERT INTO consumption_history (
                id, item_id, inventory_id, event_type, amount,
                quantity_before, quantity_after, source, timestamp, price
            ) VALUES (?, ?, ?, ?, ?, 0, 0, 'test', ?, ?)
            """,
            (
                str(uuid.uuid4()),
                item_id,
                inventory_id,
                ev["event_type"],
                ev["amount"],
                ts,
                ev.get("price", 0),
            ),
        )
        await conn.commit()


class TestGetItemConsumptionStats:
    async def test_no_history_returns_zeros(self, repo: InventoryRepository) -> None:
        await repo.upsert_inventory("inv1", "Test")
        item_id = await repo.create_item("inv1", {FIELD_NAME: "milk", FIELD_QUANTITY: 5})

        result = await repo.get_item_consumption_stats(item_id)

        assert result["decrement_count"] == 0
        assert result["total_consumed"] == 0.0
        assert result["first_event_ts"] is None
        assert result["last_event_ts"] is None
        assert result["restock_count"] == 0
        assert result["restock_timestamps"] == []
        assert result["window_days"] is None

    async def test_multiple_decrements(self, repo: InventoryRepository) -> None:
        await repo.upsert_inventory("inv1", "Test")
        item_id = await repo.create_item("inv1", {FIELD_NAME: "milk", FIELD_QUANTITY: 5})

        await _seed_history(
            repo,
            item_id,
            "inv1",
            [
                {"event_type": "decrement", "amount": 1.0, "days_ago": 10},
                {"event_type": "decrement", "amount": 2.5, "days_ago": 5},
                {"event_type": "decrement", "amount": 0.5, "days_ago": 1},
            ],
        )

        result = await repo.get_item_consumption_stats(item_id)

        assert result["decrement_count"] == 3
        assert result["total_consumed"] == 4.0
        assert result["first_event_ts"] is not None
        assert result["last_event_ts"] is not None

    async def test_window_days_filters_old_events(self, repo: InventoryRepository) -> None:
        await repo.upsert_inventory("inv1", "Test")
        item_id = await repo.create_item("inv1", {FIELD_NAME: "milk", FIELD_QUANTITY: 5})

        await _seed_history(
            repo,
            item_id,
            "inv1",
            [
                {"event_type": "decrement", "amount": 1.0, "days_ago": 60},
                {"event_type": "decrement", "amount": 2.0, "days_ago": 10},
            ],
        )

        result = await repo.get_item_consumption_stats(item_id, window_days=30)

        assert result["decrement_count"] == 1
        assert result["total_consumed"] == 2.0
        assert result["window_days"] == 30

    async def test_window_none_includes_all(self, repo: InventoryRepository) -> None:
        await repo.upsert_inventory("inv1", "Test")
        item_id = await repo.create_item("inv1", {FIELD_NAME: "milk", FIELD_QUANTITY: 5})

        await _seed_history(
            repo,
            item_id,
            "inv1",
            [
                {"event_type": "decrement", "amount": 1.0, "days_ago": 200},
                {"event_type": "decrement", "amount": 2.0, "days_ago": 10},
            ],
        )

        result = await repo.get_item_consumption_stats(item_id, window_days=None)

        assert result["decrement_count"] == 2
        assert result["total_consumed"] == 3.0

    async def test_restock_timestamps_includes_increment_and_add(
        self, repo: InventoryRepository
    ) -> None:
        await repo.upsert_inventory("inv1", "Test")
        item_id = await repo.create_item("inv1", {FIELD_NAME: "milk", FIELD_QUANTITY: 5})

        await _seed_history(
            repo,
            item_id,
            "inv1",
            [
                {"event_type": "increment", "amount": 3.0, "days_ago": 20},
                {"event_type": "add", "amount": 5.0, "days_ago": 10},
                {"event_type": "decrement", "amount": 1.0, "days_ago": 5},
            ],
        )

        result = await repo.get_item_consumption_stats(item_id)

        assert result["restock_count"] == 2
        assert len(result["restock_timestamps"]) == 2


class TestGetInventoryConsumptionStats:
    async def test_returns_all_items_including_zero_activity(
        self, repo: InventoryRepository
    ) -> None:
        await repo.upsert_inventory("inv1", "Test")
        await repo.create_item("inv1", {FIELD_NAME: "milk", FIELD_QUANTITY: 5})
        item_id2 = await repo.create_item("inv1", {FIELD_NAME: "bread", FIELD_QUANTITY: 2})

        await _seed_history(
            repo,
            item_id2,
            "inv1",
            [
                {"event_type": "decrement", "amount": 1.0, "days_ago": 5},
            ],
        )

        results = await repo.get_inventory_consumption_stats("inv1")

        assert len(results) == 2
        names = {r["item_name"] for r in results}
        assert names == {"milk", "bread"}

        # milk has no history
        milk = next(r for r in results if r["item_name"] == "milk")
        assert milk["decrement_count"] == 0

        # bread has history
        bread = next(r for r in results if r["item_name"] == "bread")
        assert bread["decrement_count"] == 1
        assert bread["total_consumed"] == 1.0

    async def test_per_item_aggregates_correct(self, repo: InventoryRepository) -> None:
        await repo.upsert_inventory("inv1", "Test")
        item_a = await repo.create_item("inv1", {FIELD_NAME: "apple", FIELD_QUANTITY: 10})
        item_b = await repo.create_item("inv1", {FIELD_NAME: "banana", FIELD_QUANTITY: 3})

        await _seed_history(
            repo,
            item_a,
            "inv1",
            [
                {"event_type": "decrement", "amount": 2.0, "days_ago": 10},
                {"event_type": "decrement", "amount": 3.0, "days_ago": 5},
            ],
        )
        await _seed_history(
            repo,
            item_b,
            "inv1",
            [
                {"event_type": "decrement", "amount": 1.0, "days_ago": 3},
            ],
        )

        results = await repo.get_inventory_consumption_stats("inv1")

        apple = next(r for r in results if r["item_name"] == "apple")
        assert apple["decrement_count"] == 2
        assert apple["total_consumed"] == 5.0

        banana = next(r for r in results if r["item_name"] == "banana")
        assert banana["decrement_count"] == 1
        assert banana["total_consumed"] == 1.0

    async def test_window_filter_applies_across_all_items(self, repo: InventoryRepository) -> None:
        await repo.upsert_inventory("inv1", "Test")
        item_a = await repo.create_item("inv1", {FIELD_NAME: "apple", FIELD_QUANTITY: 10})
        item_b = await repo.create_item("inv1", {FIELD_NAME: "banana", FIELD_QUANTITY: 3})

        await _seed_history(
            repo,
            item_a,
            "inv1",
            [
                {"event_type": "decrement", "amount": 2.0, "days_ago": 60},
                {"event_type": "decrement", "amount": 3.0, "days_ago": 5},
            ],
        )
        await _seed_history(
            repo,
            item_b,
            "inv1",
            [
                {"event_type": "decrement", "amount": 1.0, "days_ago": 60},
            ],
        )

        results = await repo.get_inventory_consumption_stats("inv1", window_days=30)

        apple = next(r for r in results if r["item_name"] == "apple")
        assert apple["decrement_count"] == 1
        assert apple["total_consumed"] == 3.0

        banana = next(r for r in results if r["item_name"] == "banana")
        assert banana["decrement_count"] == 0
        assert banana["total_consumed"] == 0.0


class TestInventoryConsumptionSpend:
    async def test_inventory_stats_include_spend(self, repo: InventoryRepository) -> None:
        await repo.upsert_inventory("inv1", "Test")
        item_id = await repo.create_item("inv1", {FIELD_NAME: "milk", FIELD_QUANTITY: 5})
        await _seed_history(
            repo,
            item_id,
            "inv1",
            [
                {"event_type": "increment", "amount": 2.0, "days_ago": 10, "price": 3.0},
                {"event_type": "add", "amount": 1.0, "days_ago": 8, "price": 4.0},
                {"event_type": "increment", "amount": 1.0, "days_ago": 6},
            ],
        )

        results = await repo.get_inventory_consumption_stats("inv1")

        milk = next(r for r in results if r["item_name"] == "milk")
        assert milk["total_spend"] == 10.0
        assert milk["restock_spend_count"] == 2
        assert milk["first_spend_ts"] is not None

    async def test_inventory_rates_report_spend_like_item_rates(
        self, repo: InventoryRepository
    ) -> None:
        await repo.upsert_inventory("inv1", "Test")
        item_id = await repo.create_item("inv1", {FIELD_NAME: "milk", FIELD_QUANTITY: 5})
        await _seed_history(
            repo,
            item_id,
            "inv1",
            [{"event_type": "increment", "amount": 2.0, "days_ago": 10, "price": 5.0}],
        )

        item_raw = await repo.get_item_consumption_stats(item_id)
        inv_raw = next(r for r in await repo.get_inventory_consumption_stats("inv1"))
        item_rates = SimpleInventoryCoordinator._compute_consumption_rates(item_raw, 5.0)
        inv_rates = SimpleInventoryCoordinator._compute_consumption_rates(inv_raw, 5.0)

        assert inv_rates["total_spend"] == 10.0
        assert inv_rates["daily_spend_rate"] == item_rates["daily_spend_rate"]
        assert inv_rates["weekly_spend_rate"] == item_rates["weekly_spend_rate"]


class TestSpendRateSpan:
    async def test_spend_span_starts_at_first_priced_restock(
        self, repo: InventoryRepository
    ) -> None:
        """$20 spent 10 days ago, decrements only in the last 2 days → ~$2/day, not $10/day."""
        await repo.upsert_inventory("inv1", "Test")
        item_id = await repo.create_item("inv1", {FIELD_NAME: "milk", FIELD_QUANTITY: 5})
        await _seed_history(
            repo,
            item_id,
            "inv1",
            [
                {"event_type": "increment", "amount": 2.0, "days_ago": 10, "price": 10.0},
                {"event_type": "decrement", "amount": 1.0, "days_ago": 2},
                {"event_type": "decrement", "amount": 1.0, "days_ago": 1},
            ],
        )

        raw = await repo.get_item_consumption_stats(item_id)
        rates = SimpleInventoryCoordinator._compute_consumption_rates(raw, 5.0)

        assert rates["daily_spend_rate"] is not None
        assert rates["daily_spend_rate"] == pytest.approx(2.0, rel=0.01)

    async def test_spend_span_without_any_decrements(self, repo: InventoryRepository) -> None:
        await repo.upsert_inventory("inv1", "Test")
        item_id = await repo.create_item("inv1", {FIELD_NAME: "milk", FIELD_QUANTITY: 5})
        await _seed_history(
            repo,
            item_id,
            "inv1",
            [{"event_type": "increment", "amount": 2.0, "days_ago": 10, "price": 10.0}],
        )

        results = await repo.get_inventory_consumption_stats("inv1")
        rates = SimpleInventoryCoordinator._compute_consumption_rates(results[0], 5.0)

        assert rates["daily_spend_rate"] == pytest.approx(2.0, rel=0.01)


class TestWindowedRateSpan:
    async def test_window_rate_uses_days_since_first_event_in_window(
        self, repo: InventoryRepository
    ) -> None:
        """6 consumed over the last 3 days of a 30-day window → ~2/day, not 0.2/day."""
        await repo.upsert_inventory("inv1", "Test")
        item_id = await repo.create_item("inv1", {FIELD_NAME: "milk", FIELD_QUANTITY: 5})
        await _seed_history(
            repo,
            item_id,
            "inv1",
            [
                {"event_type": "decrement", "amount": 2.0, "days_ago": 3},
                {"event_type": "decrement", "amount": 2.0, "days_ago": 2},
                {"event_type": "decrement", "amount": 2.0, "days_ago": 1},
            ],
        )

        raw = await repo.get_item_consumption_stats(item_id, window_days=30)
        rates = SimpleInventoryCoordinator._compute_consumption_rates(raw, 5.0, min_events=1)

        assert rates["daily_rate"] == pytest.approx(2.0, rel=0.01)

    async def test_window_rate_recent_burst_uses_one_day_floor(
        self, repo: InventoryRepository
    ) -> None:
        await repo.upsert_inventory("inv1", "Test")
        item_id = await repo.create_item("inv1", {FIELD_NAME: "milk", FIELD_QUANTITY: 5})
        await _seed_history(
            repo,
            item_id,
            "inv1",
            [
                {"event_type": "decrement", "amount": 100.0, "days_ago": 60},
                {"event_type": "decrement", "amount": 3.0, "days_ago": 0.25},
            ],
        )

        raw = await repo.get_item_consumption_stats(item_id, window_days=5)
        rates = SimpleInventoryCoordinator._compute_consumption_rates(raw, 5.0, min_events=1)

        # Only the recent event is inside the 5-day window; its age (<1 day) is floored to 1.
        assert rates["daily_rate"] == 3.0


class TestHistoryEndDate:
    async def test_date_only_end_date_includes_whole_day(self, repo: InventoryRepository) -> None:
        await repo.upsert_inventory("inv1", "Test")
        item_id = await repo.create_item("inv1", {FIELD_NAME: "milk", FIELD_QUANTITY: 5})
        await _seed_history(
            repo,
            item_id,
            "inv1",
            [
                {"event_type": "decrement", "amount": 1.0, "ts": "2025-03-10T00:00:00"},
                {"event_type": "decrement", "amount": 1.0, "ts": "2025-03-10T15:30:00.123456"},
                {"event_type": "decrement", "amount": 1.0, "ts": "2025-03-11T00:00:00"},
            ],
        )

        item_events = await repo.get_item_history(item_id, end_date="2025-03-10")
        inv_events = await repo.get_inventory_history(
            "inv1", start_date="2025-03-10", end_date="2025-03-10"
        )

        expected = ["2025-03-10T15:30:00.123456", "2025-03-10T00:00:00"]
        assert [e["timestamp"] for e in item_events] == expected
        assert [e["timestamp"] for e in inv_events] == expected

    async def test_full_timestamp_end_date_is_exact(self, repo: InventoryRepository) -> None:
        await repo.upsert_inventory("inv1", "Test")
        item_id = await repo.create_item("inv1", {FIELD_NAME: "milk", FIELD_QUANTITY: 5})
        await _seed_history(
            repo,
            item_id,
            "inv1",
            [
                {"event_type": "decrement", "amount": 1.0, "ts": "2025-03-10T10:00:00"},
                {"event_type": "decrement", "amount": 1.0, "ts": "2025-03-10T15:30:00"},
            ],
        )

        events = await repo.get_item_history(item_id, end_date="2025-03-10T12:00:00")

        assert [e["timestamp"] for e in events] == ["2025-03-10T10:00:00"]
