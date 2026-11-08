"""Import/export mixin for SimpleInventoryCoordinator."""

from __future__ import annotations

import csv
import io
import json
import logging
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, cast

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.util import dt as dt_util

from ..const import (
    DEFAULT_AUTO_ADD_ENABLED,
    DEFAULT_AUTO_ADD_TO_LIST_QUANTITY,
    DEFAULT_DESIRED_QUANTITY,
    DEFAULT_EXPIRY_ALERT_DAYS,
    DEFAULT_EXPIRY_DATE,
    DEFAULT_ITEM_ICON,
    DEFAULT_PRICE,
    DEFAULT_TODO_LIST,
    DEFAULT_TODO_QUANTITY_PLACEMENT,
    DEFAULT_UNIT,
    FIELD_ALIASES,
    FIELD_AUTO_ADD_ENABLED,
    FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED,
    FIELD_AUTO_ADD_TO_LIST_QUANTITY,
    FIELD_BARCODE,
    FIELD_BARCODES,
    FIELD_BATCHES,
    FIELD_CATEGORIES,
    FIELD_CATEGORY,
    FIELD_DESCRIPTION,
    FIELD_DESIRED_QUANTITY,
    FIELD_EXPIRY_ALERT_DAYS,
    FIELD_EXPIRY_DATE,
    FIELD_ICON,
    FIELD_IMAGE,
    FIELD_ITEMS,
    FIELD_LOCATION,
    FIELD_LOCATIONS,
    FIELD_NAME,
    FIELD_PRICE,
    FIELD_PURCHASED_AT,
    FIELD_QUANTITY,
    FIELD_TODO_LIST,
    FIELD_TODO_QUANTITY_PLACEMENT,
    FIELD_UNIT,
    FIELD_UNIT_PRICE,
    match_key,
    round_quantity,
    split_unique,
)
from ..data import get_todo_manager
from ..item_fields import ITEM_FIELDS, item_field_names
from ..storage._batches import StockChange
from ..types import InventoryItem
from ._identifiers import ItemIdentifiers
from ._protocol import _CoordinatorProtocol

_LOGGER = logging.getLogger(__name__)

_MERGE_STRATEGIES = ("skip", "overwrite", "merge_quantities")

# Spreadsheet apps evaluate cells starting with these characters as formulas.
_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_TODO_QUANTITY_PLACEMENTS = ("name", "description", "none")
# Same bounds as the add/update service schema.
_MAX_EXPIRY_ALERT_DAYS = 365

_NUMBER_FIELDS = item_field_names("float")
_QUANTITY_FIELDS = (FIELD_QUANTITY, FIELD_AUTO_ADD_TO_LIST_QUANTITY, FIELD_DESIRED_QUANTITY)
_BOOLEAN_FIELDS = item_field_names("bool")
# String fields parsed with dedicated validation (or not imported) in _parse_import_record;
# every other str registry field is imported as plain text.
_SPECIAL_TEXT_FIELDS = frozenset(
    (
        FIELD_NAME,
        FIELD_ICON,
        FIELD_IMAGE,  # exported as a has-image flag only; image files are not imported
        FIELD_LOCATION,
        FIELD_CATEGORY,
        FIELD_TODO_LIST,
        FIELD_TODO_QUANTITY_PLACEMENT,
    )
)
_TEXT_FIELDS = tuple(name for name in item_field_names("str") if name not in _SPECIAL_TEXT_FIELDS)

# Relation -> (list key emitted by export, scalar/comma-string fallback key).
# Applied in this order: barcodes and aliases can conflict with other items, so they go
# first and a conflict aborts the record before the cheaper relations are touched.
_RELATION_KEYS: tuple[tuple[str, str], ...] = (
    (FIELD_BARCODES, FIELD_BARCODE),
    (FIELD_ALIASES, FIELD_ALIASES),
    (FIELD_LOCATIONS, FIELD_LOCATION),
    (FIELD_CATEGORIES, FIELD_CATEGORY),
)

_CSV_COLUMNS = (*item_field_names(), FIELD_BARCODES, FIELD_ALIASES, FIELD_BATCHES)
# An empty cell in these columns means "not provided" rather than zero/false.
_CSV_OPTIONAL_COLUMNS = frozenset(
    (
        *_NUMBER_FIELDS,
        *_BOOLEAN_FIELDS,
        FIELD_EXPIRY_ALERT_DAYS,
        FIELD_TODO_QUANTITY_PLACEMENT,
        FIELD_BATCHES,
    )
)


class _InvalidImportRecord(ValueError):
    """An import record failed validation; nothing was written for it."""


