"""InventoryHub: every read across inventories, and the one expiry cache.

Coordinators (one per config entry) keep the per-inventory operations; anything that
reads several inventories, or a cache several readers share, lives here so a write
through any coordinator is seen by every reader (``invalidate`` on each update event).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta
from typing import Any, Final

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from .const import (
    ATTENTION_SECTIONS,
    DEFAULT_DESIRED_QUANTITY,
    DEFAULT_EXPIRY_ALERT_DAYS,
    DOMAIN,
    FIELD_AUTO_ADD_TO_LIST_QUANTITY,
    FIELD_BATCH_ID,
    FIELD_BATCHES,
    FIELD_DESIRED_QUANTITY,
    FIELD_EXPIRY_ALERT_DAYS,
    FIELD_EXPIRY_DATE,
    FIELD_ITEMS,
    FIELD_LOCATION,
    FIELD_NAME,
    FIELD_QUANTITY,
    FIELD_UNIT_PRICE,
    compute_quantity_needed,
    is_below_threshold,
    is_out_of_stock,
    partition_expiry,
    round_quantity,
)
from .entries import enabled_inventory_entries
from .expiry_cache import ExpiryCache
from .storage.repository import InventoryRepository

_LOGGER = logging.getLogger(__name__)

# ``matched`` for each repository search rank (0-2 are exact, prefix and substring name).
_MATCH_REASONS: Final = (
    "name",
    "name",
    "name",
    "alias",
    "barcode",
    "category",
    "location",
    "description",
    "unit",
)


def expiry_entries(
    items: Iterable[Mapping[str, Any]], inventory_id: str, today: date
) -> list[dict[str, Any]]:
    """One entry per batch of *items* expiring within its item's alert window (or expired).

    Each entry is the item without ``batches``, plus ``inventory_id``, the batch's id,
    quantity, location and expiry date, ``days_until_expiry`` and ``threshold``.
    """
    expiring: list[dict[str, Any]] = []
    for item in items:
        item_name = item.get(FIELD_NAME, "<unknown>")
        try:
            raw_threshold = item.get(FIELD_EXPIRY_ALERT_DAYS)
            threshold = (
                max(0, int(raw_threshold))
                if raw_threshold is not None
                else DEFAULT_EXPIRY_ALERT_DAYS
            )
        except (TypeError, ValueError):
            threshold = DEFAULT_EXPIRY_ALERT_DAYS
        cutoff = today + timedelta(days=threshold)
        base = {k: v for k, v in item.items() if k != FIELD_BATCHES}

        for batch in item.get(FIELD_BATCHES, []):
            expiry_str = batch[FIELD_EXPIRY_DATE]
            if not expiry_str:
                continue
            try:
                expiry_date = datetime.strptime(expiry_str, "%Y-%m-%d").date()
            except ValueError:
                _LOGGER.warning("Invalid expiry date format for %s: %s", item_name, expiry_str)
                continue

            days = (expiry_date - today).days
            included = expiry_date <= cutoff
            _LOGGER.debug(
                "  %s batch %s: expiry=%s days_until=%d threshold=%d cutoff=%s → %s",
                item_name,
                batch["id"],
                expiry_str,
                days,
                threshold,
                cutoff,
                "INCLUDED" if included else "excluded",
            )
            if included:
                expiring.append(
                    {
                        **base,
                        "inventory_id": inventory_id,
                        FIELD_BATCH_ID: batch["id"],
                        FIELD_QUANTITY: batch[FIELD_QUANTITY],
                        FIELD_LOCATION: batch[FIELD_LOCATION],
                        FIELD_EXPIRY_DATE: expiry_str,
                        "days_until_expiry": days,
                        "threshold": threshold,
                    }
                )
    return expiring


def total_value(items: Iterable[Mapping[str, Any]]) -> float:
    """Sum of quantity × unit price over every priced batch of *items*."""
    return sum(
        float(batch[FIELD_QUANTITY]) * float(batch[FIELD_UNIT_PRICE])
        for item in items
        for batch in item.get(FIELD_BATCHES, [])
        if float(batch[FIELD_UNIT_PRICE]) > 0
    )


def _batch_totals(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Count and total quantity of expiry (per-batch) entries."""
    return {
        "batches": len(entries),
        FIELD_QUANTITY: round_quantity(sum(float(entry[FIELD_QUANTITY]) for entry in entries)),
    }


