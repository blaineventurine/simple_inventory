"""Statistics mixin for SimpleInventoryCoordinator."""

from __future__ import annotations

from typing import Any

from ..const import (
    DEFAULT_CATEGORY,
    DEFAULT_DESIRED_QUANTITY,
    DEFAULT_LOCATION,
    DEFAULT_QUANTITY,
    DEFAULT_UNIT,
    FIELD_AUTO_ADD_TO_LIST_QUANTITY,
    FIELD_CATEGORIES,
    FIELD_CATEGORY,
    FIELD_DESIRED_QUANTITY,
    FIELD_LOCATION,
    FIELD_LOCATIONS,
    FIELD_NAME,
    FIELD_QUANTITY,
    FIELD_UNIT,
    compute_quantity_needed,
    is_below_threshold,
)
from ..hub import total_value as hub_total_value
from ._protocol import _CoordinatorProtocol


class _StatisticsMixin(_CoordinatorProtocol):
    """Mixin providing statistics for one inventory."""

    async def async_get_inventory_statistics(self, inventory_id: str) -> dict[str, Any]:
        """Compute aggregates for an inventory."""
        items = await self.async_list_items(inventory_id)

        total_items = len(items)
        total_quantity = sum(float(item.get(FIELD_QUANTITY, DEFAULT_QUANTITY)) for item in items)

        categories = self._group_counts(items, FIELD_CATEGORIES, FIELD_CATEGORY, DEFAULT_CATEGORY)
        locations = self._group_counts(items, FIELD_LOCATIONS, FIELD_LOCATION, DEFAULT_LOCATION)

        below_threshold = []
        for item in items:
            if not is_below_threshold(item):
                continue
            quantity = float(item.get(FIELD_QUANTITY, 0))
            threshold = float(item.get(FIELD_AUTO_ADD_TO_LIST_QUANTITY, 0))
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

        total_value = hub_total_value(items)

        expiring_items = await self.hub.async_items_expiring_soon(inventory_id)

        return {
            "total_items": total_items,
            "total_quantity": total_quantity,
            "total_value": total_value,
            FIELD_CATEGORIES: categories,
            FIELD_LOCATIONS: locations,
            "below_threshold": below_threshold,
            "expiring_items": expiring_items,
        }

    @staticmethod
    def _group_counts(
        items: list[dict[str, Any]],
        list_field: str,
        scalar_field: str,
        default: str,
    ) -> dict[str, int]:
        """Count items per value, preferring the array field and falling back to the scalar."""
        groups: dict[str, int] = {}
        for item in items:
            values = item.get(list_field)
            if not isinstance(values, list) or not values:
                values = [item.get(scalar_field) or default]
            for value in values:
                if value:
                    key = str(value)
                    groups[key] = groups.get(key, 0) + 1
        return groups