@dataclass
class _ImportBatch:
    """Validated stock to add; ``None`` fields take the item's value when written."""

    quantity: float
    expiry_date: str | None = None
    location: str | None = None
    unit_price: float | None = None
    purchased_at: str | None = None


@dataclass
class _ImportRecord:
    """A validated import record holding only the fields the source provided."""

    name: str
    fields: dict[str, Any] = field(default_factory=dict)
    # Relation list key (FIELD_BARCODES, ...) -> comma-separated value for _apply_*_updates.
    relations: dict[str, str] = field(default_factory=dict)
    source_inventory_id: str = ""
    # Stock from ``batches`` or the scalar quantity/expiry_date; None when neither was given.
    batches: list[_ImportBatch] | None = None
    # A scalar expiry_date given without stock: applies to the item's only batch (D6).
    expiry_date: str | None = None

    @property
    def stock_quantity(self) -> float:
        return round_quantity(sum(batch.quantity for batch in self.batches or ()))


def _escape_csv_cell(value: Any) -> Any:
    """Neutralise spreadsheet formulas; quotes already present are escaped too."""
    if isinstance(value, str) and value.lstrip("'").startswith(_CSV_FORMULA_PREFIXES):
        return f"'{value}"
    return value


def _unescape_csv_cell(value: str) -> str:
    """Invert _escape_csv_cell."""
    if value.startswith("'") and value.lstrip("'").startswith(_CSV_FORMULA_PREFIXES):
        return value[1:]
    return value


