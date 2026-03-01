"""Statistics mixin for SimpleInventoryCoordinator."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from ..const import (
    DEFAULT_CATEGORY,
    DEFAULT_DESIRED_QUANTITY,
    DEFAULT_EXPIRY_ALERT_DAYS,
    DEFAULT_LOCATION,
    DEFAULT_QUANTITY,
    DEFAULT_UNIT,
    FIELD_AUTO_ADD_TO_LIST_QUANTITY,
    FIELD_CATEGORY,
    FIELD_DESIRED_QUANTITY,
    FIELD_EXPIRY_ALERT_DAYS,
    FIELD_EXPIRY_DATE,
    FIELD_LOCATION,
    FIELD_NAME,
    FIELD_PRICE,
    FIELD_QUANTITY,
    FIELD_UNIT,
    compute_quantity_needed,
)
from ._protocol import _CoordinatorProtocol

_LOGGER = logging.getLogger(__name__)


class _StatisticsMixin(_CoordinatorProtocol):
    """Mixin providing inventory statistics and expiry methods."""

    async def async_get_inventory_statistics(self, inventory_id: str) -> dict[str, Any]:
        """Compute aggregates for an inventory."""
        items = await self.async_list_items(inventory_id)

        total_items = len(items)
        total_quantity = sum(float(item.get(FIELD_QUANTITY, DEFAULT_QUANTITY)) for item in items)

        categories = self._group_items_by_field(items, FIELD_CATEGORY, DEFAULT_CATEGORY)
        locations = self._group_location_counts(items)

        below_threshold = []
        for item in items:
            quantity = float(item.get(FIELD_QUANTITY, 0))
            threshold = float(item.get(FIELD_AUTO_ADD_TO_LIST_QUANTITY, 0))
            if threshold > 0 and quantity <= threshold:
                desired = float(item.get(FIELD_DESIRED_QUANTITY, DEFAULT_DESIRED_QUANTITY))
                quantity_needed = compute_quantity_needed(quantity, threshold, desired)
                below_threshold.append(
                    {
                        FIELD_NAME: item.get(FIELD_NAME),
                        FIELD_QUANTITY: quantity,
                        "threshold": threshold,
                        FIELD_DESIRED_QUANTITY: desired,
                        "quantity_needed": quantity_needed,
                        FIELD_UNIT: item.get(FIELD_UNIT, DEFAULT_UNIT),
                        FIELD_CATEGORY: item.get(FIELD_CATEGORY, DEFAULT_CATEGORY),
                    }
                )

        total_value = sum(
            float(item.get(FIELD_QUANTITY, 0)) * float(item.get(FIELD_PRICE, 0))
            for item in items
            if float(item.get(FIELD_PRICE, 0)) > 0
        )

        expiring_items = await self.async_get_items_expiring_soon(inventory_id)

        return {
            "total_items": total_items,
            "total_quantity": total_quantity,
            "total_value": total_value,
            "categories": categories,
            "locations": locations,
            "below_threshold": below_threshold,
            "expiring_items": expiring_items,
        }

    _EXPIRY_CACHE_TTL = 2.0  # seconds — shared between paired sensors in one update cycle

    async def async_get_items_expiring_soon(
        self, inventory_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Return items expiring within their individual thresholds.

        Results are cached for _EXPIRY_CACHE_TTL seconds so that paired sensors
        (ItemsExpiringSoonSensor + ExpiredItemsSensor) sharing the same update cycle
        only hit the database once per inventory.
        """
        cache: dict[str | None, tuple[float, list[dict[str, Any]]]] = getattr(
            self, "_expiry_cache", {}
        )
        if not hasattr(self, "_expiry_cache"):
            self._expiry_cache: dict[str | None, tuple[float, list[dict[str, Any]]]] = cache

        cached = cache.get(inventory_id)
        if cached is not None:
            ts, result = cached
            age = time.monotonic() - ts
            if age < self._EXPIRY_CACHE_TTL:
                _LOGGER.debug(
                    "async_get_items_expiring_soon(%s): cache HIT (age=%.3fs, %d items)",
                    inventory_id,
                    age,
                    len(result),
                )
                return result
            _LOGGER.debug(
                "async_get_items_expiring_soon(%s): cache EXPIRED (age=%.3fs)", inventory_id, age
            )
        else:
            _LOGGER.debug("async_get_items_expiring_soon(%s): cache MISS (no entry)", inventory_id)

        await self.async_initialize()

        if inventory_id:
            inventories = {inventory_id: await self.async_list_items(inventory_id)}
        else:
            inventories = {}
            for inventory in await self.repository.list_inventories():
                inv_id = inventory["id"]
                inventories[inv_id] = await self.async_list_items(inv_id)

        now = dt_util.utcnow().date()
        _LOGGER.debug("async_get_items_expiring_soon(%s): now (UTC) = %s", inventory_id, now)
        expiring: list[dict[str, Any]] = []

        for inv_id, items in inventories.items():
            _LOGGER.debug(
                "async_get_items_expiring_soon: scanning inventory=%s (%d items)",
                inv_id,
                len(items),
            )
            for item in items:
                item_name = item.get(FIELD_NAME, "<unknown>")
                expiry_str = item.get(FIELD_EXPIRY_DATE, "")
                if not expiry_str:
                    _LOGGER.debug("  %s: no expiry_date — skipped", item_name)
                    continue

                try:
                    raw_threshold = item.get(FIELD_EXPIRY_ALERT_DAYS)
                    threshold = (
                        max(0, int(raw_threshold))
                        if raw_threshold is not None
                        else DEFAULT_EXPIRY_ALERT_DAYS
                    )
                except (TypeError, ValueError):
                    threshold = DEFAULT_EXPIRY_ALERT_DAYS
                try:
                    raw_quantity = item.get(FIELD_QUANTITY)
                    quantity = float(raw_quantity) if raw_quantity is not None else DEFAULT_QUANTITY
                except (TypeError, ValueError):
                    quantity = DEFAULT_QUANTITY

                if quantity <= 0:
                    _LOGGER.debug(
                        "  %s: qty=%.2f — skipped (zero/negative quantity)", item_name, quantity
                    )
                    continue

                try:
                    expiry_date = datetime.strptime(expiry_str, "%Y-%m-%d").date()
                except ValueError:
                    _LOGGER.warning(
                        "Invalid expiry date format for %s: %s", item.get(FIELD_NAME), expiry_str
                    )
                    continue

                days = (expiry_date - now).days
                cutoff = now + timedelta(days=threshold)
                included = expiry_date <= cutoff
                _LOGGER.debug(
                    "  %s: expiry=%s days_until=%d threshold=%d cutoff=%s → %s",
                    item_name,
                    expiry_str,
                    days,
                    threshold,
                    cutoff,
                    "INCLUDED" if included else "excluded",
                )
                if included:
                    expiring.append(
                        {
                            **item,
                            "inventory_id": inv_id,
                            FIELD_NAME: item.get(FIELD_NAME),
                            FIELD_EXPIRY_DATE: expiry_str,
                            "days_until_expiry": days,
                            "threshold": threshold,
                        }
                    )

        expiring.sort(key=lambda entry: entry["days_until_expiry"])
        _LOGGER.debug(
            "async_get_items_expiring_soon(%s): returning %d items (expired=%d, expiring_soon=%d)",
            inventory_id,
            len(expiring),
            sum(1 for e in expiring if e["days_until_expiry"] < 0),
            sum(1 for e in expiring if e["days_until_expiry"] >= 0),
        )
        cache[inventory_id] = (time.monotonic(), expiring)
        return expiring

    def _group_items_by_field(
        self,
        items: list[dict[str, Any]],
        field: str,
        default: str,
    ) -> dict[str, int]:
        groups: dict[str, int] = {}
        for item in items:
            value = item.get(field, default)
            if isinstance(value, list):
                for entry in value:
                    if entry:
                        key = str(entry)
                        groups[key] = groups.get(key, 0) + 1
            else:
                key = str(value) if value else default
                if key:
                    groups[key] = groups.get(key, 0) + 1
        return groups

    def _group_location_counts(self, items: list[dict[str, Any]]) -> dict[str, int]:
        locations: dict[str, int] = {}
        for item in items:
            loc_list = item.get("locations", [])
            if isinstance(loc_list, list) and loc_list:
                for name in loc_list:
                    if name:
                        locations[name] = locations.get(name, 0) + 1
            else:
                name = item.get(FIELD_LOCATION, DEFAULT_LOCATION)
                if name:
                    locations[name] = locations.get(name, 0) + 1
        return locations
