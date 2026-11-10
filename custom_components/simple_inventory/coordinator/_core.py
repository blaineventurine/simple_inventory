"""Core coordinator for Simple Inventory integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiosqlite
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from ..const import (
    DEFAULT_AUTO_ADD_ENABLED,
    DEFAULT_AUTO_ADD_TO_LIST_QUANTITY,
    DEFAULT_CATEGORY,
    DEFAULT_DESIRED_QUANTITY,
    DEFAULT_EXPIRY_ALERT_DAYS,
    DEFAULT_EXPIRY_DATE,
    DEFAULT_ITEM_ICON,
    DEFAULT_LOCATION,
    DEFAULT_PRICE,
    DEFAULT_QUANTITY,
    DEFAULT_TODO_LIST,
    DEFAULT_TODO_QUANTITY_PLACEMENT,
    DEFAULT_UNIT,
    DOMAIN,
    EVENT_ITEM_ADDED,
    EVENT_ITEM_DEPLETED,
    EVENT_ITEM_QUANTITY_CHANGED,
    EVENT_ITEM_REMOVED,
    EVENT_ITEM_RESTOCKED,
    EVENT_ITEM_TRANSFERRED,
    EVENT_UPDATED,
    FIELD_ALIASES,
    FIELD_AMOUNT,
    FIELD_AUTO_ADD_ENABLED,
    FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED,
    FIELD_AUTO_ADD_TO_LIST_QUANTITY,
    FIELD_BARCODE,
    FIELD_CATEGORY,
    FIELD_DESCRIPTION,
    FIELD_DESIRED_QUANTITY,
    FIELD_EXPIRY_ALERT_DAYS,
    FIELD_EXPIRY_DATE,
    FIELD_FROM_LOCATION,
    FIELD_ICON,
    FIELD_IMAGE,
    FIELD_LOCATION,
    FIELD_NAME,
    FIELD_PRICE,
    FIELD_PURCHASED_AT,
    FIELD_QUANTITY,
    FIELD_TO_LOCATION,
    FIELD_TODO_LIST,
    FIELD_TODO_QUANTITY_PLACEMENT,
    FIELD_UNIT,
    FIELD_UNIT_PRICE,
    match_key,
    round_quantity,
    split_unique,
    updated_event,
)
from ..entries import inventory_display_name
from ..hub import InventoryHub
from ..item_fields import UPDATABLE_ITEM_FIELDS, item_field_names
from ..storage._batches import InsufficientStockError, StockChange
from ..storage.images import ImageStore
from ..storage.repository import InventoryRepository
from ._analytics import _AnalyticsMixin
from ._identifiers import ItemIdentifiers
from ._images import _ImagesMixin
from ._import_export import _ImportExportMixin
from ._statistics import _StatisticsMixin

_LOGGER = logging.getLogger(__name__)


def scan_lookup_result(item: dict[str, Any], inventory_id: str) -> dict[str, Any]:
    """The result of a ``lookup`` scan: the item found by its barcode, nothing changed."""
    return {"action": "lookup", "item": item, "inventory_id": inventory_id}


class SimpleInventoryCoordinator(
    _StatisticsMixin, _ImportExportMixin, _AnalyticsMixin, _ImagesMixin
):
    """Facade around the SQLite repository with HA signaling."""

    _INTEGER_FIELDS = frozenset(item_field_names("int", updatable_only=True))
    _NUMERIC_FIELDS = frozenset(item_field_names("float", updatable_only=True))
    _BOOLEAN_FIELDS = frozenset(item_field_names("bool", updatable_only=True))
    _STRING_FIELDS = frozenset(item_field_names("str", "date", updatable_only=True))

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        repository: InventoryRepository,
        hub: InventoryHub,
    ) -> None:
        """Initialize the coordinator; *hub* is the integration's shared InventoryHub."""
        self.hass = hass
        self.entry = entry
        self.repository = repository
        self.hub = hub
        self.images = ImageStore(hass)
        self._init_lock = asyncio.Lock()
        self._initialized = False

    async def async_initialize(self) -> None:
        """Perform per-entry init (repository already opened)."""
        async with self._init_lock:
            if self._initialized:
                return
            _LOGGER.debug("Coordinator ready for %s", self.entry.entry_id)
            self._initialized = True

    async def async_upsert_inventory_metadata(
        self,
        inventory_id: str,
        name: str,
        description: str = "",
        icon: str = "",
        entry_type: str = "",
        metadata: str | None = None,
    ) -> None:
        """Ensure an inventory row exists (called from config entry setup)."""
        await self.async_initialize()
        await self.repository.upsert_inventory(
            inventory_id, name, description, icon, entry_type, metadata
        )
        await self._fire_update_events(inventory_id)

    async def async_add_item(self, inventory_id: str, **kwargs: Any) -> str | None:
        """Add a new item to an inventory.

        Raises ServiceValidationError if the name is empty or already used in the
        inventory (case-insensitive), or if a barcode/alias/location/category conflicts.
        Nothing is kept (no row, history or event) when it raises.
        """
        await self.async_initialize()

        name = kwargs.get(FIELD_NAME)
        cleaned_name = self._validate_and_clean_name(str(name) if name else "", inventory_id)
        quantity = round_quantity(max(0, float(kwargs.get(FIELD_QUANTITY, DEFAULT_QUANTITY))))

        auto_add_quantity = round_quantity(
            max(
                0,
                float(
                    kwargs.get(FIELD_AUTO_ADD_TO_LIST_QUANTITY, DEFAULT_AUTO_ADD_TO_LIST_QUANTITY)
                ),
            )
        )
        auto_add_enabled = bool(kwargs.get(FIELD_AUTO_ADD_ENABLED, DEFAULT_AUTO_ADD_ENABLED))
        auto_add_id_enabled = bool(kwargs.get(FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED, False))
        todo_list = kwargs.get(FIELD_TODO_LIST, DEFAULT_TODO_LIST)

        if not self._validate_auto_add_config(
            cleaned_name, inventory_id, auto_add_enabled, auto_add_quantity, todo_list
        ):
            return None

        existing = await self.repository.get_item_by_name(inventory_id, cleaned_name)
        if existing:
            raise self._duplicate_name_error(str(existing[FIELD_NAME]), inventory_id)
        await self._raise_on_name_alias_clashes(
            inventory_id, "", cleaned_name, kwargs.get(FIELD_ALIASES, "")
        )

        description = self._process_description_update(
            kwargs.get(FIELD_DESCRIPTION, ""),
            inventory_id,
            auto_add_id_enabled,
        )

        item_payload = {
            FIELD_NAME: cleaned_name,
            FIELD_DESCRIPTION: description,
            FIELD_UNIT: kwargs.get(FIELD_UNIT, DEFAULT_UNIT),
            FIELD_EXPIRY_ALERT_DAYS: max(
                0,
                int(kwargs.get(FIELD_EXPIRY_ALERT_DAYS, DEFAULT_EXPIRY_ALERT_DAYS)),
            ),
            FIELD_AUTO_ADD_ENABLED: auto_add_enabled,
            FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED: auto_add_id_enabled,
            FIELD_AUTO_ADD_TO_LIST_QUANTITY: auto_add_quantity,
            FIELD_DESIRED_QUANTITY: round_quantity(
                max(0, float(kwargs.get(FIELD_DESIRED_QUANTITY, DEFAULT_DESIRED_QUANTITY)))
            ),
            FIELD_TODO_LIST: todo_list,
            FIELD_TODO_QUANTITY_PLACEMENT: kwargs.get(
                FIELD_TODO_QUANTITY_PLACEMENT, DEFAULT_TODO_QUANTITY_PLACEMENT
            ),
            FIELD_PRICE: max(
                0,
                float(kwargs.get(FIELD_PRICE, DEFAULT_PRICE)),
            ),
            FIELD_ICON: kwargs.get(FIELD_ICON, DEFAULT_ITEM_ICON),
        }

        try:
            item_id = await self.repository.create_item(inventory_id, item_payload)
        except aiosqlite.IntegrityError as exc:
            # Lost a race with a concurrent add of the same name.
            raise self._duplicate_name_error(cleaned_name, inventory_id) from exc

        try:
            await self._apply_barcode_updates(inventory_id, item_id, kwargs.get(FIELD_BARCODE, ""))
            await self._apply_alias_updates(inventory_id, item_id, kwargs.get(FIELD_ALIASES, ""))
            await self._apply_location_updates(
                inventory_id,
                item_id,
                kwargs.get(FIELD_LOCATION, DEFAULT_LOCATION),
            )
            await self._apply_category_updates(
                item_id, kwargs.get(FIELD_CATEGORY, DEFAULT_CATEGORY)
            )
            change = (
                await self.repository.add_stock(
                    item_id,
                    inventory_id,
                    quantity,
                    expiry_date=kwargs.get(FIELD_EXPIRY_DATE, DEFAULT_EXPIRY_DATE) or "",
                    location_id=await self.repository.first_item_location_id(item_id),
                    unit_price=float(item_payload[FIELD_PRICE]),
                    purchased_at=dt_util.now().date().isoformat(),
                )
                if quantity > 0
                else None
            )
        except Exception:
            # Never leave a half-created item behind (e.g. barcode already taken).
            await self.repository.delete_item(item_id)
            raise

        item_price = float(item_payload.get(FIELD_PRICE, 0))
        await self.repository.record_history_event(
            item_id=item_id,
            inventory_id=inventory_id,
            event_type="add",
            amount=quantity,
            quantity_before=0,
            quantity_after=quantity,
            price=item_price,
            batch_id=change.batches[0].batch_id if change else "",
        )

        await self._after_change(inventory_id)
        self.hass.bus.async_fire(
            EVENT_ITEM_ADDED,
            {
                "item_name": cleaned_name,
                "inventory_id": inventory_id,
                FIELD_QUANTITY: quantity,
            },
        )
        return item_id

    async def async_update_item(
        self,
        inventory_id: str,
        old_name: str,
        new_name: str,
        *,
        barcode: str | None = None,
        aliases: str | None = None,
        **kwargs: Any,
    ) -> bool:
        """Update an existing item.

        Raises ServiceValidationError when renaming onto another item's name or when a
        barcode/alias/location/category conflicts, with ``no_stock_for_expiry`` when an
        expiry edit targets an item without batches, and with ``batch_required`` when an
        expiry/price edit cannot be applied to exactly one batch (D6). Quantity changes
        add or consume stock and are recorded as ``update`` history events.
        """
        await self.async_initialize()

        resolved_old_name = await self._resolve_item_name(inventory_id, old_name, barcode)
        item = await self.repository.get_item_by_name(inventory_id, resolved_old_name)
        if not item:
            _LOGGER.warning(
                "Cannot update non-existent item '%s' in inventory '%s'",
                resolved_old_name,
                inventory_id,
            )
            return False

        payload = self._prepare_update_payload(inventory_id, item, new_name, kwargs)
        requested_quantity = payload.pop(FIELD_QUANTITY, None)
        requested_expiry = payload.pop(FIELD_EXPIRY_DATE, None)
        batches = await self.repository.list_batches(item["id"])
        current_quantity = round_quantity(float(item.get(FIELD_QUANTITY) or 0))
        if requested_quantity is not None:
            requested_quantity = round_quantity(float(requested_quantity))
        adds_stock = requested_quantity is not None and requested_quantity > current_quantity
        expiry_change = (
            requested_expiry is not None
            and requested_expiry != (item.get(FIELD_EXPIRY_DATE) or "")
            and not adds_stock
        )
        price_change = (
            FIELD_PRICE in payload
            and float(payload[FIELD_PRICE]) != round_quantity(float(item.get(FIELD_PRICE) or 0))
            and not adds_stock
        )
        for field, changing in ((FIELD_EXPIRY_DATE, expiry_change), (FIELD_PRICE, price_change)):
            if changing and field == FIELD_EXPIRY_DATE and not batches:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="no_stock_for_expiry",
                    translation_placeholders={"name": str(item[FIELD_NAME])},
                )
            if changing and len(batches) > 1:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="batch_required",
                    translation_placeholders={
                        "name": str(item[FIELD_NAME]),
                        "count": str(len(batches)),
                        "field": field,
                    },
                )

        auto_add_enabled = payload.get(
            FIELD_AUTO_ADD_ENABLED, item.get(FIELD_AUTO_ADD_ENABLED, False)
        )
        auto_add_quantity = payload.get(
            FIELD_AUTO_ADD_TO_LIST_QUANTITY,
            item.get(FIELD_AUTO_ADD_TO_LIST_QUANTITY, DEFAULT_AUTO_ADD_TO_LIST_QUANTITY),
        )
        todo_list = payload.get(FIELD_TODO_LIST, item.get(FIELD_TODO_LIST, DEFAULT_TODO_LIST))

        if not self._validate_auto_add_config(
            payload[FIELD_NAME],
            inventory_id,
            auto_add_enabled,
            auto_add_quantity,
            todo_list,
        ):
            return False

        target = await self.repository.get_item_by_name(inventory_id, payload[FIELD_NAME])
        if target and target["id"] != item["id"]:
            raise self._duplicate_name_error(str(target[FIELD_NAME]), inventory_id)

        await self._raise_on_relation_conflicts(inventory_id, item["id"], barcode, aliases)
        renamed = match_key(payload[FIELD_NAME]) != match_key(str(item[FIELD_NAME]))
        await self._raise_on_name_alias_clashes(
            inventory_id, item["id"], payload[FIELD_NAME] if renamed else None, aliases
        )

        try:
            updated = await self.repository.update_item(item["id"], payload)
        except aiosqlite.IntegrityError as exc:
            raise self._duplicate_name_error(payload[FIELD_NAME], inventory_id) from exc
        if not updated:
            return False

        if FIELD_LOCATION in kwargs:
            await self._apply_location_updates(
                inventory_id,
                item["id"],
                kwargs.get(FIELD_LOCATION, DEFAULT_LOCATION),
            )

        if FIELD_CATEGORY in kwargs:
            await self._apply_category_updates(
                item["id"], kwargs.get(FIELD_CATEGORY, DEFAULT_CATEGORY)
            )

        if barcode is not None:
            await self._apply_barcode_updates(inventory_id, item["id"], barcode)

        if aliases is not None:
            await self._apply_alias_updates(inventory_id, item["id"], aliases)

        explicit_price = float(payload[FIELD_PRICE]) if FIELD_PRICE in payload else None
        item_price = float(payload.get(FIELD_PRICE, item.get(FIELD_PRICE)) or 0)
        change: StockChange | None = None
        if requested_quantity is not None and adds_stock:
            change = await self.repository.add_stock(
                item["id"],
                inventory_id,
                round_quantity(requested_quantity - current_quantity),
                expiry_date=requested_expiry or "",
                location_id=await self.repository.first_item_location_id(item["id"]),
                unit_price=item_price,
                purchased_at=dt_util.now().date().isoformat(),
            )
        elif requested_quantity is not None and requested_quantity < current_quantity:
            change = await self.repository.consume_stock(
                item["id"], round_quantity(current_quantity - requested_quantity)
            )
        if len(batches) == 1 and (expiry_change or price_change):
            fields: dict[str, Any] = {}
            if expiry_change:
                fields[FIELD_EXPIRY_DATE] = requested_expiry
            if price_change:
                fields[FIELD_UNIT_PRICE] = item_price
            await self.repository.update_batch(batches[0]["id"], fields)
        if change is not None:
            await self._record_stock_change(
                inventory_id,
                item["id"],
                payload[FIELD_NAME],
                change,
                event_type="update",
                explicit_price=explicit_price,
                item_price=item_price,
            )

        await self._after_change(inventory_id)
        return True

    async def async_remove_item(
        self, inventory_id: str, name: str | None = None, *, barcode: str | None = None
    ) -> bool:
        """Remove an item."""
        await self.async_initialize()

        resolved_name = await self._resolve_item_name(inventory_id, name, barcode)
        cleaned_name = self._validate_and_clean_name(resolved_name, inventory_id)
        item = await self.repository.get_item_by_name(inventory_id, cleaned_name)
        if not item:
            _LOGGER.warning(
                "Cannot remove non-existent item '%s' from inventory '%s'",
                cleaned_name,
                inventory_id,
            )
            return False

        removed = await self.repository.delete_item(item["id"])
        if removed:
            if item.get(FIELD_IMAGE):
                await self.images.async_delete(item["id"])
            await self._after_change(inventory_id)
            self.hass.bus.async_fire(
                EVENT_ITEM_REMOVED,
                {
                    "item_name": item[FIELD_NAME],
                    "inventory_id": inventory_id,
                },
            )
        return removed

    async def async_update_batch(
        self,
        inventory_id: str,
        batch_id: str,
        *,
        quantity: float | None = None,
        expiry_date: str | None = None,
        location: str | None = None,
        unit_price: float | None = None,
        purchased_at: str | None = None,
    ) -> str:
        """Edit one batch; returns the item's name. Quantity 0 removes the batch (D7).

        A positive ``unit_price`` also becomes the item's price (the most recent price
        information), so later plain restocks merge with the repriced batch.
        """
        await self.async_initialize()
        batch = await self._inventory_batch(inventory_id, batch_id)
        fields: dict[str, Any] = {}
        if quantity is not None:
            fields[FIELD_QUANTITY] = round_quantity(max(0.0, float(quantity)))
        if expiry_date is not None:
            fields[FIELD_EXPIRY_DATE] = expiry_date
        if location is not None:
            fields["location_id"] = (
                await self.repository.ensure_location(inventory_id, location.strip())
                if location.strip()
                else None
            )
        if unit_price is not None:
            fields[FIELD_UNIT_PRICE] = max(0.0, float(unit_price))
            if fields[FIELD_UNIT_PRICE] > 0:
                await self.repository.update_item(
                    batch["item_id"], {FIELD_PRICE: fields[FIELD_UNIT_PRICE]}
                )
        if purchased_at and purchased_at.strip():
            fields[FIELD_PURCHASED_AT] = purchased_at.strip()
        return await self._apply_batch_change(inventory_id, batch, fields)

    async def async_remove_batch(self, inventory_id: str, batch_id: str) -> str:
        """Delete one batch; returns the item's name."""
        await self.async_initialize()
        batch = await self._inventory_batch(inventory_id, batch_id)
        return await self._apply_batch_change(inventory_id, batch, {FIELD_QUANTITY: 0})

    async def async_transfer_item(
        self,
        inventory_id: str,
        name: str | None = None,
        *,
        barcode: str | None = None,
        to_location: str,
        amount: float | None = None,
        from_location: str | None = None,
        batch_id: str | None = None,
    ) -> dict[str, Any]:
        """Move stock to another location of this inventory (spec 2026-10-25, T1-T8).

        Source: ``batch_id`` (wins), else ``from_location``, else the soonest-expiring
        stock not already at the destination. ``amount`` None moves everything at the
        source. Every error is raised before anything is written. Returns the
        ``simple_inventory_item_transferred`` event payload.
        """
        await self.async_initialize()
        destination = to_location.strip()
        if not destination:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="location_required"
            )
        requested = None if amount is None else round_quantity(amount)
        if requested is not None and requested <= 0:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_amount",
                translation_placeholders={"amount": f"{amount:g}"},
            )
        resolved_name = await self._resolve_item_name(inventory_id, name, barcode)
        item = await self.repository.get_item_by_name(inventory_id, resolved_name)
        if item is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="item_not_found",
                translation_placeholders={
                    "name": resolved_name,
                    "inventory": inventory_display_name(self.hass, inventory_id),
                },
            )
        item_id = str(item["id"])
        item_name = str(item[FIELD_NAME])
        to_location_id = await self.repository.find_location_id(inventory_id, destination)
        from_location_id, sources = await self._transfer_sources(
            inventory_id, item_id, item_name, destination, to_location_id, from_location, batch_id
        )

        origins = dict.fromkeys(batch[FIELD_LOCATION] for batch in sources if batch[FIELD_LOCATION])
        source_label = ", ".join(origins) or inventory_display_name(self.hass, inventory_id)
        available = round_quantity(sum(batch[FIELD_QUANTITY] for batch in sources))
        if available == 0 or (requested is not None and requested > available):
            raise self._insufficient_stock_error(item_name, source_label, available)

        if to_location_id is None:
            to_location_id = await self.repository.ensure_location(inventory_id, destination)
        try:
            change = await self.repository.transfer_stock(
                item_id,
                inventory_id,
                requested,
                to_location_id=to_location_id,
                from_location_id=from_location_id,
                batch_id=batch_id,
            )
        except InsufficientStockError as err:
            # Stock changed between the check above and the transaction; nothing moved.
            raise self._insufficient_stock_error(item_name, source_label, err.available) from err
        except ValueError as err:
            # Every source vanished before the transaction; nothing moved.
            raise self._insufficient_stock_error(item_name, source_label, 0) from err

        for move in change.moves:
            await self.repository.record_history_event(
                item_id=item_id,
                inventory_id=inventory_id,
                event_type="transfer",
                amount=move.moved,
                quantity_before=change.item_total,
                quantity_after=change.item_total,
                location_from=move.location_from,
                location_to=change.location_to,
                price=move.unit_price,
                batch_id=move.batch_id,
            )
        moved_from = {move.location_from for move in change.moves}
        payload: dict[str, Any] = {
            "item_name": item_name,
            "inventory_id": inventory_id,
            FIELD_AMOUNT: round_quantity(sum(move.moved for move in change.moves)),
            FIELD_FROM_LOCATION: moved_from.pop() if len(moved_from) == 1 else "",
            FIELD_TO_LOCATION: change.location_to,
        }
        await self._after_change(inventory_id)
        self.hass.bus.async_fire(EVENT_ITEM_TRANSFERRED, payload)
        return payload

    async def _inventory_batch(self, inventory_id: str, batch_id: str) -> dict[str, Any]:
        batch = await self.repository.get_batch(batch_id)
        if batch is None or batch["inventory_id"] != inventory_id:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="batch_not_found",
                translation_placeholders={"batch_id": batch_id},
            )
        return batch

    async def _apply_batch_change(
        self, inventory_id: str, batch: dict[str, Any], fields: dict[str, Any]
    ) -> str:
        item = await self.repository.get_item_by_id(batch["item_id"])
        assert item is not None  # batch rows cascade with their item
        change = await self.repository.update_batch(batch["id"], fields)
        if change is not None:
            await self._record_stock_change(
                inventory_id,
                item["id"],
                str(item[FIELD_NAME]),
                change,
                event_type="update",
                explicit_price=None,
                item_price=float(item.get(FIELD_PRICE) or 0),
            )
        await self._after_change(inventory_id)
        return str(item[FIELD_NAME])

    async def async_increment_item(
        self,
        inventory_id: str,
        name: str | None = None,
        amount: float = 1,
        *,
        barcode: str | None = None,
        price: float | None = None,
        expiry_date: str | None = None,
        location: str | None = None,
        purchased_at: str | None = None,
    ) -> bool:
        """Increment quantity, topping up a matching batch or creating one (D4)."""
        if amount < 0:
            _LOGGER.warning(
                "Cannot increment item with negative amount: %d in inventory '%s'",
                amount,
                inventory_id,
            )
            return False

        resolved_name = await self._resolve_item_name(inventory_id, name, barcode)
        return await self._adjust_quantity(
            inventory_id,
            resolved_name,
            amount,
            price=price,
            expiry_date=expiry_date,
            location=location,
            purchased_at=purchased_at,
        )

    async def async_decrement_item(
        self,
        inventory_id: str,
        name: str | None = None,
        amount: float = 1,
        *,
        barcode: str | None = None,
        price: float | None = None,
        location: str | None = None,
        batch_id: str | None = None,
    ) -> bool:
        """Decrement quantity, consuming batches in D3 order.

        ``batch_id`` consumes only that batch and takes precedence: ``location`` is then
        ignored. Otherwise ``location`` limits consumption to that location's batches.
        """
        if amount < 0:
            _LOGGER.warning(
                "Cannot decrement item with negative amount: %d in inventory '%s'",
                amount,
                inventory_id,
            )
            return False

        resolved_name = await self._resolve_item_name(inventory_id, name, barcode)
        return await self._adjust_quantity(
            inventory_id,
            resolved_name,
            -amount,
            price=price,
            location=location,
            batch_id=batch_id,
        )

    async def async_get_item(self, inventory_id: str, name: str) -> dict[str, Any] | None:
        """Return detailed item data (incl. batches) by case-insensitive name."""
        await self.async_initialize()
        wanted = match_key(name)
        for item in await self.repository.list_items_with_details(inventory_id):
            if match_key(str(item[FIELD_NAME])) == wanted:
                return item
        return None

    async def async_get_item_by_barcode(
        self, inventory_id: str, barcode: str
    ) -> dict[str, Any] | None:
        """The item of *inventory_id* with exactly *barcode*, if any."""
        await self.async_initialize()
        return await self.repository.get_item_by_barcode(inventory_id, barcode)

    async def async_scan_barcode(
        self,
        barcode: str,
        action: str,
        amount: float,
        inventory_id: str,
        price: float | None = None,
        *,
        expiry_date: str | None = None,
        location: str | None = None,
        purchased_at: str | None = None,
        batch_id: str | None = None,
    ) -> dict[str, Any]:
        """Scan a barcode in *inventory_id* and perform an action (increment/decrement/lookup).

        A scan without an inventory is resolved across inventories by
        ``InventoryHub.async_barcode_item`` first, then handed to ``async_scan_item``.
        """
        item = await self.async_get_item_by_barcode(inventory_id, barcode)
        if item is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="barcode_not_found",
                translation_placeholders={"barcode": barcode},
            )
        return await self.async_scan_item(
            item,
            inventory_id,
            action,
            amount,
            price,
            expiry_date=expiry_date,
            location=location,
            purchased_at=purchased_at,
            batch_id=batch_id,
        )

    async def async_scan_item(
        self,
        item: dict[str, Any],
        resolved_inventory_id: str,
        action: str,
        amount: float = 1.0,
        price: float | None = None,
        *,
        expiry_date: str | None = None,
        location: str | None = None,
        purchased_at: str | None = None,
        batch_id: str | None = None,
    ) -> dict[str, Any]:
        """Perform a scan action on *item*, already found by its barcode."""
        await self.async_initialize()
        item_name = str(item[FIELD_NAME])

        if action == "lookup":
            return scan_lookup_result(item, resolved_inventory_id)

        if action == "increment":
            result = await self.async_increment_item(
                resolved_inventory_id,
                name=item_name,
                amount=amount,
                price=price,
                expiry_date=expiry_date,
                location=location,
                purchased_at=purchased_at,
            )
            return {
                "action": "increment",
                "success": result,
                "item_name": item_name,
                "inventory_id": resolved_inventory_id,
                FIELD_AMOUNT: amount,
            }

        if action == "decrement":
            result = await self.async_decrement_item(
                resolved_inventory_id,
                name=item_name,
                amount=amount,
                price=price,
                location=location,
                batch_id=batch_id,
            )
            return {
                "action": "decrement",
                "success": result,
                "item_name": item_name,
                "inventory_id": resolved_inventory_id,
                FIELD_AMOUNT: amount,
            }

        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_scan_action",
            translation_placeholders={"action": action},
        )

    async def async_list_items(self, inventory_id: str) -> list[dict[str, Any]]:
        """Return detailed items for an inventory."""
        await self.async_initialize()
        return await self.repository.list_items_with_details(inventory_id)

    async def async_list_location_names(self, inventory_id: str) -> list[str]:
        """Return the stored names of an inventory's locations."""
        await self.async_initialize()
        return await self.repository.list_location_names(inventory_id)

    async def async_get_item_history(
        self,
        inventory_id: str,
        name: str,
        *,
        event_type: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return history events for a specific item."""
        await self.async_initialize()
        item = await self.repository.get_item_by_name(inventory_id, name)
        if not item:
            return []
        return await self.repository.get_item_history(
            item["id"],
            event_type=event_type,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset,
        )

    async def async_get_inventory_history(
        self,
        inventory_id: str,
        *,
        event_type: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return history events for an inventory."""
        await self.async_initialize()
        return await self.repository.get_inventory_history(
            inventory_id,
            event_type=event_type,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset,
        )

    async def async_unload(self) -> None:
        """Unload per-entry resources.

        Repository is shared and is closed by __init__.py when the last entry unloads.
        """
        async with self._init_lock:
            self._initialized = False

    # Internal helpers -----------------------------------------------------

    async def _resolve_item_name(
        self,
        inventory_id: str,
        name: str | None,
        barcode: str | None,
    ) -> str:
        """Resolve an item name from name or barcode.

        Returns the item name. Raises ValueError if neither is provided
        or the barcode does not match any item.
        """
        if name and name.strip():
            return name.strip()

        if barcode and barcode.strip():
            item = await self.repository.get_item_by_barcode(inventory_id, barcode.strip())
            if item is None:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="barcode_not_found",
                    translation_placeholders={"barcode": barcode.strip()},
                )
            return str(item[FIELD_NAME])

        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="item_identifier_required",
            translation_placeholders={"inventory": inventory_display_name(self.hass, inventory_id)},
        )

    async def _adjust_quantity(
        self,
        inventory_id: str,
        name: str,
        delta: float,
        price: float | None = None,
        *,
        expiry_date: str | None = None,
        location: str | None = None,
        purchased_at: str | None = None,
        batch_id: str | None = None,
    ) -> bool:
        await self.async_initialize()

        cleaned_name = self._validate_and_clean_name(name, inventory_id)
        item = await self.repository.get_item_by_name(inventory_id, cleaned_name)
        if not item:
            _LOGGER.warning(
                "Cannot adjust quantity for non-existent item '%s' in inventory '%s'",
                cleaned_name,
                inventory_id,
            )
            return False

        if round_quantity(delta) == 0:
            return True

        item_id = str(item["id"])
        item_name = str(item[FIELD_NAME])
        # Resolve and validate the target before any write.
        if delta > 0:
            location_id = await self._batch_location_id(inventory_id, item_id, location)
        else:
            batch_id = await self._own_batch_id(item_id, batch_id)
            location_id = (
                None
                if batch_id is not None
                else await self._stocked_location_id(inventory_id, item_id, item_name, location)
            )

        # A positive price updates the item's stored price and is recorded on history.
        explicit_price = float(price) if price is not None and price > 0 else None
        item_price = float(item.get(FIELD_PRICE) or 0)
        if explicit_price is not None:
            await self.repository.update_item(item_id, {FIELD_PRICE: explicit_price})
            item_price = explicit_price

        if delta > 0:
            change = await self.repository.add_stock(
                item_id,
                inventory_id,
                delta,
                expiry_date=expiry_date or "",
                location_id=location_id,
                unit_price=item_price,
                purchased_at=purchased_at or dt_util.now().date().isoformat(),
            )
            event_type = "increment"
        else:
            change = await self.repository.consume_stock(
                item_id, -delta, location_id=location_id, batch_id=batch_id
            )
            event_type = "decrement"

        changed = await self._record_stock_change(
            inventory_id,
            item_id,
            item_name,
            change,
            event_type=event_type,
            explicit_price=explicit_price,
            item_price=item_price,
        )
        if changed or explicit_price is not None:
            await self._after_change(inventory_id)
        return True

    async def _batch_location_id(
        self, inventory_id: str, item_id: str, location: str | None
    ) -> int | None:
        """Location for new stock: the given one (created if new), else the item's first one."""
        if location and location.strip():
            return await self.repository.ensure_location(inventory_id, location.strip())
        return await self.repository.first_item_location_id(item_id)

    async def _stocked_location_id(
        self, inventory_id: str, item_id: str, item_name: str, location: str | None
    ) -> int | None:
        """Location to consume from; raises unless the item has stock there."""
        if location is None or not location.strip():
            return None
        location_id = await self.repository.find_location_id(inventory_id, location.strip())
        if location_id is None or not await self.repository.has_stock_at_location(
            item_id, location_id
        ):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="no_stock_at_location",
                translation_placeholders={"name": item_name, "location": location.strip()},
            )
        return location_id

    async def _own_batch_id(self, item_id: str, batch_id: str | None) -> str | None:
        if batch_id is None:
            return None
        batch = await self.repository.get_batch(batch_id)
        if batch is None or batch["item_id"] != item_id:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="batch_not_found",
                translation_placeholders={"batch_id": batch_id},
            )
        return batch_id

    async def _transfer_sources(
        self,
        inventory_id: str,
        item_id: str,
        item_name: str,
        destination: str,
        to_location_id: int | None,
        from_location: str | None,
        batch_id: str | None,
    ) -> tuple[int | None, list[dict[str, Any]]]:
        """Validated T2 source batches and the ``from_location`` id (None unless given).

        Raises ``batch_not_found`` / ``no_stock_at_location`` like a decrement, and
        ``same_location`` when the source is the destination.
        """
        from_location_id: int | None = None
        if batch_id is not None:
            await self._own_batch_id(item_id, batch_id)
        else:
            from_location_id = await self._stocked_location_id(
                inventory_id, item_id, item_name, from_location
            )
        sources = await self.repository.list_transfer_sources(
            item_id,
            to_location_id=to_location_id,
            from_location_id=from_location_id,
            batch_id=batch_id,
        )
        if to_location_id is not None:
            if batch_id is not None:
                at_destination = bool(sources) and sources[0]["location_id"] == to_location_id
            elif from_location_id is not None:
                at_destination = from_location_id == to_location_id
            else:
                at_destination = not sources and await self.repository.has_stock_at_location(
                    item_id, to_location_id
                )
            if at_destination:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="same_location",
                    translation_placeholders={"location": destination},
                )
        return from_location_id, sources

    async def _record_stock_change(
        self,
        inventory_id: str,
        item_id: str,
        item_name: str,
        change: StockChange,
        *,
        event_type: str,
        explicit_price: float | None,
        item_price: float,
        source: str = "service",
    ) -> bool:
        """History rows for *change* (see _record_stock_history) plus lifecycle events once."""
        await self._record_stock_history(
            inventory_id,
            item_id,
            change,
            event_type=event_type,
            explicit_price=explicit_price,
            item_price=item_price,
            source=source,
        )
        return self._fire_quantity_events(
            inventory_id, item_name, change.item_before, change.item_after
        )

    async def _record_stock_history(
        self,
        inventory_id: str,
        item_id: str,
        change: StockChange,
        *,
        event_type: str,
        explicit_price: float | None,
        item_price: float,
        source: str = "service",
    ) -> None:
        """One history row per touched batch (running item totals).

        Recorded price: the caller's explicit price, else the batch's unit price, else the
        item's price.
        """
        running = change.item_before
        for batch in change.batches:
            amount = round_quantity(abs(batch.quantity_after - batch.quantity_before))
            if amount == 0:
                continue
            signed = amount if batch.quantity_after > batch.quantity_before else -amount
            after = round_quantity(running + signed)
            await self.repository.record_history_event(
                item_id=item_id,
                inventory_id=inventory_id,
                event_type=event_type,
                amount=amount,
                quantity_before=running,
                quantity_after=after,
                source=source,
                price=explicit_price or batch.unit_price or item_price,
                batch_id=batch.batch_id,
                location_from=batch.location if signed < 0 else "",
                location_to=batch.location if signed > 0 else "",
            )
            running = after

    def _fire_quantity_events(
        self, inventory_id: str, item_name: str, before: float, after: float
    ) -> bool:
        """Fire depleted/restocked/quantity_changed for an applied change; returns whether it changed."""
        quantity_before = round_quantity(before)
        quantity_after = round_quantity(after)
        amount = round_quantity(abs(quantity_after - quantity_before))
        if amount == 0:
            return False

        if quantity_after == 0:
            self.hass.bus.async_fire(
                EVENT_ITEM_DEPLETED,
                {
                    "item_name": item_name,
                    "inventory_id": inventory_id,
                    "previous_quantity": quantity_before,
                },
            )

        if quantity_before == 0:
            self.hass.bus.async_fire(
                EVENT_ITEM_RESTOCKED,
                {
                    "item_name": item_name,
                    "inventory_id": inventory_id,
                    FIELD_QUANTITY: quantity_after,
                },
            )

        self.hass.bus.async_fire(
            EVENT_ITEM_QUANTITY_CHANGED,
            {
                "item_name": item_name,
                "inventory_id": inventory_id,
                "quantity_before": quantity_before,
                "quantity_after": quantity_after,
                FIELD_AMOUNT: amount,
                "direction": "increment" if quantity_after > quantity_before else "decrement",
            },
        )
        return True

    async def _apply_barcode_updates(
        self, inventory_id: str, item_id: str, barcode_str: str
    ) -> None:
        barcodes = split_unique(barcode_str, case_sensitive=True)
        try:
            await self.repository.set_item_barcodes(item_id, inventory_id, barcodes)
        except aiosqlite.IntegrityError as exc:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="barcode_conflict",
                translation_placeholders={"barcodes": ", ".join(barcodes)},
            ) from exc

    async def _apply_alias_updates(self, inventory_id: str, item_id: str, aliases_str: str) -> None:
        aliases = split_unique(aliases_str)
        try:
            await self.repository.set_item_aliases(item_id, inventory_id, aliases)
        except aiosqlite.IntegrityError as exc:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="alias_conflict",
                translation_placeholders={"aliases": ", ".join(aliases)},
            ) from exc

    async def _raise_on_relation_conflicts(
        self, inventory_id: str, item_id: str, barcode_str: str | None, aliases_str: str | None
    ) -> None:
        """Reject barcodes/aliases owned by another item before anything is written.

        Locations and categories need no check: they are deduped and cannot conflict.
        """
        barcodes, aliases = await self.repository.find_relation_conflicts(
            inventory_id,
            item_id,
            split_unique(barcode_str, case_sensitive=True) if barcode_str is not None else [],
            split_unique(aliases_str) if aliases_str is not None else [],
        )
        if barcodes:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="barcode_conflict",
                translation_placeholders={"barcodes": ", ".join(barcodes)},
            )
        if aliases:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="alias_conflict",
                translation_placeholders={"aliases": ", ".join(aliases)},
            )

    async def _raise_on_name_alias_clashes(
        self,
        inventory_id: str,
        item_id: str,
        name: str | None,
        aliases_str: str | None,
        identifiers: ItemIdentifiers | None = None,
    ) -> None:
        """Reject a name that is another item's name or alias, or an alias that is another
        item's name or alias, before anything is written.

        Compared as item resolution compares them (``match_key``: trimmed, Unicode
        casefolded, unlike SQLite's ASCII-only NOCASE), since any such clash makes the
        name ambiguous. *name* is checked when given (pass ``None`` when it is unchanged);
        of *aliases_str* only aliases the item does not already have are checked, so data
        stored before this check never blocks unrelated edits. An item's alias equal to its
        own name is harmless. *identifiers* is read from the database when not given.
        """
        aliases = split_unique(aliases_str) if aliases_str is not None else []
        if name is None and not aliases:
            return
        if identifiers is None:
            identifiers = ItemIdentifiers(await self.repository.list_item_identifiers(inventory_id))

        if name is not None and (owner := identifiers.name_owner(name, item_id)):
            raise self._duplicate_name_error(owner, inventory_id)
        inventory = inventory_display_name(self.hass, inventory_id)
        if name is not None and (owner := identifiers.alias_owner(name, item_id)):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="name_is_alias",
                translation_placeholders={"name": name, "item": owner, "inventory": inventory},
            )
        added = [alias for alias in aliases if not identifiers.has_alias(item_id, alias)]
        if names := [alias for alias in added if identifiers.name_owner(alias, item_id)]:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="alias_is_item_name",
                translation_placeholders={"aliases": ", ".join(names), "inventory": inventory},
            )
        if taken := [alias for alias in added if identifiers.alias_owner(alias, item_id)]:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="alias_conflict",
                translation_placeholders={"aliases": ", ".join(taken)},
            )

    async def _apply_location_updates(
        self,
        inventory_id: str,
        item_id: str,
        location_name: str,
    ) -> None:
        loc_ids: list[int] = []
        for name in split_unique(location_name):
            loc_id = await self.repository.ensure_location(inventory_id, name)
            if loc_id not in loc_ids:
                loc_ids.append(loc_id)
        try:
            await self.repository.set_item_locations(item_id, loc_ids)
        except aiosqlite.IntegrityError as exc:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="location_assignment_failed",
                translation_placeholders={
                    "locations": location_name,
                    "inventory": inventory_display_name(self.hass, inventory_id),
                },
            ) from exc

    async def _apply_category_updates(self, item_id: str, category_name: str) -> None:
        ids: list[int] = []
        for name in split_unique(category_name):
            cat_id = await self.repository.ensure_category(name)
            if cat_id not in ids:
                ids.append(cat_id)
        try:
            await self.repository.set_item_categories(item_id, ids)
        except aiosqlite.IntegrityError as exc:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="category_assignment_failed",
                translation_placeholders={"categories": category_name},
            ) from exc

    def _prepare_update_payload(
        self,
        inventory_id: str,
        current_item: dict[str, Any],
        new_name: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        allowed_fields = self._get_allowed_update_fields()

        for field, value in data.items():
            if field not in allowed_fields and field not in (
                FIELD_NAME,
                FIELD_LOCATION,
                FIELD_CATEGORY,
            ):
                continue
            if field in (FIELD_LOCATION, FIELD_CATEGORY):
                continue
            processed = self._process_field_value(field, value)
            payload[field] = processed

        payload[FIELD_NAME] = self._validate_and_clean_name(
            new_name or current_item.get(FIELD_NAME, ""), inventory_id
        )

        if FIELD_DESCRIPTION in data or FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED in data:
            description_value = payload.get(
                FIELD_DESCRIPTION, current_item.get(FIELD_DESCRIPTION, "")
            )
            auto_add_id_enabled = payload.get(
                FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED,
                current_item.get(FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED, False),
            )
            payload[FIELD_DESCRIPTION] = self._process_description_update(
                description_value,
                inventory_id,
                bool(auto_add_id_enabled),
            )

        return payload

    async def _after_change(self, inventory_id: str) -> None:
        await self._fire_update_events(inventory_id)

    async def _fire_update_events(self, inventory_id: str | None) -> None:
        # The hub's cache is shared by every reader, so a write through any coordinator
        # is seen everywhere.
        self.hub.invalidate(inventory_id)
        if inventory_id:
            self.hass.bus.async_fire(updated_event(inventory_id))
        self.hass.bus.async_fire(EVENT_UPDATED)

    def _process_field_value(self, field: str, value: Any) -> Any:
        if field in self._INTEGER_FIELDS:
            return max(0, int(value)) if value is not None else 0
        if field in self._NUMERIC_FIELDS:
            return round_quantity(max(0, float(value))) if value is not None else 0.0
        if field in self._BOOLEAN_FIELDS:
            return bool(value)
        if field in self._STRING_FIELDS:
            return str(value) if value is not None else ""
        return value

    def _validate_auto_add_config(
        self,
        item_name: str,
        inventory_id: str,
        auto_add_enabled: bool,
        auto_add_quantity: float | None,
        todo_list: str | None,
    ) -> bool:
        if not auto_add_enabled:
            return True

        if auto_add_quantity is None or auto_add_quantity < 0:
            _LOGGER.error(
                "Auto-add enabled but no valid quantity specified for item '%s' in inventory '%s'",
                item_name,
                inventory_id,
            )
            return False

        if not todo_list or not todo_list.strip():
            _LOGGER.error(
                "Auto-add enabled but no todo list specified for item '%s' in inventory '%s'",
                item_name,
                inventory_id,
            )
            return False

        return True

    def _validate_and_clean_name(self, name: str, inventory_id: str) -> str:
        if not name or not name.strip():
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="empty_item_name",
                translation_placeholders={
                    "inventory": inventory_display_name(self.hass, inventory_id)
                },
            )
        return name.strip()

    def _duplicate_name_error(self, name: str, inventory_id: str) -> ServiceValidationError:
        return ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="duplicate_item_name",
            translation_placeholders={
                "name": name,
                "inventory": inventory_display_name(self.hass, inventory_id),
            },
        )

    def _insufficient_stock_error(
        self, name: str, location: str, available: float
    ) -> ServiceValidationError:
        return ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="insufficient_stock",
            translation_placeholders={
                "name": name,
                "location": location,
                "available": f"{available:g}",
            },
        )

    def _get_allowed_update_fields(self) -> set[str]:
        return set(UPDATABLE_ITEM_FIELDS)

    def _process_description_update(
        self,
        description: str | None,
        inventory_id: str,
        auto_add_id_enabled: bool,
    ) -> str:
        normalized = (description or "").rstrip()
        if not inventory_id:
            return normalized

        id_tag = f"({inventory_id})"

        # Strip the ID tag from the description regardless of position
        if id_tag in normalized:
            normalized = normalized.replace(f" {id_tag}", "")
            normalized = normalized.replace(id_tag, "")
            normalized = normalized.strip()

        if auto_add_id_enabled:
            return f"{normalized} {id_tag}" if normalized else id_tag

        return normalized
