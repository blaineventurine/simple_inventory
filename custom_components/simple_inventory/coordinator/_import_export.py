"""Import/export mixin for SimpleInventoryCoordinator."""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any

from ..const import (
    DEFAULT_AUTO_ADD_ENABLED,
    DEFAULT_AUTO_ADD_TO_LIST_QUANTITY,
    DEFAULT_DESIRED_QUANTITY,
    DEFAULT_EXPIRY_ALERT_DAYS,
    DEFAULT_EXPIRY_DATE,
    DEFAULT_PRICE,
    DEFAULT_TODO_LIST,
    DEFAULT_TODO_QUANTITY_PLACEMENT,
    DEFAULT_UNIT,
    FIELD_AUTO_ADD_ENABLED,
    FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED,
    FIELD_AUTO_ADD_TO_LIST_QUANTITY,
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
from ._protocol import _CoordinatorProtocol


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
            "items": items,
        }

    async def async_import_inventory(
        self,
        inventory_id: str,
        data: Any,
        fmt: str = "json",
        merge_strategy: str = "skip",
    ) -> dict[str, Any]:
        """Import items into an inventory.

        merge_strategy: skip | overwrite | merge_quantities
        Returns summary: {added, updated, skipped, errors}
        """
        await self.async_initialize()

        if fmt == "csv":
            items_to_import = self._csv_to_items(data)
        elif isinstance(data, dict):
            items_to_import = data.get("items", [])
        elif isinstance(data, list):
            items_to_import = data
        else:
            return {"added": 0, "updated": 0, "skipped": 0, "errors": ["Invalid data format"]}

        added = 0
        updated = 0
        skipped = 0
        errors: list[str] = []

        for item_data in items_to_import:
            try:
                name = item_data.get(FIELD_NAME, "")
                if not name or not name.strip():
                    errors.append("Item missing name, skipped")
                    continue

                existing = await self.repository.get_item_by_name(inventory_id, name.strip())

                if existing and merge_strategy == "skip":
                    skipped += 1
                    continue

                if existing and merge_strategy == "merge_quantities":
                    new_qty = float(existing.get(FIELD_QUANTITY, 0)) + float(
                        item_data.get(FIELD_QUANTITY, 0)
                    )
                    await self.repository.update_item(existing["id"], {FIELD_QUANTITY: new_qty})
                    await self.repository.record_history_event(
                        item_id=existing["id"],
                        inventory_id=inventory_id,
                        event_type="import",
                        amount=float(item_data.get(FIELD_QUANTITY, 0)),
                        quantity_before=float(existing.get(FIELD_QUANTITY, 0)),
                        quantity_after=new_qty,
                        source="import",
                    )
                    updated += 1
                    continue

                if existing and merge_strategy == "overwrite":
                    payload = self._build_import_payload(item_data)
                    await self.repository.update_item(existing["id"], payload)
                    qty_before = float(existing.get(FIELD_QUANTITY, 0))
                    qty_after = float(payload.get(FIELD_QUANTITY, qty_before))
                    await self.repository.record_history_event(
                        item_id=existing["id"],
                        inventory_id=inventory_id,
                        event_type="import",
                        amount=qty_after,
                        quantity_before=qty_before,
                        quantity_after=qty_after,
                        source="import",
                    )

                    if FIELD_LOCATION in item_data and item_data[FIELD_LOCATION]:
                        await self._apply_location_updates(
                            inventory_id,
                            existing["id"],
                            item_data[FIELD_LOCATION],
                        )
                    if FIELD_CATEGORY in item_data and item_data[FIELD_CATEGORY]:
                        await self._apply_category_updates(
                            existing["id"], item_data[FIELD_CATEGORY]
                        )

                    updated += 1
                    continue

                # New item
                payload = self._build_import_payload(item_data)
                item_id = await self.repository.create_item(inventory_id, payload)
                qty = float(payload.get(FIELD_QUANTITY, 0))
                await self.repository.record_history_event(
                    item_id=item_id,
                    inventory_id=inventory_id,
                    event_type="import",
                    amount=qty,
                    quantity_before=0,
                    quantity_after=qty,
                    source="import",
                )

                if FIELD_LOCATION in item_data and item_data[FIELD_LOCATION]:
                    await self._apply_location_updates(
                        inventory_id, item_id, item_data[FIELD_LOCATION]
                    )
                if FIELD_CATEGORY in item_data and item_data[FIELD_CATEGORY]:
                    await self._apply_category_updates(item_id, item_data[FIELD_CATEGORY])

                added += 1

            except Exception as exc:
                errors.append(f"Error importing '{item_data.get(FIELD_NAME, '?')}': {exc}")

        if added or updated:
            await self._after_change(inventory_id)

        return {"added": added, "updated": updated, "skipped": skipped, "errors": errors}

    def _build_import_payload(self, item_data: dict[str, Any]) -> dict[str, Any]:
        """Build a clean item payload from imported data."""
        return {
            FIELD_NAME: str(item_data.get(FIELD_NAME, "")).strip(),
            FIELD_DESCRIPTION: str(item_data.get(FIELD_DESCRIPTION, "")),
            FIELD_QUANTITY: float(item_data.get(FIELD_QUANTITY, 0)),
            FIELD_UNIT: str(item_data.get(FIELD_UNIT, DEFAULT_UNIT)),
            FIELD_PRICE: float(item_data.get(FIELD_PRICE, DEFAULT_PRICE)),
            FIELD_EXPIRY_DATE: str(item_data.get(FIELD_EXPIRY_DATE, DEFAULT_EXPIRY_DATE)),
            FIELD_EXPIRY_ALERT_DAYS: int(
                item_data.get(FIELD_EXPIRY_ALERT_DAYS, DEFAULT_EXPIRY_ALERT_DAYS)
            ),
            FIELD_AUTO_ADD_ENABLED: bool(
                item_data.get(FIELD_AUTO_ADD_ENABLED, DEFAULT_AUTO_ADD_ENABLED)
            ),
            FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED: bool(
                item_data.get(FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED, False)
            ),
            FIELD_AUTO_ADD_TO_LIST_QUANTITY: float(
                item_data.get(FIELD_AUTO_ADD_TO_LIST_QUANTITY, DEFAULT_AUTO_ADD_TO_LIST_QUANTITY)
            ),
            FIELD_DESIRED_QUANTITY: float(
                item_data.get(FIELD_DESIRED_QUANTITY, DEFAULT_DESIRED_QUANTITY)
            ),
            FIELD_TODO_LIST: str(item_data.get(FIELD_TODO_LIST, DEFAULT_TODO_LIST)),
            FIELD_TODO_QUANTITY_PLACEMENT: str(
                item_data.get(FIELD_TODO_QUANTITY_PLACEMENT, DEFAULT_TODO_QUANTITY_PLACEMENT)
            ),
        }

    def _items_to_csv(self, items: list[dict[str, Any]]) -> str:
        """Convert items list to a CSV string."""
        output = io.StringIO()
        fieldnames = [
            "name",
            "description",
            "quantity",
            "unit",
            "price",
            "location",
            "category",
            "expiry_date",
            "expiry_alert_days",
            "auto_add_enabled",
            "auto_add_id_to_description_enabled",
            "auto_add_to_list_quantity",
            "desired_quantity",
            "todo_list",
            "todo_quantity_placement",
            "barcodes",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()

        for item in items:
            row = {
                "name": item.get(FIELD_NAME, ""),
                "description": item.get(FIELD_DESCRIPTION, ""),
                "quantity": item.get(FIELD_QUANTITY, 0),
                "unit": item.get(FIELD_UNIT, ""),
                "price": item.get(FIELD_PRICE, 0),
                "location": ", ".join(item.get("locations", [])) or item.get(FIELD_LOCATION, ""),
                "category": ", ".join(item.get("categories", [])) or item.get(FIELD_CATEGORY, ""),
                "expiry_date": item.get(FIELD_EXPIRY_DATE, ""),
                "expiry_alert_days": item.get(FIELD_EXPIRY_ALERT_DAYS, 0),
                "auto_add_enabled": int(item.get(FIELD_AUTO_ADD_ENABLED, False)),
                "auto_add_id_to_description_enabled": int(
                    item.get(FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED, False)
                ),
                "auto_add_to_list_quantity": item.get(FIELD_AUTO_ADD_TO_LIST_QUANTITY, 0),
                "desired_quantity": item.get(FIELD_DESIRED_QUANTITY, 0),
                "todo_list": item.get(FIELD_TODO_LIST, ""),
                "todo_quantity_placement": item.get(
                    FIELD_TODO_QUANTITY_PLACEMENT, DEFAULT_TODO_QUANTITY_PLACEMENT
                ),
                "barcodes": ", ".join(item.get("barcodes", [])),
            }
            writer.writerow(row)

        return output.getvalue()

    def _csv_to_items(self, csv_string: str) -> list[dict[str, Any]]:
        """Parse a CSV string into a list of item dicts."""
        reader = csv.DictReader(io.StringIO(csv_string))
        items: list[dict[str, Any]] = []
        for row in reader:
            item: dict[str, Any] = {
                FIELD_NAME: row.get("name", ""),
                FIELD_DESCRIPTION: row.get("description", ""),
                FIELD_QUANTITY: float(row.get("quantity", 0) or 0),
                FIELD_UNIT: row.get("unit", ""),
                FIELD_PRICE: float(row.get("price", 0) or 0),
                FIELD_LOCATION: row.get("location", ""),
                FIELD_CATEGORY: row.get("category", ""),
                FIELD_EXPIRY_DATE: row.get("expiry_date", ""),
                FIELD_EXPIRY_ALERT_DAYS: int(row.get("expiry_alert_days", 0) or 0),
                FIELD_AUTO_ADD_ENABLED: bool(int(row.get("auto_add_enabled", 0) or 0)),
                FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED: bool(
                    int(row.get("auto_add_id_to_description_enabled", 0) or 0)
                ),
                FIELD_AUTO_ADD_TO_LIST_QUANTITY: float(
                    row.get("auto_add_to_list_quantity", 0) or 0
                ),
                FIELD_DESIRED_QUANTITY: float(row.get("desired_quantity", 0) or 0),
                FIELD_TODO_LIST: row.get("todo_list", ""),
                FIELD_TODO_QUANTITY_PLACEMENT: row.get(
                    "todo_quantity_placement", DEFAULT_TODO_QUANTITY_PLACEMENT
                ),
            }
            items.append(item)
        return items