def _attention(
    item: Mapping[str, Any], expiry_entries: list[dict[str, Any]]
) -> tuple[str, dict[str, Any], tuple[float, ...]] | None:
    """The item's most urgent section, its reason and its leading sort key; None if fine."""
    expired, expiring_soon = partition_expiry(expiry_entries)
    if expired:
        days_overdue = -min(entry["days_until_expiry"] for entry in expired)
        return "expired", {"days_overdue": days_overdue, **_batch_totals(expired)}, (-days_overdue,)
    if expiring_soon:
        days = min(entry["days_until_expiry"] for entry in expiring_soon)
        return "expiring_soon", {"days_until_expiry": days, **_batch_totals(expiring_soon)}, (days,)
    quantity = float(item.get(FIELD_QUANTITY, 0))
    if is_out_of_stock(item):
        return "out_of_stock", {}, ()
    if is_below_threshold(item):
        threshold = float(item.get(FIELD_AUTO_ADD_TO_LIST_QUANTITY, 0))
        desired = float(item.get(FIELD_DESIRED_QUANTITY, DEFAULT_DESIRED_QUANTITY))
        reason = {
            "threshold": threshold,
            "quantity_needed": compute_quantity_needed(quantity, threshold, desired),
        }
        return "low_stock", reason, ()
    return None


