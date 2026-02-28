"""Statistics mixin for SimpleInventoryCoordinator."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

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

    async def async_get_items_expiring_soon(
        self, inventory_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Return items expiring within their individual thresholds."""
        await self.async_initialize()

        if inventory_id:
            inventories = {inventory_id: await self.async_list_items(inventory_id)}
        else:
            inventories = {}
            for inventory in await self.repository.list_inventories():
                inv_id = inventory["id"]
                inventories[inv_id] = await self.async_list_items(inv_id)

        now = datetime.now().date()
        expiring: list[dict[str, Any]] = []

        for inv_id, items in inventories.items():
            for item in items:
                expiry_str = item.get(FIELD_EXPIRY_DATE, "")
                threshold = int(item.get(FIELD_EXPIRY_ALERT_DAYS, DEFAULT_EXPIRY_ALERT_DAYS))
                quantity = float(item.get(FIELD_QUANTITY, DEFAULT_QUANTITY))

                if not expiry_str or quantity <= 0:
                    continue

                try:
                    expiry_date = datetime.strptime(expiry_str, "%Y-%m-%d").date()
                except ValueError:
                    _LOGGER.warning(
                        "Invalid expiry date format for %s: %s", item.get(FIELD_NAME), expiry_str
                    )
                    continue

                if expiry_date <= now + timedelta(days=threshold):
                    expiring.append(
                        {
                            "inventory_id": inv_id,
                            FIELD_NAME: item.get(FIELD_NAME),
                            FIELD_EXPIRY_DATE: expiry_str,
                            "days_until_expiry": (expiry_date - now).days,
                            "threshold": threshold,
                            **item,
                        }
                    )

        expiring.sort(key=lambda entry: entry["days_until_expiry"])
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
