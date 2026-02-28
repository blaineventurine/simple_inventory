"""Analytics mixin for SimpleInventoryCoordinator."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..const import (
    ANALYTICS_MIN_EVENTS,
    FIELD_NAME,
    FIELD_QUANTITY,
    FIELD_UNIT,
)
from ._protocol import _CoordinatorProtocol


def _compute_avg_restock_days(timestamps: list[str]) -> float | None:
    """Compute mean gap in days between consecutive restock timestamps."""
    if len(timestamps) < 2:
        return None
    parsed = sorted(datetime.fromisoformat(ts) for ts in timestamps)
    gaps = [(parsed[i + 1] - parsed[i]).total_seconds() / 86400 for i in range(len(parsed) - 1)]
    return round(sum(gaps) / len(gaps), 1)


class _AnalyticsMixin(_CoordinatorProtocol):
    """Mixin providing consumption analytics methods."""

    @staticmethod
    def _compute_consumption_rates(
        raw: dict[str, Any],
        current_quantity: float,
        min_events: int = ANALYTICS_MIN_EVENTS,
    ) -> dict[str, Any]:
        """Derive consumption rates from raw aggregates."""
        decrement_count = raw["decrement_count"]
        total_consumed = raw["total_consumed"]
        window_days = raw["window_days"]
        first_event_ts = raw.get("first_event_ts")
        has_sufficient_data = decrement_count >= min_events

        daily_rate: float | None = None
        weekly_rate: float | None = None
        days_until_depletion: float | None = None

        if has_sufficient_data and total_consumed > 0:
            if window_days is not None:
                span_days = float(window_days)
            elif first_event_ts:
                first_dt = datetime.fromisoformat(first_event_ts)
                span_days = max((datetime.utcnow() - first_dt).total_seconds() / 86400, 1.0)
            else:
                span_days = 1.0

            daily_rate = round(total_consumed / span_days, 4)
            weekly_rate = round(daily_rate * 7, 4)

            if daily_rate > 0:
                days_until_depletion = round(current_quantity / daily_rate, 1)

        avg_restock_days = _compute_avg_restock_days(raw.get("restock_timestamps", []))

        # Spend rate calculations
        total_spend = raw.get("total_spend", 0.0)
        restock_spend_count = raw.get("restock_spend_count", 0)
        daily_spend_rate: float | None = None
        weekly_spend_rate: float | None = None

        if restock_spend_count > 0 and total_spend > 0:
            if window_days is not None:
                spend_span = float(window_days)
            elif first_event_ts:
                first_dt = datetime.fromisoformat(first_event_ts)
                spend_span = max((datetime.utcnow() - first_dt).total_seconds() / 86400, 1.0)
            else:
                spend_span = 1.0
            daily_spend_rate = round(total_spend / spend_span, 4)
            weekly_spend_rate = round(daily_spend_rate * 7, 4)

        return {
            "decrement_count": decrement_count,
            "total_consumed": total_consumed,
            "window_days": window_days,
            "daily_rate": daily_rate,
            "weekly_rate": weekly_rate,
            "days_until_depletion": days_until_depletion,
            "avg_restock_days": avg_restock_days,
            "has_sufficient_data": has_sufficient_data,
            "total_spend": total_spend if total_spend > 0 else None,
            "daily_spend_rate": daily_spend_rate,
            "weekly_spend_rate": weekly_spend_rate,
        }

    async def async_get_item_consumption_rates(
        self,
        inventory_id: str,
        item_name: str,
        *,
        window_days: int | None = None,
    ) -> dict[str, Any] | None:
        """Return consumption rates for a single item."""
        await self.async_initialize()
        item = await self.repository.get_item_by_name(inventory_id, item_name)
        if not item:
            return None

        raw = await self.repository.get_item_consumption_stats(item["id"], window_days=window_days)
        rates = self._compute_consumption_rates(raw, float(item.get(FIELD_QUANTITY, 0)))
        rates["item_name"] = item.get(FIELD_NAME, item_name)
        rates["current_quantity"] = float(item.get(FIELD_QUANTITY, 0))
        rates["unit"] = item.get(FIELD_UNIT, "")
        return rates

    async def async_get_inventory_consumption_rates(
        self,
        inventory_id: str,
        *,
        window_days: int | None = None,
    ) -> dict[str, Any]:
        """Return consumption rates for all items in an inventory."""
        await self.async_initialize()
        rows = await self.repository.get_inventory_consumption_stats(
            inventory_id, window_days=window_days
        )

        items: list[dict[str, Any]] = []
        for row in rows:
            rates = self._compute_consumption_rates(row, row["current_quantity"])
            rates["item_name"] = row["item_name"]
            rates["current_quantity"] = row["current_quantity"]
            rates["unit"] = row["unit"]
            items.append(rates)

        tracked = [i for i in items if i["decrement_count"] > 0]
        total_consumed = sum(i["total_consumed"] for i in items)

        most_consumed = sorted(tracked, key=lambda x: x["total_consumed"], reverse=True)[:5]
        running_out = sorted(
            (i for i in items if i["days_until_depletion"] is not None),
            key=lambda x: x["days_until_depletion"],
        )[:5]

        return {
            "inventory_id": inventory_id,
            "window_days": window_days,
            "items": items,
            "summary": {
                "total_items_tracked": len(tracked),
                "total_consumed": total_consumed,
                "most_consumed": [
                    {
                        "item_name": i["item_name"],
                        "total_consumed": i["total_consumed"],
                        "daily_rate": i["daily_rate"],
                    }
                    for i in most_consumed
                ],
                "running_out_soonest": [
                    {
                        "item_name": i["item_name"],
                        "days_until_depletion": i["days_until_depletion"],
                        "current_quantity": i["current_quantity"],
                    }
                    for i in running_out
                ],
            },
        }