class _ImportExportMixin(_CoordinatorProtocol):
    """Mixin providing JSON/CSV import and export methods."""

    async def async_export_inventory(
        self,
        inventory_id: str,
        fmt: str = "json",
    ) -> dict[str, Any] | str:
        """Export inventory data as JSON dict or CSV string."""
        await self.async_initialize()
        inventory = await self.repository.fetch_inventory(inventory_id)
        if not inventory:
            raise ValueError(f"Inventory '{inventory_id}' not found")

        items = await self.async_list_items(inventory_id)
        # The "(inventory_id)" description tag is derived from auto_add_id_to_description_enabled
        # and the owning inventory; export the user's text so imports re-tag for their target.
        for item in items:
            item[FIELD_DESCRIPTION] = self._process_description_update(
                item.get(FIELD_DESCRIPTION), inventory_id, False
            )
            # Image files are not exported (I15): only whether the item has one.
            item[FIELD_IMAGE] = bool(item.get(FIELD_IMAGE))
            # Batch IDs are database-local.
            item[FIELD_BATCHES] = [
                {key: value for key, value in batch.items() if key != "id"}
                for batch in item.get(FIELD_BATCHES, [])
            ]
        exported_at = datetime.utcnow().isoformat()

        if fmt == "csv":
            return self._items_to_csv(items)

        return {
            "version": "1.0",
            "exported_at": exported_at,
            "inventory": {
                "id": inventory.get("id"),
                "name": inventory.get("name"),
                "description": inventory.get("description", ""),
            },
            FIELD_ITEMS: items,
        }

    async def async_import_inventory(
        self,
        inventory_id: str,
        data: Any,
        fmt: str = "json",
        merge_strategy: str = "skip",
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Import items into an inventory.

        Each record is validated like the add/update services and applied atomically:
        an invalid or failing record is reported in ``errors`` and leaves no trace.

        merge_strategy (for records whose name already exists):
          skip             - leave the existing item alone
          overwrite        - replace only the fields present in the record (stock is
                             replaced when ``batches`` or ``quantity`` is present)
          merge_quantities - add the record's stock as new/merged batches

        dry_run: when True, runs the identical validation and merge-strategy decisions
        but skips every actual write and the post-import todo-list sync, so the summary
        previews exactly what a real import would do without changing anything.
        Returns summary: {added, updated, skipped, errors}
        """
        await self.async_initialize()

        added = 0
        updated = 0
        skipped = 0
        errors: list[str] = []

        if merge_strategy not in _MERGE_STRATEGIES:
            errors.append(
                f"Invalid merge strategy '{merge_strategy}'; "
                f"expected one of {', '.join(_MERGE_STRATEGIES)}"
            )
            return {"added": 0, "updated": 0, "skipped": 0, "errors": errors}

        entries: list[tuple[str, Any]]
        if fmt == "csv":
            if not isinstance(data, str):
                errors.append("CSV import data must be a string")
                return {"added": 0, "updated": 0, "skipped": 0, "errors": errors}
            entries = self._csv_to_items(data, errors)
        else:
            raw_items = data.get(FIELD_ITEMS, []) if isinstance(data, Mapping) else data
            if not isinstance(raw_items, list):
                errors.append("Invalid data format: 'items' must be a list of item objects")
                return {"added": 0, "updated": 0, "skipped": 0, "errors": errors}
            entries = [(f"Item {index}", raw) for index, raw in enumerate(raw_items, start=1)]

        wrote = False
        # (stored name, row before the write or None for a new item) per written record.
        written: list[tuple[str, Mapping[str, Any] | None]] = []
        # Relation snapshots (list_items_with_details rows) used to restore an item when an
        # overwrite fails part-way. Loaded lazily; an item's entry is dropped once it changes.
        details: dict[str, dict[str, Any]] | None = None
        # Names and aliases for matching and the clash checks, read once and kept current
        # as records are written so a later record sees the earlier ones. In a dry run,
        # this is still kept current from each *parsed* record (not a written row), so a
        # later record in the same preview still sees earlier ones for clash detection.
        identifiers = ItemIdentifiers(await self.repository.list_item_identifiers(inventory_id))

        for label, raw in entries:
            if not isinstance(raw, Mapping):
                errors.append(f"{label}: expected an item object, got {type(raw).__name__}")
                continue

            raw_name = raw.get(FIELD_NAME)
            prefix = f"{label} ('{raw_name}')" if isinstance(raw_name, str) else label
            try:
                record = self._parse_import_record(raw)
                existing = await self._find_import_target(inventory_id, record.name, identifiers)

                if existing is None:
                    if not dry_run:
                        wrote = True
                        item_id = await self._import_new_item(inventory_id, record, identifiers)
                        identifiers.set_item(
                            item_id, record.name, self._import_aliases(record) or []
                        )
                        written.append((record.name, None))
                    else:
                        identifiers.set_item(
                            record.name, record.name, self._import_aliases(record) or []
                        )
                    added += 1
                elif merge_strategy == "skip":
                    skipped += 1
                elif merge_strategy == "merge_quantities":
                    delta = record.stock_quantity
                    if not delta:
                        skipped += 1
                        continue
                    if not dry_run:
                        wrote = True
                        await self._import_merge_quantity(inventory_id, existing, record)
                        written.append((existing[FIELD_NAME], existing))
                    updated += 1
                else:
                    if (
                        not record.fields
                        and not record.relations
                        and record.batches is None
                        and record.expiry_date is None
                    ):
                        skipped += 1
                        continue
                    if not dry_run:
                        if record.relations and (details is None or existing["id"] not in details):
                            details = {
                                item["id"]: item
                                for item in await self.async_list_items(inventory_id)
                            }
                        snapshot = details.pop(existing["id"], {}) if details is not None else {}
                        wrote = True
                        await self._import_overwrite_item(
                            inventory_id, existing, snapshot, record, identifiers
                        )
                        identifiers.set_item(
                            existing["id"], existing[FIELD_NAME], self._import_aliases(record)
                        )
                        written.append((existing[FIELD_NAME], existing))
                    updated += 1
            except Exception as exc:  # noqa: BLE001 - every failure is reported per record
                errors.append(f"{prefix}: {exc}")

        if wrote and not dry_run:
            await self._after_change(inventory_id)
            await self._sync_imported_todo_entries(inventory_id, written)

        return {"added": added, "updated": updated, "skipped": skipped, "errors": errors}

    async def _find_import_target(
        self, inventory_id: str, name: str, identifiers: ItemIdentifiers
    ) -> dict[str, Any] | None:
        """The existing item *name* refers to, compared as item resolution compares names.

        The exact ``NOCASE`` lookup comes first, so an item named exactly so wins over a
        non-ASCII case variant left by data stored before the duplicate checks; it folds
        ASCII only, so "čokolada" for "Čokolada" is found through *identifiers*.

        In a dry run, ``identifiers`` may hold a synthetic id (the record's own name)
        for an item that was never actually written; such an id has no database row, so
        a minimal stand-in dict is returned instead.
        """
        existing = await self.repository.get_item_by_name(inventory_id, name)
        if existing is not None:
            return existing
        item_id = identifiers.item_named(name)
        if item_id is None:
            return None
        item = await self.repository.get_item_by_id(item_id)
        return item if item is not None else {"id": item_id, FIELD_NAME: name}

    @staticmethod
    def _import_aliases(record: _ImportRecord) -> list[str] | None:
        """The aliases a record sets, or ``None`` when it leaves them unchanged."""
        aliases = record.relations.get(FIELD_ALIASES)
        return None if aliases is None else split_unique(aliases)

    async def _sync_imported_todo_entries(
        self, inventory_id: str, written: list[tuple[str, Mapping[str, Any] | None]]
    ) -> None:
        """Sync written items' todo entries, as the services do after their own changes."""
        todo_manager = get_todo_manager(self.hass)
        if todo_manager is None or not written:
            return
        items = {
            match_key(str(item[FIELD_NAME])): item
            for item in await self.async_list_items(inventory_id)
        }
        for name, previous in written:
            item = items.get(match_key(name))
            if item is not None:
                await todo_manager.async_sync(
                    str(item[FIELD_NAME]),
                    cast(InventoryItem, item),
                    previous=cast(InventoryItem | None, previous),
                )

    # ------------------------------------------------------------------
    # Record validation
    # ------------------------------------------------------------------

    def _parse_import_record(self, raw: Mapping[str, Any]) -> _ImportRecord:
        """Validate one import record; only fields present (and non-null) are kept."""
        name = raw.get(FIELD_NAME)
        if not isinstance(name, str) or not name.strip():
            raise _InvalidImportRecord("item is missing a name")
        record = _ImportRecord(name=name.strip())

        source_inventory_id = raw.get("inventory_id")
        if isinstance(source_inventory_id, str):
            record.source_inventory_id = source_inventory_id

        def present(key: str) -> bool:
            return raw.get(key) is not None

        for key in _NUMBER_FIELDS:
            if present(key):
                number = self._import_number(key, raw[key])
                record.fields[key] = round_quantity(number) if key in _QUANTITY_FIELDS else number

        if present(FIELD_EXPIRY_ALERT_DAYS):
            record.fields[FIELD_EXPIRY_ALERT_DAYS] = self._import_alert_days(
                raw[FIELD_EXPIRY_ALERT_DAYS]
            )

        for key in _BOOLEAN_FIELDS:
            if present(key):
                try:
                    flag = cv.boolean(raw[key])
                except vol.Invalid as exc:
                    raise _InvalidImportRecord(
                        f"{key} must be a boolean, got {raw[key]!r}"
                    ) from exc
                record.fields[key] = self._process_field_value(key, flag)

        for key in _TEXT_FIELDS:
            if present(key):
                record.fields[key] = self._process_field_value(
                    key, self._import_text(key, raw[key])
                )

        if present(FIELD_ICON):
            icon = self._import_text(FIELD_ICON, raw[FIELD_ICON]).strip()
            if icon:
                try:
                    icon = cv.icon(icon)
                except vol.Invalid as exc:
                    raise _InvalidImportRecord(
                        f"{FIELD_ICON} must be empty or an icon like mdi:apple, got {icon!r}"
                    ) from exc
            record.fields[FIELD_ICON] = icon

        # Item quantity/expiry_date are derived from batches: a scalar quantity becomes one
        # batch; ``batches`` wins over the scalars; an expiry alone edits the only batch.
        expiry = (
            self._import_date(FIELD_EXPIRY_DATE, raw[FIELD_EXPIRY_DATE])
            if present(FIELD_EXPIRY_DATE)
            else None
        )
        quantity = record.fields.pop(FIELD_QUANTITY, None)
        if present(FIELD_BATCHES):
            record.batches = self._import_batches(raw[FIELD_BATCHES])
        elif quantity is not None:
            record.batches = [_ImportBatch(quantity, expiry)]
        else:
            record.expiry_date = expiry

        if present(FIELD_TODO_LIST):
            todo_list = self._import_text(FIELD_TODO_LIST, raw[FIELD_TODO_LIST]).strip()
            if todo_list:
                try:
                    todo_list = cv.entity_domain("todo")(todo_list)
                except vol.Invalid as exc:
                    raise _InvalidImportRecord(
                        f"{FIELD_TODO_LIST} must be a todo entity ID, got {todo_list!r}"
                    ) from exc
            record.fields[FIELD_TODO_LIST] = todo_list

        if present(FIELD_TODO_QUANTITY_PLACEMENT):
            placement = raw[FIELD_TODO_QUANTITY_PLACEMENT]
            if placement not in _TODO_QUANTITY_PLACEMENTS:
                raise _InvalidImportRecord(
                    f"{FIELD_TODO_QUANTITY_PLACEMENT} must be one of "
                    f"{', '.join(_TODO_QUANTITY_PLACEMENTS)}, got {placement!r}"
                )
            record.fields[FIELD_TODO_QUANTITY_PLACEMENT] = placement

        for list_key, scalar_key in _RELATION_KEYS:
            if present(list_key):
                record.relations[list_key] = self._import_relation(list_key, raw[list_key])
            elif present(scalar_key):
                record.relations[list_key] = self._import_relation(scalar_key, raw[scalar_key])

        return record

    def _import_number(self, key: str, value: Any) -> float:
        if isinstance(value, bool):
            raise _InvalidImportRecord(f"{key} must be a number, got {value!r}")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise _InvalidImportRecord(f"{key} must be a number, got {value!r}") from exc
        if not math.isfinite(number) or number < 0:
            raise _InvalidImportRecord(f"{key} must be a finite number >= 0, got {value!r}")
        return float(self._process_field_value(key, number))

    def _import_alert_days(self, value: Any) -> int:
        key = FIELD_EXPIRY_ALERT_DAYS
        if isinstance(value, bool):
            raise _InvalidImportRecord(f"{key} must be a whole number, got {value!r}")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise _InvalidImportRecord(f"{key} must be a whole number, got {value!r}") from exc
        if not number.is_integer() or not 0 <= number <= _MAX_EXPIRY_ALERT_DAYS:
            raise _InvalidImportRecord(
                f"{key} must be a whole number between 0 and {_MAX_EXPIRY_ALERT_DAYS}, "
                f"got {value!r}"
            )
        return int(self._process_field_value(key, int(number)))

    @staticmethod
    def _import_text(key: str, value: Any) -> str:
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise _InvalidImportRecord(f"{key} must be text, got {value!r}")
        return str(value)

    def _import_date(self, key: str, value: Any) -> str:
        text = self._import_text(key, value).strip()
        if not text:
            return ""
        try:
            return datetime.strptime(text, "%Y-%m-%d").date().isoformat()
        except ValueError as exc:
            raise _InvalidImportRecord(f"{key} must be a YYYY-MM-DD date, got {value!r}") from exc

    def _import_batches(self, value: Any) -> list[_ImportBatch]:
        """Validate a ``batches`` list (or its JSON string form from CSV)."""
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError as exc:
                raise _InvalidImportRecord(
                    f"{FIELD_BATCHES} must be a JSON list of batch objects, got {value!r}"
                ) from exc
        if not isinstance(value, list):
            raise _InvalidImportRecord(
                f"{FIELD_BATCHES} must be a list of batch objects, got {value!r}"
            )
        batches: list[_ImportBatch] = []
        for index, entry in enumerate(value, start=1):
            try:
                batches.append(self._import_batch(entry))
            except _InvalidImportRecord as exc:
                raise _InvalidImportRecord(f"{FIELD_BATCHES} entry {index}: {exc}") from exc
        return batches

    def _import_batch(self, entry: Any) -> _ImportBatch:
        if not isinstance(entry, Mapping):
            raise _InvalidImportRecord(f"expected a batch object, got {entry!r}")

        def present(key: str) -> bool:
            return entry.get(key) is not None

        if not present(FIELD_QUANTITY):
            raise _InvalidImportRecord(f"{FIELD_QUANTITY} is required")
        quantity = round_quantity(self._import_number(FIELD_QUANTITY, entry[FIELD_QUANTITY]))
        if quantity <= 0:
            raise _InvalidImportRecord(
                f"{FIELD_QUANTITY} must be > 0, got {entry[FIELD_QUANTITY]!r}"
            )
        purchased_at = (
            self._import_date(FIELD_PURCHASED_AT, entry[FIELD_PURCHASED_AT])
            if present(FIELD_PURCHASED_AT)
            else ""
        )
        return _ImportBatch(
            quantity=quantity,
            expiry_date=(
                self._import_date(FIELD_EXPIRY_DATE, entry[FIELD_EXPIRY_DATE])
                if present(FIELD_EXPIRY_DATE)
                else ""
            ),
            location=(
                self._import_text(FIELD_LOCATION, entry[FIELD_LOCATION]).strip()
                if present(FIELD_LOCATION)
                else None
            ),
            unit_price=(
                self._import_number(FIELD_UNIT_PRICE, entry[FIELD_UNIT_PRICE])
                if present(FIELD_UNIT_PRICE)
                else None
            ),
            purchased_at=purchased_at or None,
        )

    @staticmethod
    def _import_relation(key: str, value: Any) -> str:
        """Normalise a list (export shape) or comma-string (service shape) to a comma-string."""
        values: Iterable[Any] = value if isinstance(value, list) else [value]
        parts: list[str] = []
        for entry in values:
            if isinstance(entry, bool) or not isinstance(entry, (str, int, float)):
                raise _InvalidImportRecord(f"{key} must be text or a list of text, got {value!r}")
            parts.append(str(entry))
        return ", ".join(parts)

    def _import_description(
        self, description: str, record: _ImportRecord, inventory_id: str, tag: bool
    ) -> str:
        """Description for this inventory: drop the source inventory's ID tag, apply ours."""
        if record.source_inventory_id and record.source_inventory_id != inventory_id:
            description = self._process_description_update(
                description, record.source_inventory_id, False
            )
        return self._process_description_update(description, inventory_id, tag)

    def _check_import_auto_add(self, name: str, inventory_id: str, item: Mapping[str, Any]) -> None:
        if not self._validate_auto_add_config(
            name,
            inventory_id,
            bool(item.get(FIELD_AUTO_ADD_ENABLED)),
            item.get(FIELD_AUTO_ADD_TO_LIST_QUANTITY),
            item.get(FIELD_TODO_LIST),
        ):
            raise _InvalidImportRecord(
                f"auto-add is enabled but no todo list is set ({FIELD_TODO_LIST})"
            )

    # ------------------------------------------------------------------
    # Writers (each leaves the item as it was on failure)
    # ------------------------------------------------------------------

    async def _apply_import_relations(
        self, inventory_id: str, item_id: str, relations: Mapping[str, str]
    ) -> None:
        for list_key, _ in _RELATION_KEYS:
            if list_key not in relations:
                continue
            value = relations[list_key]
            if list_key == FIELD_BARCODES:
                await self._apply_barcode_updates(inventory_id, item_id, value)
            elif list_key == FIELD_ALIASES:
                await self._apply_alias_updates(inventory_id, item_id, value)
            elif list_key == FIELD_LOCATIONS:
                await self._apply_location_updates(inventory_id, item_id, value)
            else:
                await self._apply_category_updates(item_id, value)

    async def _import_new_item(
        self, inventory_id: str, record: _ImportRecord, identifiers: ItemIdentifiers
    ) -> str:
        payload: dict[str, Any] = {
            FIELD_UNIT: DEFAULT_UNIT,
            FIELD_ICON: DEFAULT_ITEM_ICON,
            FIELD_PRICE: float(DEFAULT_PRICE),
            FIELD_EXPIRY_ALERT_DAYS: DEFAULT_EXPIRY_ALERT_DAYS,
            FIELD_AUTO_ADD_ENABLED: DEFAULT_AUTO_ADD_ENABLED,
            FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED: False,
            FIELD_AUTO_ADD_TO_LIST_QUANTITY: float(DEFAULT_AUTO_ADD_TO_LIST_QUANTITY),
            FIELD_DESIRED_QUANTITY: float(DEFAULT_DESIRED_QUANTITY),
            FIELD_TODO_LIST: DEFAULT_TODO_LIST,
            FIELD_TODO_QUANTITY_PLACEMENT: DEFAULT_TODO_QUANTITY_PLACEMENT,
            **record.fields,
            FIELD_NAME: record.name,
        }
        payload[FIELD_DESCRIPTION] = self._import_description(
            str(payload.get(FIELD_DESCRIPTION, "")),
            record,
            inventory_id,
            bool(payload[FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED]),
        )
        self._check_import_auto_add(record.name, inventory_id, payload)
        await self._raise_on_name_alias_clashes(
            inventory_id, "", record.name, record.relations.get(FIELD_ALIASES), identifiers
        )

        item_id = await self.repository.create_item(inventory_id, payload)
        try:
            await self._apply_import_relations(inventory_id, item_id, record.relations)
            item_price = float(payload[FIELD_PRICE])
            changes = await self._add_import_stock(
                inventory_id,
                item_id,
                record,
                default_expiry=DEFAULT_EXPIRY_DATE,
                default_price=item_price,
            )
            await self._record_import_changes(inventory_id, item_id, changes, item_price)
        except Exception:
            # Deleting the row cascades to its relations, batches and history.
            await self.repository.delete_item(item_id)
            raise
        return item_id

    async def _import_merge_quantity(
        self, inventory_id: str, existing: Mapping[str, Any], record: _ImportRecord
    ) -> None:
        item_id: str = existing["id"]
        old_price = float(existing.get(FIELD_PRICE) or 0)
        # A priced restock also sets the item's price, like a priced increment (D5).
        new_price = float(record.fields.get(FIELD_PRICE) or 0)
        item_price = new_price or old_price
        batches_before = await self.repository.list_batches(item_id)
        try:
            changes = await self._add_import_stock(
                inventory_id,
                item_id,
                record,
                default_expiry=DEFAULT_EXPIRY_DATE,
                default_price=item_price,
            )
            if new_price and new_price != old_price:
                await self.repository.update_item(item_id, {FIELD_PRICE: new_price})
            await self._record_import_changes(inventory_id, item_id, changes, item_price)
        except Exception:
            await self._restore_import_batches(item_id, batches_before)
            await self.repository.update_item(item_id, {FIELD_PRICE: old_price})
            raise

    async def _import_overwrite_item(
        self,
        inventory_id: str,
        existing: Mapping[str, Any],
        snapshot: Mapping[str, Any],
        record: _ImportRecord,
        identifiers: ItemIdentifiers,
    ) -> None:
        item_id: str = existing["id"]
        updates = dict(record.fields)
        merged = {**existing, **updates}
        if FIELD_DESCRIPTION in updates or FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED in updates:
            updates[FIELD_DESCRIPTION] = self._import_description(
                str(merged.get(FIELD_DESCRIPTION) or ""),
                record,
                inventory_id,
                bool(merged.get(FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED)),
            )
        self._check_import_auto_add(existing[FIELD_NAME], inventory_id, merged)
        await self._raise_on_name_alias_clashes(
            inventory_id, item_id, None, record.relations.get(FIELD_ALIASES), identifiers
        )

        item_price = float(merged.get(FIELD_PRICE) or 0)
        batches = await self.repository.list_batches(item_id)
        batch_fields = (
            self._single_batch_fields(existing, record, batches) if record.batches is None else {}
        )
        batches_before = batches if record.batches is not None else None
        # (batch id, original values) to undo a D6 edit of the only batch.
        batch_undo = (
            (batches[0]["id"], {key: batches[0][key] for key in batch_fields})
            if batch_fields
            else None
        )
        applied: list[str] = []
        try:
            # Stock first; history is written last so a failure leaves none behind.
            changes: list[StockChange] = []
            if batches_before is not None:
                current = round_quantity(sum(batch[FIELD_QUANTITY] for batch in batches_before))
                if current:
                    changes.append(await self.repository.consume_stock(item_id, current))
                changes += await self._add_import_stock(
                    inventory_id,
                    item_id,
                    record,
                    default_expiry=str(existing.get(FIELD_EXPIRY_DATE) or ""),
                    default_price=item_price,
                )
            if batch_undo is not None:
                await self.repository.update_batch(batch_undo[0], batch_fields)
            for list_key, _ in _RELATION_KEYS:
                if list_key in record.relations:
                    applied.append(list_key)
                    await self._apply_import_relations(
                        inventory_id, item_id, {list_key: record.relations[list_key]}
                    )
            if updates and not await self.repository.update_item(item_id, updates):
                raise _InvalidImportRecord("item no longer exists")
            await self._record_import_changes(inventory_id, item_id, changes, item_price)
        except Exception:
            await self._restore_overwritten_item(
                inventory_id, existing, snapshot, updates, applied, batches_before, batch_undo
            )
            raise

    @staticmethod
    def _single_batch_fields(
        existing: Mapping[str, Any], record: _ImportRecord, batches: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """D6: batch columns a stock-less expiry/price change sets on the item's only batch.

        Unchanged values are no-ops; a price change on an item without batches only sets
        the item's price. Raises when the change cannot target exactly one batch.
        """
        fields: dict[str, Any] = {}
        if record.expiry_date is not None and record.expiry_date != (
            existing.get(FIELD_EXPIRY_DATE) or ""
        ):
            fields[FIELD_EXPIRY_DATE] = record.expiry_date
        price = record.fields.get(FIELD_PRICE)
        if (
            price is not None
            and batches
            and float(price) != round_quantity(float(existing.get(FIELD_PRICE) or 0))
        ):
            fields[FIELD_UNIT_PRICE] = float(price)
        if fields and not batches:
            raise _InvalidImportRecord(
                f"{existing[FIELD_NAME]} has no stock; restock it with an expiry date instead"
            )
        if fields and len(batches) != 1:
            field_name = FIELD_EXPIRY_DATE if FIELD_EXPIRY_DATE in fields else FIELD_PRICE
            raise _InvalidImportRecord(
                f"{existing[FIELD_NAME]} has {len(batches)} batches; change the batch itself "
                f"instead of the item's {field_name}"
            )
        return fields

    async def _add_import_stock(
        self,
        inventory_id: str,
        item_id: str,
        record: _ImportRecord,
        *,
        default_expiry: str,
        default_price: float,
    ) -> list[StockChange]:
        """Add the record's batches; unset batch fields take the given/item defaults."""
        changes: list[StockChange] = []
        today = dt_util.now().date().isoformat()
        for batch in record.batches or ():
            changes.append(
                await self.repository.add_stock(
                    item_id,
                    inventory_id,
                    batch.quantity,
                    expiry_date=(
                        batch.expiry_date if batch.expiry_date is not None else default_expiry
                    ),
                    location_id=await self._import_location_id(
                        inventory_id, item_id, record, batch
                    ),
                    unit_price=batch.unit_price if batch.unit_price is not None else default_price,
                    purchased_at=batch.purchased_at or today,
                )
            )
        return changes

    async def _import_location_id(
        self, inventory_id: str, item_id: str, record: _ImportRecord, batch: _ImportBatch
    ) -> int | None:
        """The batch's location; unset -> the record's first location, else the item's."""
        name = batch.location
        if name is None and FIELD_LOCATIONS in record.relations:
            names = split_unique(record.relations[FIELD_LOCATIONS])
            name = names[0] if names else ""
        if name is None:
            return await self.repository.first_item_location_id(item_id)
        return await self.repository.ensure_location(inventory_id, name) if name else None

    async def _record_import_changes(
        self,
        inventory_id: str,
        item_id: str,
        changes: list[StockChange],
        item_price: float,
    ) -> None:
        """History only: a bulk import fires no per-item lifecycle events."""
        for change in changes:
            await self._record_stock_history(
                inventory_id,
                item_id,
                change,
                event_type="import",
                explicit_price=None,
                item_price=item_price,
                source="import",
            )

    async def _restore_import_batches(self, item_id: str, batches: list[dict[str, Any]]) -> None:
        """Replace the item's batches with a ``list_batches`` snapshot."""
        for batch in await self.repository.list_batches(item_id):
            await self.repository.delete_batch(batch["id"])
        for batch in batches:
            await self.repository.add_stock(
                item_id,
                batch["inventory_id"],
                batch[FIELD_QUANTITY],
                expiry_date=batch[FIELD_EXPIRY_DATE],
                location_id=batch["location_id"],
                unit_price=batch[FIELD_UNIT_PRICE],
                purchased_at=batch[FIELD_PURCHASED_AT],
            )

    async def _restore_overwritten_item(
        self,
        inventory_id: str,
        existing: Mapping[str, Any],
        snapshot: Mapping[str, Any],
        updates: Mapping[str, Any],
        relations: list[str],
        batches: list[dict[str, Any]] | None,
        batch_undo: tuple[str, dict[str, Any]] | None,
    ) -> None:
        """Best-effort undo of a failed overwrite."""
        item_id: str = existing["id"]
        try:
            if updates:
                await self.repository.update_item(
                    item_id, {key: existing[key] for key in updates if key in existing}
                )
            await self._apply_import_relations(
                inventory_id,
                item_id,
                {key: ", ".join(snapshot.get(key, [])) for key in relations},
            )
            if batches is not None:
                await self._restore_import_batches(item_id, batches)
            if batch_undo is not None:
                await self.repository.update_batch(*batch_undo)
        except Exception:  # noqa: BLE001 - the original failure is what gets reported
            _LOGGER.exception(
                "Could not restore item '%s' after a failed import", existing.get(FIELD_NAME)
            )

    # ------------------------------------------------------------------
    # CSV
    # ------------------------------------------------------------------

    def _items_to_csv(self, items: list[dict[str, Any]]) -> str:
        """Convert items list to a CSV string (formula-like cells are quote-prefixed)."""
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()

        for item in items:
            row: dict[str, Any] = {
                f.name: (
                    int(item.get(f.name, f.export_default))
                    if f.kind == "bool"
                    else item.get(f.name, f.export_default)
                )
                for f in ITEM_FIELDS
            }
            row[FIELD_IMAGE] = int(bool(item.get(FIELD_IMAGE)))
            row[FIELD_LOCATION] = ", ".join(item.get(FIELD_LOCATIONS, [])) or item.get(
                FIELD_LOCATION, ""
            )
            row[FIELD_CATEGORY] = ", ".join(item.get(FIELD_CATEGORIES, [])) or item.get(
                FIELD_CATEGORY, ""
            )
            row[FIELD_BARCODES] = ", ".join(item.get(FIELD_BARCODES, []))
            row[FIELD_ALIASES] = ", ".join(item.get(FIELD_ALIASES, []))
            row[FIELD_BATCHES] = json.dumps(item.get(FIELD_BATCHES, []))
            writer.writerow({key: _escape_csv_cell(value) for key, value in row.items()})

        return output.getvalue()

    def _csv_to_items(self, csv_string: str, errors: list[str]) -> list[tuple[str, Any]]:
        """Parse CSV into ("Row N", raw record) pairs; values are validated per record later.

        Rows are numbered like a spreadsheet (header = row 1). Only known columns that are
        present in the header are kept; empty numeric/boolean/placement cells count as
        not provided.
        """
        reader = csv.DictReader(io.StringIO(csv_string))
        entries: list[tuple[str, Any]] = []
        try:
            for row_number, row in enumerate(reader, start=2):
                record: dict[str, str] = {}
                for column in _CSV_COLUMNS:
                    value = row.get(column)
                    if value is None:
                        continue
                    value = _unescape_csv_cell(value)
                    if column in _CSV_OPTIONAL_COLUMNS and not value.strip():
                        continue
                    record[column] = value
                entries.append((f"Row {row_number}", record))
        except csv.Error as exc:
            errors.append(f"CSV parse error at line {reader.line_num}: {exc}")
        return entries
