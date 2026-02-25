"""Core coordinator for Simple Inventory integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

import aiosqlite
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from ..const import (
    DEFAULT_AUTO_ADD_ENABLED,
    DEFAULT_AUTO_ADD_TO_LIST_QUANTITY,
    DEFAULT_CATEGORY,
    DEFAULT_DESIRED_QUANTITY,
    DEFAULT_EXPIRY_ALERT_DAYS,
    DEFAULT_EXPIRY_DATE,
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
    FIELD_AUTO_ADD_ENABLED,
    FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED,
    FIELD_AUTO_ADD_TO_LIST_QUANTITY,
    FIELD_BARCODE,
    FIELD_CATEGORY,
    FIELD_DESCRIPTION,
    FIELD_DESIRED_QUANTITY,
    FIELD_EXPIRY_ALERT_DAYS,
    FIELD_EXPIRY_DATE,
    FIELD_LOCATION,
    FIELD_NAME,
    FIELD_PRICE,
    FIELD_QUANTITY,
    FIELD_TODO_LIST,
    FIELD_TODO_QUANTITY_PLACEMENT,
    FIELD_UNIT,
)
from ..storage.repository import InventoryRepository
from ._analytics import _AnalyticsMixin
from ._import_export import _ImportExportMixin
from ._statistics import _StatisticsMixin

_LOGGER = logging.getLogger(__name__)


class SimpleInventoryCoordinator(_StatisticsMixin, _ImportExportMixin, _AnalyticsMixin):
    """Facade around the SQLite repository with HA signaling."""

    _INTEGER_FIELDS = {
        FIELD_EXPIRY_ALERT_DAYS,
    }
    _NUMERIC_FIELDS = {
        FIELD_QUANTITY,
        FIELD_AUTO_ADD_TO_LIST_QUANTITY,
        FIELD_DESIRED_QUANTITY,
        FIELD_PRICE,
    }
    _BOOLEAN_FIELDS = {
        FIELD_AUTO_ADD_ENABLED,
        FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED,
    }
    _STRING_FIELDS = {
        FIELD_UNIT,
        FIELD_CATEGORY,
        FIELD_DESCRIPTION,
        FIELD_EXPIRY_DATE,
        FIELD_TODO_LIST,
        FIELD_TODO_QUANTITY_PLACEMENT,
        FIELD_LOCATION,
    }

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        repository: InventoryRepository,
    ) -> None:
        """Initialize the coordinator."""
        self.hass = hass
        self.entry = entry
        self.repository = repository
        self._listeners: list[Callable[[], None]] = []
        self._init_lock = asyncio.Lock()
        self._initialized = False

    async def async_initialize(self) -> None:
        """Perform per-entry init (repository already opened)."""
        async with self._init_lock:
            if self._initialized:
                return
            _LOGGER.debug("Coordinator ready for %s", self.entry.entry_id)
            self._initialized = True

    async def async_save_data(self, inventory_id: str | None = None) -> None:
        """Compatibility shim for legacy callers (fire update signals)."""
        await self.async_initialize()
        await self._fire_update_events(inventory_id)

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
        """Add a new item to an inventory."""
        await self.async_initialize()

        name = kwargs.get(FIELD_NAME)
        cleaned_name = self._validate_and_clean_name(str(name) if name else "", "add", inventory_id)
        quantity = max(0, float(kwargs.get(FIELD_QUANTITY, DEFAULT_QUANTITY)))

        auto_add_quantity = max(
            0,
            float(kwargs.get(FIELD_AUTO_ADD_TO_LIST_QUANTITY, DEFAULT_AUTO_ADD_TO_LIST_QUANTITY)),
        )
        auto_add_enabled = bool(kwargs.get(FIELD_AUTO_ADD_ENABLED, DEFAULT_AUTO_ADD_ENABLED))
        auto_add_id_enabled = bool(kwargs.get(FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED, False))
        todo_list = kwargs.get(FIELD_TODO_LIST, DEFAULT_TODO_LIST)

        if not self._validate_auto_add_config(
            cleaned_name, inventory_id, auto_add_enabled, auto_add_quantity, todo_list
        ):
            return None

        description = self._process_description_update(
            kwargs.get(FIELD_DESCRIPTION, ""),
            inventory_id,
            auto_add_id_enabled,
        )

        item_payload = {
            FIELD_NAME: cleaned_name,
            FIELD_DESCRIPTION: description,
            FIELD_QUANTITY: quantity,
            FIELD_UNIT: kwargs.get(FIELD_UNIT, DEFAULT_UNIT),
            FIELD_EXPIRY_DATE: kwargs.get(FIELD_EXPIRY_DATE, DEFAULT_EXPIRY_DATE),
            FIELD_EXPIRY_ALERT_DAYS: max(
                0,
                int(kwargs.get(FIELD_EXPIRY_ALERT_DAYS, DEFAULT_EXPIRY_ALERT_DAYS)),
            ),
            FIELD_AUTO_ADD_ENABLED: auto_add_enabled,
            FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED: auto_add_id_enabled,
            FIELD_AUTO_ADD_TO_LIST_QUANTITY: auto_add_quantity,
            FIELD_DESIRED_QUANTITY: max(
                0,
                float(kwargs.get(FIELD_DESIRED_QUANTITY, DEFAULT_DESIRED_QUANTITY)),
            ),
            FIELD_TODO_LIST: todo_list,
            FIELD_TODO_QUANTITY_PLACEMENT: kwargs.get(
                FIELD_TODO_QUANTITY_PLACEMENT, DEFAULT_TODO_QUANTITY_PLACEMENT
            ),
            FIELD_PRICE: max(
                0,
                float(kwargs.get(FIELD_PRICE, DEFAULT_PRICE)),
            ),
        }

        item_id = await self.repository.create_item(inventory_id, item_payload)

        await self._apply_barcode_updates(inventory_id, item_id, kwargs.get(FIELD_BARCODE, ""))

        await self._apply_location_updates(
            inventory_id,
            item_id,
            kwargs.get(FIELD_LOCATION, DEFAULT_LOCATION),
        )
        await self._apply_category_updates(item_id, kwargs.get(FIELD_CATEGORY, DEFAULT_CATEGORY))

        item_price = float(item_payload.get(FIELD_PRICE, 0))
        await self.repository.record_history_event(
            item_id=item_id,
            inventory_id=inventory_id,
            event_type="add",
            amount=quantity,
            quantity_before=0,
            quantity_after=quantity,
            price=item_price,
        )

        await self._after_change(inventory_id)
        self.hass.bus.async_fire(
            EVENT_ITEM_ADDED,
            {
                "item_name": cleaned_name,
                "inventory_id": inventory_id,
                "quantity": quantity,
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
        **kwargs: Any,
    ) -> bool:
        """Update an existing item."""
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

        updated = await self.repository.update_item(item["id"], payload)
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

        await self._after_change(inventory_id)
        return True

    async def async_remove_item(
        self, inventory_id: str, name: str | None = None, *, barcode: str | None = None
    ) -> bool:
        """Remove an item."""
        await self.async_initialize()

        resolved_name = await self._resolve_item_name(inventory_id, name, barcode)
        cleaned_name = self._validate_and_clean_name(resolved_name, "remove", inventory_id)
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
            await self._after_change(inventory_id)
            self.hass.bus.async_fire(
                EVENT_ITEM_REMOVED,
                {
                    "item_name": cleaned_name,
                    "inventory_id": inventory_id,
                },
            )
        return removed

    async def async_increment_item(
        self,
        inventory_id: str,
        name: str | None = None,
        amount: float = 1,
        *,
        barcode: str | None = None,
        price: float | None = None,
    ) -> bool:
        """Increment quantity."""
        if amount < 0:
            _LOGGER.warning(
                "Cannot increment item with negative amount: %d in inventory '%s'",
                amount,
                inventory_id,
            )
            return False

        resolved_name = await self._resolve_item_name(inventory_id, name, barcode)
        return await self._adjust_quantity(inventory_id, resolved_name, amount, price=price)

    async def async_decrement_item(
        self,
        inventory_id: str,
        name: str | None = None,
        amount: float = 1,
        *,
        barcode: str | None = None,
        price: float | None = None,
    ) -> bool:
        """Decrement quantity."""
        if amount < 0:
            _LOGGER.warning(
                "Cannot decrement item with negative amount: %d in inventory '%s'",
                amount,
                inventory_id,
            )
            return False

        resolved_name = await self._resolve_item_name(inventory_id, name, barcode)
        return await self._adjust_quantity(inventory_id, resolved_name, -amount, price=price)

    async def async_get_item(self, inventory_id: str, name: str) -> dict[str, Any] | None:
        """Return item data by name."""
        await self.async_initialize()
        return await self.repository.get_item_by_name(inventory_id, name)

    async def async_lookup_by_barcode(self, barcode: str) -> list[dict[str, Any]]:
        """Cross-inventory barcode lookup."""
        await self.async_initialize()
        return await self.repository.get_item_by_barcode_global(barcode)

    async def async_scan_barcode(
        self,
        barcode: str,
        action: str,
        amount: float = 1.0,
        inventory_id: str | None = None,
        price: float | None = None,
    ) -> dict[str, Any]:
        """Scan a barcode and perform an action (increment/decrement/lookup)."""
        await self.async_initialize()

        if inventory_id:
            item = await self.repository.get_item_by_barcode(inventory_id, barcode)
            if item is None:
                raise ServiceValidationError(
                    f"No item found for barcode '{barcode}' in inventory '{inventory_id}'"
                )
            resolved_inventory_id = inventory_id
        else:
            matches = await self.repository.get_item_by_barcode_global(barcode)
            if not matches:
                raise ServiceValidationError(
                    f"No item found for barcode '{barcode}' in any inventory"
                )
            if len(matches) > 1:
                inv_names = [m.get("inventory_name", m["inventory_id"]) for m in matches]
                raise ServiceValidationError(
                    f"Barcode '{barcode}' found in multiple inventories: "
                    f"{', '.join(inv_names)}. Specify inventory_id to disambiguate."
                )
            item = matches[0]
            resolved_inventory_id = item["inventory_id"]

        item_name = str(item[FIELD_NAME])

        if action == "lookup":
            return {"action": "lookup", "item": item, "inventory_id": resolved_inventory_id}

        if action == "increment":
            result = await self.async_increment_item(
                resolved_inventory_id, name=item_name, amount=amount, price=price
            )
            return {
                "action": "increment",
                "success": result,
                "item_name": item_name,
                "inventory_id": resolved_inventory_id,
                "amount": amount,
            }

        if action == "decrement":
            result = await self.async_decrement_item(
                resolved_inventory_id, name=item_name, amount=amount, price=price
            )
            return {
                "action": "decrement",
                "success": result,
                "item_name": item_name,
                "inventory_id": resolved_inventory_id,
                "amount": amount,
            }

        raise ValueError(
            f"Invalid action '{action}'. Must be 'increment', 'decrement', or 'lookup'"
        )

    async def async_list_items(self, inventory_id: str) -> list[dict[str, Any]]:
        """Return detailed items for an inventory."""
        await self.async_initialize()
        return await self.repository.list_items_with_details(inventory_id)

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

    def get_data(self) -> dict[str, Any]:
        """Legacy compatibility stub (returns empty data structure)."""
        return {"inventories": {}}

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register a listener."""
        self._listeners.append(listener)

        def _remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _remove

    def notify_listeners(self) -> None:
        """Invoke registered listeners."""
        for listener in list(self._listeners):
            listener()

    async def async_unload(self) -> None:
        """Unload per-entry resources (listeners, tasks).

        Repository is shared and is closed by __init__.py when the last entry unloads.
        """
        async with self._init_lock:
            self._listeners.clear()
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
                    f"No item found for barcode '{barcode}' in inventory '{inventory_id}'"
                )
            return str(item[FIELD_NAME])

        raise ServiceValidationError(
            f"Either 'name' or 'barcode' is required to identify an item "
            f"in inventory '{inventory_id}'"
        )

    async def _adjust_quantity(
        self,
        inventory_id: str,
        name: str,
        delta: float,
        price: float | None = None,
    ) -> bool:
        await self.async_initialize()

        cleaned_name = self._validate_and_clean_name(name, "update quantity", inventory_id)
        item = await self.repository.get_item_by_name(inventory_id, cleaned_name)
        if not item:
            _LOGGER.warning(
                "Cannot adjust quantity for non-existent item '%s' in inventory '%s'",
                cleaned_name,
                inventory_id,
            )
            return False

        # If a price is provided and > 0, update the item's price
        if price is not None and price > 0:
            await self.repository.update_item(item["id"], {FIELD_PRICE: price})
            item_price = price
        else:
            item_price = float(item.get(FIELD_PRICE, 0))

        qty_before = float(item.get(FIELD_QUANTITY, 0))
        new_quantity = max(0, qty_before + delta)
        updated = await self.repository.update_item(item["id"], {FIELD_QUANTITY: new_quantity})
        if updated:
            event_type = "increment" if delta > 0 else "decrement"
            await self.repository.record_history_event(
                item_id=item["id"],
                inventory_id=inventory_id,
                event_type=event_type,
                amount=abs(delta),
                quantity_before=qty_before,
                quantity_after=new_quantity,
                price=item_price,
            )

            if new_quantity == 0 and qty_before > 0:
                self.hass.bus.async_fire(
                    EVENT_ITEM_DEPLETED,
                    {
                        "item_name": cleaned_name,
                        "inventory_id": inventory_id,
                        "previous_quantity": qty_before,
                    },
                )

            if qty_before == 0 and new_quantity > 0:
                self.hass.bus.async_fire(
                    EVENT_ITEM_RESTOCKED,
                    {
                        "item_name": cleaned_name,
                        "inventory_id": inventory_id,
                        "quantity": new_quantity,
                    },
                )

            self.hass.bus.async_fire(
                EVENT_ITEM_QUANTITY_CHANGED,
                {
                    "item_name": cleaned_name,
                    "inventory_id": inventory_id,
                    "quantity_before": qty_before,
                    "quantity_after": new_quantity,
                    "amount": abs(delta),
                    "direction": "increment" if delta > 0 else "decrement",
                },
            )

            await self._after_change(inventory_id)
        return updated

    async def _apply_barcode_updates(
        self, inventory_id: str, item_id: str, barcode_str: str
    ) -> None:
        if not barcode_str:
            await self.repository.set_item_barcodes(item_id, inventory_id, [])
            return

        barcodes = [b.strip() for b in barcode_str.split(",") if b.strip()]
        if not barcodes:
            await self.repository.set_item_barcodes(item_id, inventory_id, [])
            return

        try:
            await self.repository.set_item_barcodes(item_id, inventory_id, barcodes)
        except aiosqlite.IntegrityError as exc:
            raise HomeAssistantError(
                "One or more barcodes are already assigned to another item" " in this inventory"
            ) from exc

    async def _apply_location_updates(
        self,
        inventory_id: str,
        item_id: str,
        location_name: str,
    ) -> None:
        if not location_name:
            await self.repository.set_item_locations(item_id, [])
            return

        names = [n.strip() for n in location_name.split(",") if n.strip()]
        if not names:
            await self.repository.set_item_locations(item_id, [])
            return

        loc_ids = []
        for name in names:
            loc_id = await self.repository.ensure_location(inventory_id, name)
            loc_ids.append(loc_id)
        await self.repository.set_item_locations(item_id, loc_ids)

    async def _apply_category_updates(self, item_id: str, category_name: str) -> None:
        if not category_name:
            await self.repository.set_item_categories(item_id, [])
            return

        names = [n.strip() for n in category_name.split(",") if n.strip()]
        if not names:
            await self.repository.set_item_categories(item_id, [])
            return

        ids = []
        for name in names:
            cat_id = await self.repository.ensure_category(name)
            ids.append(cat_id)
        await self.repository.set_item_categories(item_id, ids)

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
            new_name or current_item.get(FIELD_NAME, ""), "update", inventory_id
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
        self.notify_listeners()

    async def _fire_update_events(self, inventory_id: str | None) -> None:
        if inventory_id:
            self.hass.bus.async_fire(f"{DOMAIN}_updated_{inventory_id}")
        self.hass.bus.async_fire(f"{DOMAIN}_updated")

    def _process_field_value(self, field: str, value: Any) -> Any:
        if field in self._INTEGER_FIELDS:
            return max(0, int(value)) if value is not None else 0
        if field in self._NUMERIC_FIELDS:
            return max(0, float(value)) if value is not None else 0
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

    def _validate_and_clean_name(self, name: str, operation: str, inventory_id: str) -> str:
        if not name or not name.strip():
            raise ValueError(
                f"Cannot {operation} item with empty name in inventory '{inventory_id}'"
            )
        return name.strip()

    def _get_allowed_update_fields(self) -> set[str]:
        return {
            FIELD_AUTO_ADD_ENABLED,
            FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED,
            FIELD_AUTO_ADD_TO_LIST_QUANTITY,
            FIELD_DESIRED_QUANTITY,
            FIELD_CATEGORY,
            FIELD_DESCRIPTION,
            FIELD_EXPIRY_ALERT_DAYS,
            FIELD_EXPIRY_DATE,
            FIELD_PRICE,
            FIELD_QUANTITY,
            FIELD_TODO_LIST,
            FIELD_TODO_QUANTITY_PLACEMENT,
            FIELD_UNIT,
            FIELD_LOCATION,
        }

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
            # Remove " (id)" or "(id)" and clean up extra whitespace
            normalized = normalized.replace(f" {id_tag}", "")
            normalized = normalized.replace(id_tag, "")
            normalized = normalized.strip()

        if auto_add_id_enabled:
            return f"{normalized} {id_tag}" if normalized else id_tag

        return normalized