class InventoryHub:
    """Cross-inventory reads over the shared repository, with one expiry cache.

    "All inventories" means the enabled inventory entries, as for search and the overview:
    a disabled entry's data, and data left by a deleted entry, are never listed.
    """

    def __init__(self, hass: HomeAssistant, repository: InventoryRepository) -> None:
        self.hass = hass
        self.repository = repository
        self._expiry_cache = ExpiryCache()

    def _enabled_inventory_ids(self) -> set[str]:
        return {entry.entry_id for entry in enabled_inventory_entries(self.hass)}

    def invalidate(self, inventory_id: str | None) -> None:
        """Drop the cached expiry entries of *inventory_id* and of all inventories."""
        if inventory_id is not None:
            self._expiry_cache.invalidate(inventory_id)
        self._expiry_cache.invalidate(None)

    async def _items_by_inventory(
        self, inventory_id: str | None
    ) -> dict[str, list[dict[str, Any]]]:
        """Detailed items of one inventory, or of every enabled inventory."""
        if inventory_id:
            return {inventory_id: await self.repository.list_items_with_details(inventory_id)}
        enabled = self._enabled_inventory_ids()
        return {
            inventory["id"]: await self.repository.list_items_with_details(inventory["id"])
            for inventory in await self.repository.list_inventories()
            if inventory["id"] in enabled
        }

    async def async_items_expiring_soon(
        self, inventory_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Return one entry per batch expiring within its item's threshold.

        Results are cached briefly (see ExpiryCache) so the sensors refreshing in one
        update cycle hit the database once per inventory.
        """
        cached = self._expiry_cache.get(inventory_id)
        if cached is not None:
            return cached

        inventories = await self._items_by_inventory(inventory_id)

        now = dt_util.now().date()
        _LOGGER.debug("async_items_expiring_soon(%s): today (local) = %s", inventory_id, now)
        expiring: list[dict[str, Any]] = []
        for inv_id, items in inventories.items():
            expiring.extend(expiry_entries(items, inv_id, now))

        expiring.sort(key=lambda entry: entry["days_until_expiry"])
        if _LOGGER.isEnabledFor(logging.DEBUG):
            expired, expiring_soon = partition_expiry(expiring)
            _LOGGER.debug(
                "async_items_expiring_soon(%s): returning %d batch entries "
                "(expired=%d, expiring_soon=%d)",
                inventory_id,
                len(expiring),
                len(expired),
                len(expiring_soon),
            )
        self._expiry_cache.put(inventory_id, expiring)
        return expiring

    async def async_low_stock_items(self, inventory_id: str | None = None) -> list[dict[str, Any]]:
        """Return items across one or all inventories at/below their auto-add threshold."""
        inventories = await self._items_by_inventory(inventory_id)

        low_stock: list[dict[str, Any]] = []
        for inv_id, items in inventories.items():
            for item in items:
                if is_below_threshold(item):
                    low_stock.append({**item, "inventory_id": inv_id})
        return low_stock

    async def async_overview(self, inventories: Mapping[str, str]) -> dict[str, Any]:
        """Summaries of *inventories* (id → display name) and what needs attention in them.

        Each item is listed once, in its most urgent section: expired, expiring soon (both
        from the per-batch expiry entries), out of stock, low stock. Entries are the
        ``list_items`` dicts plus ``inventory_id``, ``inventory_name`` and ``reason``.
        """
        icons = {row["id"]: row["icon"] for row in await self.repository.list_inventories()}
        today = dt_util.now().date()

        rows: dict[str, list[tuple[tuple[Any, ...], dict[str, Any]]]] = {
            section: [] for section in ATTENTION_SECTIONS
        }
        summaries: list[dict[str, Any]] = []
        for inventory_id, name in inventories.items():
            items = await self.repository.list_items_with_details(inventory_id)
            attention = dict.fromkeys(ATTENTION_SECTIONS, 0)
            expiry_by_item: dict[str, list[dict[str, Any]]] = {}
            for expiry in expiry_entries(items, inventory_id, today):
                expiry_by_item.setdefault(expiry["id"], []).append(expiry)
            for item in items:
                placed = _attention(item, expiry_by_item.get(item["id"], []))
                if placed is None:
                    continue
                section, reason, sort_key = placed
                attention[section] += 1
                key = (*sort_key, str(item[FIELD_NAME]).casefold(), name.casefold(), inventory_id)
                entry = {
                    **item,
                    "inventory_id": inventory_id,
                    "inventory_name": name,
                    "reason": reason,
                }
                rows[section].append((key, entry))
            summaries.append(
                {
                    "id": inventory_id,
                    "name": name,
                    "icon": icons.get(inventory_id) or "",
                    "total_items": len(items),
                    "total_value": total_value(items),
                    "attention": attention,
                }
            )

        summaries.sort(key=lambda summary: (summary["name"].casefold(), summary["id"]))
        result: dict[str, Any] = {"inventories": summaries}
        for section, section_rows in rows.items():
            section_rows.sort(key=lambda row: row[0])
            result[section] = [entry for _key, entry in section_rows]
        return result

    async def async_search(
        self, query: str, inventories: Mapping[str, str], limit: int
    ) -> dict[str, Any]:
        """Items of *inventories* (id → display name) matching *query*, best match first.

        Each item is its ``list_items`` dict plus ``inventory_id``, ``inventory_name`` and
        ``matched``; ``truncated`` tells whether more than *limit* items matched.
        """
        if not query or not inventories:
            return {FIELD_ITEMS: [], "truncated": False}
        rows = await self.repository.search_items(query, inventories.keys(), limit)
        truncated = len(rows) > limit
        rows = rows[:limit]
        by_inventory: dict[str, set[str]] = {}
        for inventory_id, item_id, _rank in rows:
            by_inventory.setdefault(inventory_id, set()).add(item_id)
        details: dict[str, dict[str, Any]] = {}
        for inventory_id, item_ids in by_inventory.items():
            for item in await self.repository.list_items_with_details(inventory_id, item_ids):
                details[item["id"]] = item
        items = [
            {
                **details[item_id],
                "inventory_id": inventory_id,
                "inventory_name": inventories[inventory_id],
                "matched": _MATCH_REASONS[rank],
            }
            for inventory_id, item_id, rank in rows
            if item_id in details
        ]
        return {FIELD_ITEMS: items, "truncated": truncated}

    async def async_lookup_by_barcode(self, barcode: str) -> list[dict[str, Any]]:
        """Every item with *barcode* in an enabled inventory (with ``inventory_name``)."""
        enabled = self._enabled_inventory_ids()
        return [
            item
            for item in await self.repository.get_item_by_barcode_global(barcode)
            if item["inventory_id"] in enabled
        ]

    async def async_barcode_item(self, barcode: str) -> dict[str, Any]:
        """The one item with *barcode* across inventories.

        Raises ``barcode_not_found`` when none has it and ``ambiguous_barcode`` when items
        of several inventories do.
        """
        matches = await self.async_lookup_by_barcode(barcode)
        if not matches:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="barcode_not_found",
                translation_placeholders={"barcode": barcode},
            )
        if len(matches) > 1:
            inv_names = [m.get("inventory_name", m["inventory_id"]) for m in matches]
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="ambiguous_barcode",
                translation_placeholders={
                    "barcode": barcode,
                    "inventories": ", ".join(inv_names),
                },
            )
        return matches[0]

    async def async_items_by_inventory(self) -> list[dict[str, Any]]:
        """Every enabled inventory (``get_items_from_all_inventories``).

        One ``{inventory_id, inventory_name, description, items}`` per inventory, items
        and inventories sorted by name (case-insensitive).
        """
        enabled = self._enabled_inventory_ids()
        result: list[dict[str, Any]] = []
        for inventory in await self.repository.list_inventories():
            inventory_id = str(inventory["id"])
            if inventory_id not in enabled:
                continue
            items = await self.repository.list_items_with_details(inventory_id)
            items.sort(key=lambda item: str(item.get(FIELD_NAME, "")).lower())
            result.append(
                {
                    "inventory_id": inventory_id,
                    "inventory_name": inventory.get("name", inventory_id),
                    "description": inventory.get("description", ""),
                    FIELD_ITEMS: items,
                }
            )
        result.sort(key=lambda inventory: str(inventory.get("inventory_name", "")).lower())
        return result
