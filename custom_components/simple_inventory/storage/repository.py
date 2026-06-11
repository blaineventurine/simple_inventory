from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Sequence, cast

import aiosqlite
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from ..const import (
    DEFAULT_AUTO_ADD_TO_LIST_QUANTITY,
    DEFAULT_DESIRED_QUANTITY,
    DEFAULT_EXPIRY_ALERT_DAYS,
    DEFAULT_PRICE,
    DEFAULT_QUANTITY,
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
    INVENTORY_ITEMS,
    INVENTORY_NAME,
    STORAGE_KEY,
    STORAGE_VERSION,
    compute_quantity_needed,
)

_LOGGER = logging.getLogger(__name__)

SCHEMA_VERSION = 3
LEGACY_MIGRATION_FLAG = "legacy_migrated"


class InventoryRepository:
    """SQLite-backed storage for Simple Inventory."""

    _migration_lock: asyncio.Lock = asyncio.Lock()

    def __init__(self, hass: HomeAssistant, db_filename: str = "simple_inventory.db") -> None:
        self._hass = hass
        self._db_path = Path(hass.config.path(db_filename))
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def async_initialize(self) -> None:
        """Open DB, ensure schema, migrate if needed."""
        async with self._lock:
            if self._conn is None:
                self._conn = await aiosqlite.connect(self._db_path)
                self._conn.row_factory = aiosqlite.Row
                _LOGGER.debug("Opened Simple Inventory database at %s", self._db_path)
                await self._conn.execute("PRAGMA foreign_keys = ON")
                await self._conn.execute("PRAGMA journal_mode = WAL")
                await self._conn.execute("PRAGMA synchronous = NORMAL")
                await self._conn.execute("PRAGMA busy_timeout = 5000")

        await self._ensure_schema()
        await self._maybe_migrate_legacy_store()

    async def _maybe_migrate_legacy_store(self) -> None:
        async with InventoryRepository._migration_lock:
            await self._maybe_migrate_legacy_store_locked()

    async def _maybe_migrate_legacy_store_locked(self) -> None:
        """Load legacy JSON storage and persist into SQLite once."""
        assert self._conn is not None

        cursor = await self._conn.execute(
            "SELECT value FROM metadata WHERE key = ?", (LEGACY_MIGRATION_FLAG,)
        )
        row = await cursor.fetchone()
        await cursor.close()

        if row is not None and row[0] == "1":
            return

        await self._conn.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            (LEGACY_MIGRATION_FLAG, "running"),
        )
        await self._conn.commit()

        store = Store[dict[str, Any]](self._hass, STORAGE_VERSION, STORAGE_KEY)
        legacy_data = await store.async_load()

        if not legacy_data:
            await self._conn.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                (LEGACY_MIGRATION_FLAG, "1"),
            )
            await self._conn.commit()
            return

        inventories = legacy_data.get("inventories", {})
        for inventory_id, inventory_payload in inventories.items():
            await self._migrate_inventory(inventory_id, inventory_payload)

        await self._conn.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            (LEGACY_MIGRATION_FLAG, "1"),
        )
        await self._conn.commit()
        _LOGGER.info("Legacy Simple Inventory data migrated to SQLite backend")

    async def _migrate_inventory(self, inventory_id: str, payload: dict[str, Any]) -> None:
        """Migrate a single inventory record into SQLite."""
        name = payload.get(INVENTORY_NAME, inventory_id)
        description = payload.get("description", "")
        icon = payload.get("icon", "")

        await self.upsert_inventory(inventory_id, name, description, icon)

        items = payload.get(INVENTORY_ITEMS, {})
        for item_name, item_data in items.items():
            await self._migrate_item(inventory_id, item_name, item_data, payload)

    async def _migrate_item(
        self,
        inventory_id: str,
        legacy_name: str,
        legacy_item: dict[str, Any],
        inventory_payload: dict[str, Any],
    ) -> None:
        """Migrate a single item entry, merging with existing rows if needed."""
        item_payload: dict[str, Any] = {
            FIELD_NAME: legacy_item.get(FIELD_NAME, legacy_name),
            FIELD_DESCRIPTION: legacy_item.get(FIELD_DESCRIPTION, ""),
            FIELD_QUANTITY: float(legacy_item.get(FIELD_QUANTITY, 0)),
            FIELD_UNIT: legacy_item.get(FIELD_UNIT, ""),
            FIELD_EXPIRY_DATE: legacy_item.get(FIELD_EXPIRY_DATE, ""),
            FIELD_EXPIRY_ALERT_DAYS: int(legacy_item.get(FIELD_EXPIRY_ALERT_DAYS, 0)),
            FIELD_AUTO_ADD_ENABLED: legacy_item.get(FIELD_AUTO_ADD_ENABLED, False),
            FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED: legacy_item.get(
                FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED, False
            ),
            FIELD_AUTO_ADD_TO_LIST_QUANTITY: float(
                legacy_item.get(FIELD_AUTO_ADD_TO_LIST_QUANTITY, 0)
            ),
            FIELD_DESIRED_QUANTITY: float(legacy_item.get(FIELD_DESIRED_QUANTITY, 0)),
            FIELD_TODO_LIST: legacy_item.get(FIELD_TODO_LIST, ""),
            FIELD_TODO_QUANTITY_PLACEMENT: legacy_item.get(FIELD_TODO_QUANTITY_PLACEMENT, "name"),
        }

        item_id = await self.create_item(inventory_id, item_payload)

        location_name = legacy_item.get(FIELD_LOCATION, "")
        if location_name:
            location_id = await self.ensure_location(inventory_id, location_name)
            await self.set_item_locations(item_id, [location_id])

        category_name = legacy_item.get(FIELD_CATEGORY, "")
        if category_name:
            category_id = await self.ensure_category(category_name)
            await self.set_item_categories(item_id, [category_id])

    async def get_barcode_provider_config(self) -> dict[str, Any]:
        """Read the barcode lookup provider configuration from the metadata table."""
        assert self._conn is not None
        cursor = await self._conn.execute(
            "SELECT value FROM metadata WHERE key = ?", ("barcode_lookup_provider",)
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return {}
        import json

        try:
            return cast(dict[str, Any], json.loads(row[0]))
        except (json.JSONDecodeError, TypeError):
            return {}

    async def set_barcode_provider_config(self, config: dict[str, Any]) -> None:
        """Write barcode lookup provider configuration to the metadata table."""
        assert self._conn is not None
        import json

        await self._conn.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            ("barcode_lookup_provider", json.dumps(config)),
        )
        await self._conn.commit()

    async def async_close(self) -> None:
        """Close the database connection."""
        async with self._lock:
            if self._conn:
                await self._conn.close()
                self._conn = None

    async def _ensure_schema(self) -> None:
        """Create tables and metadata if needed."""
        async with self._lock:
            assert self._conn is not None

            await self._conn.executescript("""
                DROP INDEX IF EXISTS idx_items_name_inventory;
                DROP INDEX IF EXISTS idx_locations_unique_name;

                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS inventories (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    icon TEXT DEFAULT '',
                    entry_type TEXT DEFAULT '',
                    metadata TEXT DEFAULT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_inventories_name
                    ON inventories (LOWER(name));

                CREATE TABLE IF NOT EXISTS items (
                    id TEXT PRIMARY KEY,
                    inventory_id TEXT NOT NULL,
                    name TEXT NOT NULL COLLATE NOCASE,
                    description TEXT DEFAULT '',
                    quantity REAL NOT NULL DEFAULT 0,
                    unit TEXT DEFAULT '',
                    expiry_date TEXT DEFAULT '',
                    expiry_alert_days INTEGER DEFAULT 0,
                    auto_add_enabled INTEGER NOT NULL DEFAULT 0,
                    auto_add_id_to_description_enabled INTEGER NOT NULL DEFAULT 0,
                    auto_add_to_list_quantity REAL NOT NULL DEFAULT 0,
                    desired_quantity REAL NOT NULL DEFAULT 0,
                    todo_list TEXT DEFAULT '',
                    todo_quantity_placement TEXT NOT NULL DEFAULT 'name',
                    price REAL NOT NULL DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (inventory_id) REFERENCES inventories(id) ON DELETE CASCADE,
                    UNIQUE (inventory_id, name)
                );

                CREATE INDEX IF NOT EXISTS idx_items_inventory_id
                    ON items (inventory_id);

                CREATE TABLE IF NOT EXISTS locations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    inventory_id TEXT NOT NULL,
                    name TEXT NOT NULL COLLATE NOCASE,
                    description TEXT DEFAULT '',
                    color TEXT DEFAULT '',
                    sort_order INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (inventory_id) REFERENCES inventories(id) ON DELETE CASCADE,
                    UNIQUE (inventory_id, name)
                );

                CREATE TABLE IF NOT EXISTS item_locations (
                    item_id TEXT NOT NULL,
                    location_id INTEGER NOT NULL,
                    PRIMARY KEY (item_id, location_id),
                    FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE,
                    FOREIGN KEY (location_id) REFERENCES locations(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL COLLATE NOCASE
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_categories_name
                    ON categories (name);

                CREATE TABLE IF NOT EXISTS item_categories (
                    item_id TEXT NOT NULL,
                    category_id INTEGER NOT NULL,
                    PRIMARY KEY (item_id, category_id),
                    FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE,
                    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS item_barcodes (
                    item_id TEXT NOT NULL,
                    inventory_id TEXT NOT NULL,
                    barcode TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (item_id, barcode),
                    FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE,
                    FOREIGN KEY (inventory_id) REFERENCES inventories(id) ON DELETE CASCADE
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_item_barcodes_unique
                    ON item_barcodes (inventory_id, barcode);
                """)

            await self._ensure_schema_version()
            await self._conn.commit()

    async def _ensure_schema_version(self) -> None:
        """Store or validate the schema version entry, running migrations as needed."""
        assert self._conn is not None
        cursor = await self._conn.execute("SELECT value FROM metadata WHERE key = 'schema_version'")
        row = await cursor.fetchone()
        await cursor.close()

        if row is None:
            await self._conn.execute(
                """
                INSERT OR IGNORE INTO metadata (key, value)
                VALUES (?, ?)
                """,
                ("schema_version", str(SCHEMA_VERSION)),
            )
            await self._migrate_to_v2()
            await self._migrate_to_v3()
            return

        current_version = int(row[0])
        if current_version < SCHEMA_VERSION:
            if current_version < 2:
                await self._migrate_to_v2()
            if current_version < 3:
                await self._migrate_to_v3()
            await self._conn.execute(
                "UPDATE metadata SET value = ? WHERE key = 'schema_version'",
                (str(SCHEMA_VERSION),),
            )
        elif current_version != SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema version {current_version} does not match expected {SCHEMA_VERSION}"
            )

    async def _migrate_to_v2(self) -> None:
        """Add consumption_history table (schema v1 -> v2)."""
        assert self._conn is not None
        await self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS consumption_history (
                id TEXT PRIMARY KEY,
                item_id TEXT NOT NULL,
                inventory_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                amount REAL NOT NULL DEFAULT 0,
                quantity_before REAL NOT NULL,
                quantity_after REAL NOT NULL,
                source TEXT NOT NULL DEFAULT 'service',
                location_from TEXT DEFAULT '',
                location_to TEXT DEFAULT '',
                timestamp TEXT NOT NULL,
                metadata TEXT DEFAULT '',
                FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE,
                FOREIGN KEY (inventory_id) REFERENCES inventories(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_history_item_id
                ON consumption_history (item_id);
            CREATE INDEX IF NOT EXISTS idx_history_inventory_id
                ON consumption_history (inventory_id);
            CREATE INDEX IF NOT EXISTS idx_history_timestamp
                ON consumption_history (timestamp);
            CREATE INDEX IF NOT EXISTS idx_history_event_type
                ON consumption_history (event_type);
        """)

    async def _migrate_to_v3(self) -> None:
        """Add price column to items and consumption_history (schema v2 -> v3)."""
        assert self._conn is not None
        # Add price to items table
        with contextlib.suppress(Exception):
            await self._conn.execute("ALTER TABLE items ADD COLUMN price REAL NOT NULL DEFAULT 0")
        # Add price to consumption_history table
        with contextlib.suppress(Exception):
            await self._conn.execute(
                "ALTER TABLE consumption_history ADD COLUMN price REAL NOT NULL DEFAULT 0"
            )

    def _connection(self) -> aiosqlite.Connection:
        """Accessor for the open connection."""
        if self._conn is None:
            raise RuntimeError("InventoryRepository not initialized")
        return self._conn

    async def fetch_inventory(self, inventory_id: str) -> dict[str, Any] | None:
        conn = self._connection()
        cursor = await conn.execute(
            """
            SELECT id, name, description, icon, entry_type, metadata,
                   created_at, updated_at
            FROM inventories
            WHERE id = ?
            """,
            (inventory_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None

        return {
            "id": row[0],
            "name": row[1],
            "description": row[2],
            "icon": row[3],
            "entry_type": row[4],
            "metadata": row[5],
            "created_at": row[6],
            "updated_at": row[7],
        }

    async def upsert_inventory(
        self,
        inventory_id: str,
        name: str,
        description: str = "",
        icon: str = "",
        entry_type: str = "",
        metadata: str | None = None,
    ) -> None:
        """Create or update an inventory record."""
        conn = self._connection()
        async with self._lock:
            await conn.execute(
                """
                INSERT INTO inventories (id, name, description, icon, entry_type, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    icon = excluded.icon,
                    entry_type = excluded.entry_type,
                    metadata = excluded.metadata,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (inventory_id, name, description, icon, entry_type, metadata),
            )
            await conn.commit()

    async def delete_inventory(self, inventory_id: str) -> bool:
        """Delete an inventory and all its data (cascades via FK constraints)."""
        conn = self._connection()
        async with self._lock:
            cursor = await conn.execute("DELETE FROM inventories WHERE id = ?", (inventory_id,))
            await conn.commit()
            return cursor.rowcount > 0

    async def list_inventories(self) -> list[dict[str, Any]]:
        """Return all inventories."""
        conn = self._connection()
        cursor = await conn.execute("""
            SELECT id, name, description, icon, entry_type, metadata,
                   created_at, updated_at
            FROM inventories
            ORDER BY name COLLATE NOCASE
            """)
        rows = await cursor.fetchall()
        await cursor.close()
        return [
            {
                "id": row[0],
                "name": row[1],
                "description": row[2],
                "icon": row[3],
                "entry_type": row[4],
                "metadata": row[5],
                "created_at": row[6],
                "updated_at": row[7],
            }
            for row in rows
        ]

    async def create_item(self, inventory_id: str, data: dict[str, Any]) -> str:
        """Insert or merge an item; returns item_id."""
        item_id = data.get("id") or str(uuid.uuid4())
        payload = {
            FIELD_NAME: data[FIELD_NAME],
            FIELD_DESCRIPTION: data.get(FIELD_DESCRIPTION, ""),
            FIELD_QUANTITY: data.get(FIELD_QUANTITY, 0),
            FIELD_UNIT: data.get(FIELD_UNIT, ""),
            FIELD_EXPIRY_DATE: data.get(FIELD_EXPIRY_DATE, ""),
            FIELD_EXPIRY_ALERT_DAYS: data.get(FIELD_EXPIRY_ALERT_DAYS, 0),
            FIELD_AUTO_ADD_ENABLED: int(data.get(FIELD_AUTO_ADD_ENABLED, False)),
            FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED: int(
                data.get(FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED, False)
            ),
            FIELD_AUTO_ADD_TO_LIST_QUANTITY: data.get(FIELD_AUTO_ADD_TO_LIST_QUANTITY, 0),
            FIELD_DESIRED_QUANTITY: data.get(FIELD_DESIRED_QUANTITY, 0),
            FIELD_TODO_LIST: data.get(FIELD_TODO_LIST, ""),
            FIELD_TODO_QUANTITY_PLACEMENT: data.get(FIELD_TODO_QUANTITY_PLACEMENT, "name"),
            FIELD_PRICE: data.get(FIELD_PRICE, DEFAULT_PRICE),
        }

        conn = self._connection()
        params = (
            item_id,
            inventory_id,
            payload[FIELD_NAME],
            payload[FIELD_DESCRIPTION],
            payload[FIELD_QUANTITY],
            payload[FIELD_UNIT],
            payload[FIELD_EXPIRY_DATE],
            payload[FIELD_EXPIRY_ALERT_DAYS],
            payload[FIELD_AUTO_ADD_ENABLED],
            payload[FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED],
            payload[FIELD_AUTO_ADD_TO_LIST_QUANTITY],
            payload[FIELD_DESIRED_QUANTITY],
            payload[FIELD_TODO_LIST],
            payload[FIELD_TODO_QUANTITY_PLACEMENT],
            payload[FIELD_PRICE],
        )

        async with self._lock:
            cursor = await conn.execute(
                """
                INSERT INTO items (
                    id, inventory_id, name, description, quantity, unit,
                    expiry_date, expiry_alert_days,
                    auto_add_enabled, auto_add_id_to_description_enabled,
                    auto_add_to_list_quantity, desired_quantity, todo_list,
                    todo_quantity_placement, price
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(inventory_id, name) DO UPDATE SET
                    quantity = items.quantity + excluded.quantity,
                    description = CASE
                        WHEN excluded.description != '' THEN excluded.description
                        ELSE items.description
                    END,
                    unit = CASE
                        WHEN excluded.unit != '' THEN excluded.unit
                        ELSE items.unit
                    END,
                    expiry_date = CASE
                        WHEN excluded.expiry_date != '' THEN excluded.expiry_date
                        ELSE items.expiry_date
                    END,
                    expiry_alert_days = excluded.expiry_alert_days,
                    auto_add_enabled = excluded.auto_add_enabled,
                    auto_add_id_to_description_enabled = excluded.auto_add_id_to_description_enabled,
                    auto_add_to_list_quantity = excluded.auto_add_to_list_quantity,
                    desired_quantity = excluded.desired_quantity,
                    todo_list = CASE
                        WHEN excluded.todo_list != '' THEN excluded.todo_list
                        ELSE items.todo_list
                    END,
                    todo_quantity_placement = excluded.todo_quantity_placement,
                    price = CASE
                        WHEN excluded.price > 0 THEN excluded.price
                        ELSE items.price
                    END,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id
                """,
                params,
            )
            row = await cursor.fetchone()
            await cursor.close()
            await conn.commit()

        return cast(str, row[0]) if row else item_id

    async def update_item(self, item_id: str, data: dict[str, Any]) -> bool:
        """Update an item record; returns True if a row was updated."""
        column_map = {
            FIELD_NAME: "name",
            FIELD_DESCRIPTION: "description",
            FIELD_QUANTITY: "quantity",
            FIELD_UNIT: "unit",
            FIELD_EXPIRY_DATE: "expiry_date",
            FIELD_EXPIRY_ALERT_DAYS: "expiry_alert_days",
            FIELD_AUTO_ADD_ENABLED: "auto_add_enabled",
            FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED: "auto_add_id_to_description_enabled",
            FIELD_AUTO_ADD_TO_LIST_QUANTITY: "auto_add_to_list_quantity",
            FIELD_DESIRED_QUANTITY: "desired_quantity",
            FIELD_TODO_LIST: "todo_list",
            FIELD_TODO_QUANTITY_PLACEMENT: "todo_quantity_placement",
            FIELD_PRICE: "price",
        }

        fields: list[str] = []
        params: list[Any] = []

        for field, column in column_map.items():
            if field in data:
                value = data[field]
                if field in (FIELD_AUTO_ADD_ENABLED, FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED):
                    value = int(value)
                fields.append(f"{column} = ?")
                params.append(value)

        if not fields:
            return False

        params.append(item_id)
        conn = self._connection()
        async with self._lock:
            cursor = await conn.execute(
                f"""
                UPDATE items
                SET {', '.join(fields)}, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                tuple(params),
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def delete_item(self, item_id: str) -> bool:
        """Delete an item and any related rows."""
        conn = self._connection()
        async with self._lock:
            cursor = await conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
            await conn.commit()
            return cursor.rowcount > 0

    async def list_items_with_details(self, inventory_id: str) -> list[dict[str, Any]]:
        """Return items plus associated locations and categories."""
        conn = self._connection()

        cursor = await conn.execute(
            """
            SELECT
                id,
                name,
                description,
                quantity,
                unit,
                expiry_date,
                expiry_alert_days,
                auto_add_enabled,
                auto_add_id_to_description_enabled,
                auto_add_to_list_quantity,
                desired_quantity,
                todo_list,
                todo_quantity_placement,
                price,
                created_at,
                updated_at
            FROM items
            WHERE inventory_id = ?
            ORDER BY LOWER(name)
            """,
            (inventory_id,),
        )
        base_rows = await cursor.fetchall()
        await cursor.close()

        items: dict[str, dict[str, Any]] = {}
        for row in base_rows:
            item_id = row[0]
            items[item_id] = {
                "id": item_id,
                "inventory_id": inventory_id,
                FIELD_NAME: row[1],
                FIELD_DESCRIPTION: row[2],
                FIELD_QUANTITY: row[3],
                FIELD_UNIT: row[4],
                FIELD_EXPIRY_DATE: row[5],
                FIELD_EXPIRY_ALERT_DAYS: row[6],
                FIELD_AUTO_ADD_ENABLED: bool(row[7]),
                FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED: bool(row[8]),
                FIELD_AUTO_ADD_TO_LIST_QUANTITY: row[9],
                FIELD_DESIRED_QUANTITY: row[10],
                FIELD_TODO_LIST: row[11],
                FIELD_TODO_QUANTITY_PLACEMENT: row[12],
                FIELD_PRICE: row[13],
                "created_at": row[14],
                "updated_at": row[15],
                FIELD_CATEGORY: "",
                FIELD_LOCATION: "",
                "locations": [],
                "categories": [],
                "barcodes": [],
            }

        if not items:
            return []

        cursor = await conn.execute(
            """
            SELECT il.item_id, l.name
            FROM item_locations il
            JOIN locations l ON l.id = il.location_id
            JOIN items i ON i.id = il.item_id
            WHERE i.inventory_id = ?
            """,
            (inventory_id,),
        )
        location_rows = await cursor.fetchall()
        await cursor.close()
        for item_id, location_name in location_rows:
            if item_id not in items:
                continue
            items[item_id]["locations"].append(location_name)
            if not items[item_id][FIELD_LOCATION]:
                items[item_id][FIELD_LOCATION] = location_name

        cursor = await conn.execute(
            """
            SELECT ic.item_id, c.name
            FROM item_categories ic
            JOIN categories c ON c.id = ic.category_id
            JOIN items i ON i.id = ic.item_id
            WHERE i.inventory_id = ?
            """,
            (inventory_id,),
        )
        category_rows = await cursor.fetchall()
        await cursor.close()
        for item_id, category_name in category_rows:
            if item_id not in items:
                continue
            items[item_id]["categories"].append(category_name)
            if not items[item_id][FIELD_CATEGORY]:
                items[item_id][FIELD_CATEGORY] = category_name

        cursor = await conn.execute(
            """
            SELECT ib.item_id, ib.barcode
            FROM item_barcodes ib
            JOIN items i ON i.id = ib.item_id
            WHERE i.inventory_id = ?
            ORDER BY ib.barcode
            """,
            (inventory_id,),
        )
        barcode_rows = await cursor.fetchall()
        await cursor.close()
        for item_id, barcode in barcode_rows:
            if item_id not in items:
                continue
            items[item_id]["barcodes"].append(barcode)

        return list(items.values())

    async def get_item_by_name(self, inventory_id: str, name: str) -> dict[str, Any] | None:
        """Retrieve item by inventory and case-insensitive name."""
        conn = self._connection()
        cursor = await conn.execute(
            """
            SELECT id, inventory_id, name, description, quantity, unit,
                   expiry_date, expiry_alert_days, auto_add_enabled,
                   auto_add_id_to_description_enabled, auto_add_to_list_quantity,
                   desired_quantity, todo_list, todo_quantity_placement,
                   price, created_at, updated_at
            FROM items
            WHERE inventory_id = ?
              AND name = ?
            """,
            (inventory_id, name),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if not row:
            return None

        return {
            "id": row[0],
            "inventory_id": row[1],
            FIELD_NAME: row[2],
            FIELD_DESCRIPTION: row[3],
            FIELD_QUANTITY: row[4],
            FIELD_UNIT: row[5],
            FIELD_EXPIRY_DATE: row[6],
            FIELD_EXPIRY_ALERT_DAYS: row[7],
            FIELD_AUTO_ADD_ENABLED: bool(row[8]),
            FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED: bool(row[9]),
            FIELD_AUTO_ADD_TO_LIST_QUANTITY: row[10],
            FIELD_DESIRED_QUANTITY: row[11],
            FIELD_TODO_LIST: row[12],
            FIELD_TODO_QUANTITY_PLACEMENT: row[13],
            FIELD_PRICE: row[14],
            "created_at": row[15],
            "updated_at": row[16],
        }

    async def ensure_location(self, inventory_id: str, name: str) -> int:
        """Fetch or create a location for an inventory."""
        conn = self._connection()
        async with self._lock:
            cursor = await conn.execute(
                """
                INSERT INTO locations (inventory_id, name)
                VALUES (?, ?)
                ON CONFLICT(inventory_id, name) DO UPDATE SET
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id
                """,
                (inventory_id, name),
            )
            row = await cursor.fetchone()
            await cursor.close()
            await conn.commit()
        if row is None:
            raise RuntimeError("Failed to ensure location; no row returned")

        return cast(int, row["id"])

    async def set_item_locations(
        self,
        item_id: str,
        location_ids: Sequence[int],
    ) -> None:
        """Replace all location entries for an item."""
        conn = self._connection()
        async with self._lock:
            await conn.execute("DELETE FROM item_locations WHERE item_id = ?", (item_id,))
            if location_ids:
                await conn.executemany(
                    """
                    INSERT INTO item_locations (item_id, location_id)
                    VALUES (?, ?)
                    """,
                    [(item_id, loc_id) for loc_id in location_ids],
                )
            await conn.commit()

    async def ensure_category(self, name: str) -> int:
        """Fetch or create a category."""
        conn = self._connection()
        async with self._lock:
            cursor = await conn.execute(
                """
                INSERT INTO categories (name)
                VALUES (?)
                ON CONFLICT(name) DO UPDATE SET
                    name = excluded.name
                RETURNING id
                """,
                (name,),
            )
            row = await cursor.fetchone()
            await cursor.close()
            await conn.commit()
        if row is None:
            raise RuntimeError("Failed to ensure location; no row returned")

        return cast(int, row["id"])

    async def set_item_categories(self, item_id: str, category_ids: Sequence[int]) -> None:
        """Replace category associations for an item."""
        conn = self._connection()
        async with self._lock:
            await conn.execute("DELETE FROM item_categories WHERE item_id = ?", (item_id,))
            if category_ids:
                await conn.executemany(
                    "INSERT INTO item_categories (item_id, category_id) VALUES (?, ?)",
                    [(item_id, category_id) for category_id in category_ids],
                )
            await conn.commit()

    async def add_item_barcode(self, item_id: str, inventory_id: str, barcode: str) -> None:
        """Associate a barcode with an item."""
        conn = self._connection()
        async with self._lock:
            await conn.execute(
                """
                INSERT INTO item_barcodes (item_id, inventory_id, barcode)
                VALUES (?, ?, ?)
                ON CONFLICT(item_id, barcode) DO NOTHING
                """,
                (item_id, inventory_id, barcode),
            )
            await conn.commit()

    async def remove_item_barcode(self, item_id: str, barcode: str) -> None:
        """Remove a barcode association from an item."""
        conn = self._connection()
        async with self._lock:
            await conn.execute(
                "DELETE FROM item_barcodes WHERE item_id = ? AND barcode = ?",
                (item_id, barcode),
            )
            await conn.commit()

    async def get_item_by_barcode(self, inventory_id: str, barcode: str) -> dict[str, Any] | None:
        """Retrieve an item by barcode within an inventory."""
        conn = self._connection()
        cursor = await conn.execute(
            """
            SELECT i.id, i.inventory_id, i.name, i.description, i.quantity,
                   i.unit, i.expiry_date, i.expiry_alert_days,
                   i.auto_add_enabled, i.auto_add_id_to_description_enabled,
                   i.auto_add_to_list_quantity, i.desired_quantity,
                   i.todo_list, i.todo_quantity_placement,
                   i.price, i.created_at, i.updated_at
            FROM items i
            JOIN item_barcodes ib ON ib.item_id = i.id
            WHERE ib.inventory_id = ?
              AND ib.barcode = ?
            """,
            (inventory_id, barcode),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if not row:
            return None

        return {
            "id": row[0],
            "inventory_id": row[1],
            FIELD_NAME: row[2],
            FIELD_DESCRIPTION: row[3],
            FIELD_QUANTITY: row[4],
            FIELD_UNIT: row[5],
            FIELD_EXPIRY_DATE: row[6],
            FIELD_EXPIRY_ALERT_DAYS: row[7],
            FIELD_AUTO_ADD_ENABLED: bool(row[8]),
            FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED: bool(row[9]),
            FIELD_AUTO_ADD_TO_LIST_QUANTITY: row[10],
            FIELD_DESIRED_QUANTITY: row[11],
            FIELD_TODO_LIST: row[12],
            FIELD_TODO_QUANTITY_PLACEMENT: row[13],
            FIELD_PRICE: row[14],
            "created_at": row[15],
            "updated_at": row[16],
        }

    async def get_item_by_barcode_global(self, barcode: str) -> list[dict[str, Any]]:
        """Cross-inventory barcode lookup. Returns all items matching the barcode."""
        conn = self._connection()
        cursor = await conn.execute(
            """
            SELECT i.id, i.inventory_id, inv.name AS inventory_name,
                   i.name, i.description, i.quantity, i.unit,
                   i.expiry_date, i.expiry_alert_days,
                   i.auto_add_enabled, i.auto_add_id_to_description_enabled,
                   i.auto_add_to_list_quantity, i.desired_quantity,
                   i.todo_list, i.todo_quantity_placement,
                   i.price, i.created_at, i.updated_at
            FROM items i
            JOIN item_barcodes ib ON ib.item_id = i.id
            JOIN inventories inv ON inv.id = i.inventory_id
            WHERE ib.barcode = ?
            """,
            (barcode,),
        )
        rows = await cursor.fetchall()
        await cursor.close()

        return [
            {
                "id": row[0],
                "inventory_id": row[1],
                "inventory_name": row[2],
                FIELD_NAME: row[3],
                FIELD_DESCRIPTION: row[4],
                FIELD_QUANTITY: row[5],
                FIELD_UNIT: row[6],
                FIELD_EXPIRY_DATE: row[7],
                FIELD_EXPIRY_ALERT_DAYS: row[8],
                FIELD_AUTO_ADD_ENABLED: bool(row[9]),
                FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED: bool(row[10]),
                FIELD_AUTO_ADD_TO_LIST_QUANTITY: row[11],
                FIELD_DESIRED_QUANTITY: row[12],
                FIELD_TODO_LIST: row[13],
                FIELD_TODO_QUANTITY_PLACEMENT: row[14],
                FIELD_PRICE: row[15],
                "created_at": row[16],
                "updated_at": row[17],
            }
            for row in rows
        ]

    async def set_item_barcodes(self, item_id: str, inventory_id: str, barcodes: list[str]) -> None:
        """Replace all barcodes for an item."""
        conn = self._connection()
        async with self._lock:
            await conn.execute("DELETE FROM item_barcodes WHERE item_id = ?", (item_id,))
            if barcodes:
                await conn.executemany(
                    """
                    INSERT INTO item_barcodes (item_id, inventory_id, barcode)
                    VALUES (?, ?, ?)
                    """,
                    [(item_id, inventory_id, bc) for bc in barcodes],
                )
            await conn.commit()

    async def get_barcodes_for_item(self, item_id: str) -> list[str]:
        """Return all barcodes associated with an item."""
        conn = self._connection()
        cursor = await conn.execute(
            "SELECT barcode FROM item_barcodes WHERE item_id = ? ORDER BY barcode",
            (item_id,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [row[0] for row in rows]

    async def compute_inventory_stats(self, inventory_id: str) -> dict[str, Any]:
        """Return aggregate statistics for an inventory."""
        items = await self.list_items_with_details(inventory_id)

        total_items = len(items)
        total_quantity = sum(float(item.get(FIELD_QUANTITY, DEFAULT_QUANTITY)) for item in items)

        categories = await self.get_category_counts(inventory_id)
        locations = await self.get_location_item_counts(inventory_id)

        below_threshold: list[dict[str, Any]] = []
        for item in items:
            quantity = float(item.get(FIELD_QUANTITY, 0))
            threshold = float(
                item.get(FIELD_AUTO_ADD_TO_LIST_QUANTITY, DEFAULT_AUTO_ADD_TO_LIST_QUANTITY)
            )
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
                        FIELD_UNIT: item.get(FIELD_UNIT, ""),
                        FIELD_CATEGORY: item.get(FIELD_CATEGORY, ""),
                    }
                )

        expiring = await self.list_items_expiring_before(
            date.today()
            + timedelta(
                days=max(
                    DEFAULT_EXPIRY_ALERT_DAYS,
                    *(int(it.get(FIELD_EXPIRY_ALERT_DAYS, 0)) for it in items),
                )
            ),
            inventory_id=inventory_id,
        )

        total_value = sum(
            float(item.get(FIELD_QUANTITY, 0)) * float(item.get(FIELD_PRICE, 0))
            for item in items
            if float(item.get(FIELD_PRICE, 0)) > 0
        )

        return {
            "total_items": total_items,
            "total_quantity": total_quantity,
            "total_value": total_value,
            "categories": categories,
            "locations": locations,
            "below_threshold": below_threshold,
            "expiring_items": expiring,
        }

    async def list_items_expiring_before(
        self,
        limit_date: date | datetime,
        inventory_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return items whose expiry date is before/eq limit_date."""
        conn = self._connection()
        params: list[Any] = []
        where_clause = ""

        if isinstance(limit_date, datetime):
            limit_date = limit_date.date()

        if inventory_id:
            where_clause = "AND items.inventory_id = ?"
            params.append(inventory_id)

        cursor = await conn.execute(
            f"""
            SELECT
                items.inventory_id,
                items.id,
                items.name,
                items.expiry_date,
                items.expiry_alert_days,
                items.quantity
            FROM items
            WHERE items.expiry_date != ''
              AND DATE(items.expiry_date) <= DATE(?)
              AND items.quantity > 0
              {where_clause}
            ORDER BY DATE(items.expiry_date)
            """,
            [limit_date.isoformat(), *params],
        )
        rows = await cursor.fetchall()
        await cursor.close()

        results: list[dict[str, Any]] = []
        today = date.today()

        for inv_id, item_id, name, expiry_str, alert_days, quantity in rows:
            try:
                expiry_date = datetime.strptime(expiry_str, "%Y-%m-%d").date()
            except ValueError:
                continue

            results.append(
                {
                    "inventory_id": inv_id,
                    "item_id": item_id,
                    FIELD_NAME: name,
                    FIELD_EXPIRY_DATE: expiry_str,
                    FIELD_EXPIRY_ALERT_DAYS: alert_days,
                    FIELD_QUANTITY: quantity,
                    "days_until_expiry": (expiry_date - today).days,
                }
            )

        return results

    async def list_items_with_auto_add_condition(
        self,
        inventory_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return items eligible for auto-add processing (quantity <= threshold)."""
        conn = self._connection()
        params: list[Any] = []
        where_clause = ""

        if inventory_id:
            where_clause = "AND items.inventory_id = ?"
            params.append(inventory_id)

        cursor = await conn.execute(
            f"""
            SELECT
                items.inventory_id,
                items.id,
                items.name,
                items.quantity,
                items.auto_add_to_list_quantity,
                items.desired_quantity,
                items.todo_list,
                items.auto_add_enabled
            FROM items
            WHERE items.auto_add_enabled = 1
              AND items.todo_list != ''
              AND items.auto_add_to_list_quantity >= 0
              AND items.quantity <= items.auto_add_to_list_quantity
              {where_clause}
            """,
            params,
        )
        rows = await cursor.fetchall()
        await cursor.close()

        return [
            {
                "inventory_id": row[0],
                "item_id": row[1],
                FIELD_NAME: row[2],
                FIELD_QUANTITY: row[3],
                FIELD_AUTO_ADD_TO_LIST_QUANTITY: row[4],
                FIELD_DESIRED_QUANTITY: row[5],
                FIELD_TODO_LIST: row[6],
                FIELD_AUTO_ADD_ENABLED: bool(row[7]),
            }
            for row in rows
        ]

    async def record_history_event(
        self,
        item_id: str,
        inventory_id: str,
        event_type: str,
        amount: float,
        quantity_before: float,
        quantity_after: float,
        source: str = "service",
        location_from: str = "",
        location_to: str = "",
        metadata: str = "",
        price: float = 0,
    ) -> str:
        """Record a consumption/inventory history event. Returns event ID."""
        event_id = str(uuid.uuid4())
        timestamp = datetime.utcnow().isoformat()
        conn = self._connection()
        async with self._lock:
            await conn.execute(
                """
                INSERT INTO consumption_history (
                    id, item_id, inventory_id, event_type, amount,
                    quantity_before, quantity_after, source,
                    location_from, location_to, timestamp, metadata, price
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    item_id,
                    inventory_id,
                    event_type,
                    amount,
                    quantity_before,
                    quantity_after,
                    source,
                    location_from,
                    location_to,
                    timestamp,
                    metadata,
                    price,
                ),
            )
            await conn.commit()
        return event_id

    async def get_item_history(
        self,
        item_id: str,
        *,
        event_type: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return history events for a specific item."""
        return await self._query_history(
            item_id=item_id,
            event_type=event_type,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset,
        )

    async def get_inventory_history(
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
        return await self._query_history(
            inventory_id=inventory_id,
            event_type=event_type,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset,
        )

    async def _query_history(
        self,
        *,
        item_id: str | None = None,
        inventory_id: str | None = None,
        event_type: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Query history events with optional filters."""
        conn = self._connection()
        conditions: list[str] = []
        params: list[Any] = []

        if item_id:
            conditions.append("ch.item_id = ?")
            params.append(item_id)
        if inventory_id:
            conditions.append("ch.inventory_id = ?")
            params.append(inventory_id)
        if event_type:
            conditions.append("ch.event_type = ?")
            params.append(event_type)
        if start_date:
            conditions.append("ch.timestamp >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("ch.timestamp <= ?")
            params.append(end_date)

        where = ""
        if conditions:
            where = "WHERE " + " AND ".join(conditions)

        params.extend([limit, offset])
        cursor = await conn.execute(
            f"""
            SELECT ch.id, ch.item_id, ch.inventory_id, ch.event_type,
                   ch.amount, ch.quantity_before, ch.quantity_after,
                   ch.source, ch.location_from, ch.location_to,
                   ch.timestamp, ch.metadata, i.name AS item_name, ch.price
            FROM consumption_history ch
            LEFT JOIN items i ON i.id = ch.item_id
            {where}
            ORDER BY ch.timestamp DESC
            LIMIT ? OFFSET ?
            """,
            params,
        )
        rows = await cursor.fetchall()
        await cursor.close()

        return [
            {
                "id": row[0],
                "item_id": row[1],
                "inventory_id": row[2],
                "event_type": row[3],
                "amount": float(row[4]),
                "quantity_before": float(row[5]),
                "quantity_after": float(row[6]),
                "source": row[7],
                "location_from": row[8],
                "location_to": row[9],
                "timestamp": row[10],
                "metadata": row[11],
                "item_name": row[12] or "",
                FIELD_PRICE: float(row[13]) if row[13] else 0,
            }
            for row in rows
        ]

    async def get_location_item_counts(self, inventory_id: str) -> dict[str, int]:
        """Return count of items per location."""
        conn = self._connection()
        cursor = await conn.execute(
            """
            SELECT locations.name, COUNT(*)
            FROM item_locations
            JOIN locations ON locations.id = item_locations.location_id
            WHERE locations.inventory_id = ?
            GROUP BY locations.name
            """,
            (inventory_id,),
        )
        rows = await cursor.fetchall()
        await cursor.close()

        return {row[0]: int(row[1]) for row in rows}

    async def get_category_counts(self, inventory_id: str) -> dict[str, int]:
        """Return count of items per category."""
        conn = self._connection()
        cursor = await conn.execute(
            """
            SELECT categories.name, COUNT(*)
            FROM item_categories
            JOIN categories ON categories.id = item_categories.category_id
            JOIN items ON items.id = item_categories.item_id
            WHERE items.inventory_id = ?
            GROUP BY categories.name
            """,
            (inventory_id,),
        )
        rows = await cursor.fetchall()
        await cursor.close()

        return {row[0]: int(row[1]) for row in rows}

    async def get_item_consumption_stats(
        self,
        item_id: str,
        *,
        window_days: int | None = None,
    ) -> dict[str, Any]:
        """Return raw consumption aggregates for a single item."""
        conn = self._connection()

        if window_days is not None:
            window_start = (datetime.utcnow() - timedelta(days=window_days)).isoformat()
        else:
            window_start = ""

        cursor = await conn.execute(
            """
            WITH
            decrements AS (
                SELECT COUNT(*) AS cnt, COALESCE(SUM(amount), 0) AS total,
                       MIN(timestamp) AS first_ts, MAX(timestamp) AS last_ts
                FROM consumption_history
                WHERE item_id = ? AND event_type = 'decrement'
                  AND (? = '' OR timestamp >= ?)
            ),
            restocks AS (
                SELECT timestamp FROM consumption_history
                WHERE item_id = ? AND event_type IN ('increment', 'add')
                  AND (? = '' OR timestamp >= ?)
                ORDER BY timestamp
            ),
            spend AS (
                SELECT COALESCE(SUM(price * amount), 0) AS total_spend,
                       SUM(CASE WHEN price > 0 THEN 1 ELSE 0 END) AS priced_count
                FROM consumption_history
                WHERE item_id = ? AND event_type IN ('increment', 'add')
                  AND (? = '' OR timestamp >= ?)
            )
            SELECT d.cnt, d.total, d.first_ts, d.last_ts,
                   (SELECT COUNT(*) FROM restocks),
                   (SELECT GROUP_CONCAT(timestamp, '|') FROM restocks),
                   s.total_spend, s.priced_count
            FROM decrements d, spend s
            """,
            (
                item_id,
                window_start,
                window_start,
                item_id,
                window_start,
                window_start,
                item_id,
                window_start,
                window_start,
            ),
        )
        row = await cursor.fetchone()
        await cursor.close()

        if row is None:
            return {
                "item_id": item_id,
                "window_days": window_days,
                "window_start": window_start,
                "decrement_count": 0,
                "total_consumed": 0.0,
                "first_event_ts": None,
                "last_event_ts": None,
                "restock_count": 0,
                "restock_timestamps": [],
                "total_spend": 0.0,
                "restock_spend_count": 0,
            }

        restock_ts_raw = row[5] or ""
        restock_timestamps = [ts for ts in restock_ts_raw.split("|") if ts]

        return {
            "item_id": item_id,
            "window_days": window_days,
            "window_start": window_start,
            "decrement_count": int(row[0]),
            "total_consumed": float(row[1]),
            "first_event_ts": row[2],
            "last_event_ts": row[3],
            "restock_count": int(row[4]),
            "restock_timestamps": restock_timestamps,
            "total_spend": float(row[6]),
            "restock_spend_count": int(row[7] or 0),
        }

    async def get_inventory_consumption_stats(
        self,
        inventory_id: str,
        *,
        window_days: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return consumption aggregates for all items in an inventory."""
        conn = self._connection()

        if window_days is not None:
            window_start = (datetime.utcnow() - timedelta(days=window_days)).isoformat()
        else:
            window_start = ""

        cursor = await conn.execute(
            """
            WITH
            consumption AS (
                SELECT item_id, COUNT(*) AS cnt, SUM(amount) AS total,
                       MIN(timestamp) AS first_ts, MAX(timestamp) AS last_ts
                FROM consumption_history
                WHERE inventory_id = ? AND event_type = 'decrement'
                  AND (? = '' OR timestamp >= ?)
                GROUP BY item_id
            ),
            restocks AS (
                SELECT item_id, COUNT(*) AS cnt,
                       GROUP_CONCAT(timestamp, '|') AS timestamps
                FROM consumption_history
                WHERE inventory_id = ? AND event_type IN ('increment', 'add')
                  AND (? = '' OR timestamp >= ?)
                GROUP BY item_id
            )
            SELECT i.id, i.name, i.quantity, i.unit,
                   COALESCE(c.cnt, 0), COALESCE(c.total, 0),
                   c.first_ts, c.last_ts,
                   COALESCE(r.cnt, 0), r.timestamps
            FROM items i
            LEFT JOIN consumption c ON c.item_id = i.id
            LEFT JOIN restocks r ON r.item_id = i.id
            WHERE i.inventory_id = ?
            ORDER BY LOWER(i.name)
            """,
            (
                inventory_id,
                window_start,
                window_start,
                inventory_id,
                window_start,
                window_start,
                inventory_id,
            ),
        )
        rows = await cursor.fetchall()
        await cursor.close()

        results: list[dict[str, Any]] = []
        for row in rows:
            restock_ts_raw = row[9] or ""
            restock_timestamps = [ts for ts in restock_ts_raw.split("|") if ts]
            results.append(
                {
                    "item_id": row[0],
                    "item_name": row[1],
                    "current_quantity": float(row[2]),
                    "unit": row[3] or "",
                    "window_days": window_days,
                    "window_start": window_start,
                    "decrement_count": int(row[4]),
                    "total_consumed": float(row[5]),
                    "first_event_ts": row[6],
                    "last_event_ts": row[7],
                    "restock_count": int(row[8]),
                    "restock_timestamps": restock_timestamps,
                }
            )

        return results
