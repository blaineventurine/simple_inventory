from __future__ import annotations

import asyncio
import contextlib
import logging
import shutil
import time
import uuid
from collections.abc import AsyncIterator, Collection
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Sequence, cast

import aiosqlite
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from ..const import (
    DEFAULT_PRICE,
    FIELD_ALIASES,
    FIELD_AUTO_ADD_ENABLED,
    FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED,
    FIELD_AUTO_ADD_TO_LIST_QUANTITY,
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
    FIELD_LOCATION,
    FIELD_LOCATIONS,
    FIELD_NAME,
    FIELD_PRICE,
    FIELD_PURCHASED_AT,
    FIELD_QUANTITY,
    FIELD_STOCKED_LOCATIONS,
    FIELD_TODO_LIST,
    FIELD_TODO_QUANTITY_PLACEMENT,
    FIELD_UNIT,
    FIELD_UNIT_PRICE,
    INVENTORY_ITEMS,
    INVENTORY_NAME,
    STORAGE_KEY,
    STORAGE_VERSION,
    round_quantity,
)
from ..item_fields import ITEM_COLUMNS, item_field_names
from ._batches import _BatchRepositoryMixin

_LOGGER = logging.getLogger(__name__)

SCHEMA_VERSION = 6
LEGACY_MIGRATION_FLAG = "legacy_migrated"

# Item columns holding quantities; rounded on every write (see const.round_quantity).
_QUANTITY_FIELDS = (FIELD_AUTO_ADD_TO_LIST_QUANTITY, FIELD_DESIRED_QUANTITY)
_BOOLEAN_FIELDS = frozenset(item_field_names("bool"))


def _casefold(value: object) -> str:
    """SQL ``casefold(x)``: Unicode case folding; NULL and non-text become ''."""
    return value.casefold() if isinstance(value, str) else ""


def _snapshots(backups_dir: Path) -> list[Path]:
    """``{label}_{time_ns}.db`` snapshots in *backups_dir*, oldest first; other files are ignored."""
    return sorted(
        (p for p in backups_dir.glob("*.db") if p.stem.rpartition("_")[2].isdigit()),
        key=lambda p: int(p.stem.rpartition("_")[2]),
    )


# Ranks: 0 exact name, 1 name prefix, 2 name contains, 3 alias, 4 barcode, 5 category,
# 6 item or batch location, 7 description, 8 unit. ``instr`` keeps ``%``/``_`` literal.
_SEARCH_SQL = """
WITH m(item_id, rank) AS (
    SELECT id, CASE WHEN casefold(name) = :q THEN 0
                    WHEN instr(casefold(name), :q) = 1 THEN 1 ELSE 2 END
      FROM items WHERE instr(casefold(name), :q) > 0
    UNION ALL SELECT item_id, 3 FROM item_aliases WHERE instr(casefold(alias), :q) > 0
    UNION ALL SELECT item_id, 4 FROM item_barcodes WHERE instr(casefold(barcode), :q) > 0
    UNION ALL SELECT ic.item_id, 5 FROM item_categories ic
      JOIN categories c ON c.id = ic.category_id WHERE instr(casefold(c.name), :q) > 0
    UNION ALL SELECT il.item_id, 6 FROM item_locations il
      JOIN locations l ON l.id = il.location_id WHERE instr(casefold(l.name), :q) > 0
    UNION ALL SELECT b.item_id, 6 FROM item_batches b
      JOIN locations l ON l.id = b.location_id WHERE instr(casefold(l.name), :q) > 0
    UNION ALL SELECT id, 7 FROM items WHERE instr(casefold(description), :q) > 0
    UNION ALL SELECT id, 8 FROM items WHERE instr(casefold(unit), :q) > 0
)
SELECT i.inventory_id AS inventory_id, i.id AS item_id, MIN(m.rank) AS rank
  FROM m JOIN items i ON i.id = m.item_id
  LEFT JOIN inventories inv ON inv.id = i.inventory_id
 WHERE i.inventory_id IN ({placeholders})
 GROUP BY i.id
 ORDER BY rank, casefold(i.name), casefold(inv.name), i.inventory_id, i.id
 LIMIT :limit
"""

# Item dict keys (= ``items`` columns) in output order; the ``bool`` registry fields are
# coerced. Every ``ITEM_COLUMNS`` column must appear (checked by tests/test_item_fields.py).
_ITEM_KEYS: tuple[str, ...] = (
    "id",
    "inventory_id",
    FIELD_NAME,
    FIELD_DESCRIPTION,
    FIELD_QUANTITY,
    FIELD_UNIT,
    FIELD_EXPIRY_DATE,
    FIELD_EXPIRY_ALERT_DAYS,
    FIELD_AUTO_ADD_ENABLED,
    FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED,
    FIELD_AUTO_ADD_TO_LIST_QUANTITY,
    FIELD_DESIRED_QUANTITY,
    FIELD_TODO_LIST,
    FIELD_TODO_QUANTITY_PLACEMENT,
    FIELD_PRICE,
    "created_at",
    "updated_at",
    FIELD_ICON,
    FIELD_IMAGE,
)
# Select list for ``FROM items i``.
_ITEM_SELECT = ", ".join(f"i.{key}" for key in _ITEM_KEYS)

_INVENTORY_KEYS = (
    "id",
    "name",
    "description",
    "icon",
    "entry_type",
    "metadata",
    "created_at",
    "updated_at",
)
_INVENTORY_SELECT = f"SELECT {', '.join(_INVENTORY_KEYS)} FROM inventories"


def _item_from_row(row: aiosqlite.Row, *extra: str) -> dict[str, Any]:
    """Map an ``_ITEM_SELECT`` row; *extra* columns selected after it follow the two ids."""
    item = dict(zip(_ITEM_KEYS + extra, row, strict=True))
    for key in _BOOLEAN_FIELDS:
        item[key] = bool(item[key])
    if not extra:
        return item
    return {key: item[key] for key in (*_ITEM_KEYS[:2], *extra, *_ITEM_KEYS[2:])}


def _inventory_from_row(row: aiosqlite.Row) -> dict[str, Any]:
    return {key: row[key] for key in _INVENTORY_KEYS}


def _consumption_from_row(row: aiosqlite.Row) -> dict[str, Any]:
    """The consumption aggregates both stats queries select under these names."""
    return {
        "decrement_count": int(row["decrement_count"]),
        "total_consumed": float(row["total_consumed"]),
        "first_event_ts": row["first_event_ts"],
        "last_event_ts": row["last_event_ts"],
        "restock_count": int(row["restock_count"]),
        "restock_timestamps": [ts for ts in (row["restock_timestamps"] or "").split("|") if ts],
        "total_spend": float(row["total_spend"]),
        "restock_spend_count": int(row["restock_spend_count"] or 0),
        "first_spend_ts": row["first_spend_ts"],
    }


class DatabaseFromNewerVersionError(RuntimeError):
    """The database schema is newer than this release supports (integration downgraded)."""

    def __init__(self, found: int, expected: int) -> None:
        super().__init__(
            f"Database schema version {found} is newer than the supported version {expected}"
        )
        self.found = found
        self.expected = expected


class SchemaMigrationError(RuntimeError):
    """A schema migration (v{found} -> v{expected}) failed partway through."""

    def __init__(self, found: int, expected: int, cause: Exception) -> None:
        super().__init__(f"Migration from schema v{found} to v{expected} failed: {cause}")
        self.found = found
        self.expected = expected


class InventoryRepository(_BatchRepositoryMixin):
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
                await self._conn.create_function("casefold", 1, _casefold, deterministic=True)
                await self._conn.execute("PRAGMA journal_mode = WAL")
                await self._conn.execute("PRAGMA synchronous = NORMAL")
                await self._conn.execute("PRAGMA busy_timeout = 5000")

        await self._ensure_schema()
        await self._maybe_migrate_legacy_store()

    async def _maybe_migrate_legacy_store(self) -> None:
        async with InventoryRepository._migration_lock:
            await self._maybe_migrate_legacy_store_locked()

    async def _maybe_migrate_legacy_store_locked(self) -> None:
        """Load legacy JSON storage and persist into SQLite once.

        The whole migration (inventories, items, relations and the completion flag) runs
        in a single transaction: any error rolls everything back so a retry starts clean.
        Items that already exist (e.g. committed by an interrupted pre-transaction run)
        are skipped rather than merged, so re-running never duplicates quantities.
        """
        conn = self._connection()

        cursor = await conn.execute(
            "SELECT value FROM metadata WHERE key = ?", (LEGACY_MIGRATION_FLAG,)
        )
        row = await cursor.fetchone()
        await cursor.close()

        if row is not None and row["value"] == "1":
            return

        store = Store[dict[str, Any]](self._hass, STORAGE_VERSION, STORAGE_KEY)
        legacy_data = await store.async_load()

        async with self._transaction() as conn:
            inventories = (legacy_data or {}).get("inventories", {})
            for inventory_id, inventory_payload in inventories.items():
                await self._migrate_inventory(conn, inventory_id, inventory_payload)
            await conn.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                (LEGACY_MIGRATION_FLAG, "1"),
            )

        if legacy_data:
            _LOGGER.info("Legacy Simple Inventory data migrated to SQLite backend")

    async def _migrate_inventory(
        self, conn: aiosqlite.Connection, inventory_id: str, payload: dict[str, Any]
    ) -> None:
        """Migrate a single inventory record into SQLite (inside the caller's transaction)."""
        name = payload.get(INVENTORY_NAME, inventory_id)
        description = payload.get("description", "")
        icon = payload.get("icon", "")

        await self._execute_upsert_inventory(conn, inventory_id, name, description, icon)

        items = payload.get(INVENTORY_ITEMS, {})
        for item_name, item_data in items.items():
            await self._migrate_item(conn, inventory_id, item_name, item_data)

    async def _migrate_item(
        self,
        conn: aiosqlite.Connection,
        inventory_id: str,
        legacy_name: str,
        legacy_item: dict[str, Any],
    ) -> None:
        """Migrate a single item entry; items that already exist are left untouched."""
        name = legacy_item.get(FIELD_NAME, legacy_name)
        if await self._fetch_item_id_by_name(conn, inventory_id, name) is not None:
            _LOGGER.debug(
                "Legacy item '%s' already exists in inventory '%s'; skipping",
                name,
                inventory_id,
            )
            return

        item_payload: dict[str, Any] = {
            FIELD_NAME: name,
            FIELD_DESCRIPTION: legacy_item.get(FIELD_DESCRIPTION, ""),
            FIELD_UNIT: legacy_item.get(FIELD_UNIT, ""),
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

        item_id = await self._insert_item(conn, inventory_id, item_payload)

        location_name = legacy_item.get(FIELD_LOCATION, "")
        location_id: int | None = None
        if location_name:
            location_id = await self._ensure_location_row(conn, inventory_id, location_name)
            await self._replace_item_locations(conn, item_id, [location_id])

        quantity = round_quantity(float(legacy_item.get(FIELD_QUANTITY, 0)))
        if quantity > 0:
            await self._insert_batch(
                conn,
                item_id,
                inventory_id,
                quantity,
                legacy_item.get(FIELD_EXPIRY_DATE) or "",
                location_id,
                float(legacy_item.get(FIELD_PRICE, 0) or 0),
                dt_util.now().date().isoformat(),
            )
            await self._refresh_item_totals(conn, item_id)

        category_name = legacy_item.get(FIELD_CATEGORY, "")
        if category_name:
            category_id = await self._ensure_category_row(conn, category_name)
            await self._replace_item_categories(conn, item_id, [category_id])

    @contextlib.asynccontextmanager
    async def _transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        """Serialize a unit of work under the write lock; commit on success, roll back
        (and re-raise) on any error so no partial write can be flushed by a later commit.
        """
        conn = self._connection()
        async with self._lock:
            try:
                yield conn
            except BaseException:
                await conn.rollback()
                raise
            await conn.commit()

    @staticmethod
    async def _fetch_item_id_by_name(
        conn: aiosqlite.Connection, inventory_id: str, name: str
    ) -> str | None:
        cursor = await conn.execute(
            "SELECT id FROM items WHERE inventory_id = ? AND name = ?", (inventory_id, name)
        )
        row = await cursor.fetchone()
        await cursor.close()
        return None if row is None else cast(str, row["id"])

    async def get_metadata_value(self, key: str) -> str | None:
        """Read a raw value from the metadata table (e.g. ``schema_version``)."""
        conn = self._connection()
        cursor = await conn.execute("SELECT value FROM metadata WHERE key = ?", (key,))
        row = await cursor.fetchone()
        await cursor.close()
        return None if row is None else str(row["value"])

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
            return cast(dict[str, Any], json.loads(row["value"]))
        except (json.JSONDecodeError, TypeError):
            return {}

    async def set_barcode_provider_config(self, config: dict[str, Any]) -> None:
        """Write barcode lookup provider configuration to the metadata table."""
        assert self._conn is not None
        import json

        async with self._lock:
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
            await self._raise_if_newer_schema()

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
                    icon TEXT NOT NULL DEFAULT '',
                    image TEXT NOT NULL DEFAULT '',
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

                CREATE TABLE IF NOT EXISTS item_aliases (
                    item_id TEXT NOT NULL,
                    inventory_id TEXT NOT NULL,
                    alias TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (item_id, alias),
                    FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE,
                    FOREIGN KEY (inventory_id) REFERENCES inventories(id) ON DELETE CASCADE
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_item_aliases_unique
                    ON item_aliases (inventory_id, alias);
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
            await self._migrate_to_v4()
            await self._migrate_to_v5()
            await self._migrate_to_v6()
            return

        current_version = int(row["value"])
        if current_version < SCHEMA_VERSION:
            # Make sure the WAL checkpoint/copy below sees everything, even if a future
            # change adds pending writes here.
            await self._conn.commit()
            snapshot_path = await self._snapshot_locked(
                f"pre_migration_v{current_version}_to_v{SCHEMA_VERSION}"
            )
            _LOGGER.info(
                "Saved pre-migration snapshot %s before migrating schema v%s -> v%s",
                snapshot_path,
                current_version,
                SCHEMA_VERSION,
            )
            try:
                if current_version < 2:
                    await self._migrate_to_v2()
                if current_version < 3:
                    await self._migrate_to_v3()
                if current_version < 4:
                    await self._migrate_to_v4()
                if current_version < 5:
                    await self._migrate_to_v5()
                if current_version < 6:
                    await self._migrate_to_v6()
                await self._conn.execute(
                    "UPDATE metadata SET value = ? WHERE key = 'schema_version'",
                    (str(SCHEMA_VERSION),),
                )
            except Exception as err:
                await self._conn.rollback()
                _LOGGER.exception(
                    "Migration from schema v%s to v%s failed", current_version, SCHEMA_VERSION
                )
                raise SchemaMigrationError(current_version, SCHEMA_VERSION, err) from err

    async def _raise_if_newer_schema(self) -> None:
        """Refuse a database written by a newer release before touching its schema."""
        conn = self._connection()
        cursor = await conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'metadata'"
        )
        has_metadata = await cursor.fetchone() is not None
        await cursor.close()
        if not has_metadata:
            return

        version = await self.get_metadata_value("schema_version")
        if version is not None and int(version) > SCHEMA_VERSION:
            raise DatabaseFromNewerVersionError(int(version), SCHEMA_VERSION)

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
        conn = self._connection()
        for table in ("items", "consumption_history"):
            cursor = await conn.execute(f"PRAGMA table_info({table})")
            columns = {row[1] for row in await cursor.fetchall()}
            await cursor.close()
            if "price" not in columns:
                await conn.execute(f"ALTER TABLE {table} ADD COLUMN price REAL NOT NULL DEFAULT 0")

    async def _migrate_to_v4(self) -> None:
        """Add item_batches + consumption_history.batch_id and backfill (schema v3 -> v4).

        Idempotent: one batch per stocked item that has none yet. items.quantity and
        items.expiry_date stay as derived columns maintained by the batch write path.
        """
        conn = self._connection()
        await conn.executescript("""
            CREATE TABLE IF NOT EXISTS item_batches (
                id TEXT PRIMARY KEY,
                item_id TEXT NOT NULL,
                inventory_id TEXT NOT NULL,
                quantity REAL NOT NULL CHECK (quantity > 0),
                expiry_date TEXT NOT NULL DEFAULT '',
                location_id INTEGER,
                unit_price REAL NOT NULL DEFAULT 0,
                purchased_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE,
                FOREIGN KEY (inventory_id) REFERENCES inventories(id) ON DELETE CASCADE,
                FOREIGN KEY (location_id) REFERENCES locations(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_item_batches_item ON item_batches (item_id);
            CREATE INDEX IF NOT EXISTS idx_item_batches_expiry
                ON item_batches (inventory_id, expiry_date);
        """)
        cursor = await conn.execute("PRAGMA table_info(consumption_history)")
        columns = {row[1] for row in await cursor.fetchall()}
        await cursor.close()
        if "batch_id" not in columns:
            await conn.execute(
                "ALTER TABLE consumption_history ADD COLUMN batch_id TEXT NOT NULL DEFAULT ''"
            )
        await conn.execute("""
            INSERT INTO item_batches (
                id, item_id, inventory_id, quantity, expiry_date, location_id,
                unit_price, purchased_at, created_at, updated_at
            )
            SELECT
                lower(hex(randomblob(16))), i.id, i.inventory_id, i.quantity,
                COALESCE(i.expiry_date, ''),
                (SELECT il.location_id FROM item_locations il
                    WHERE il.item_id = i.id ORDER BY il.rowid LIMIT 1),
                i.price, COALESCE(date(i.created_at), date('now')), datetime('now'), datetime('now')
            FROM items i
            WHERE i.quantity > 0
              AND NOT EXISTS (SELECT 1 FROM item_batches b WHERE b.item_id = i.id)
        """)
        await self._refresh_all_item_totals(conn)

    async def _migrate_to_v5(self) -> None:
        """Add items.icon (schema v4 -> v5); idempotent."""
        conn = self._connection()
        cursor = await conn.execute("PRAGMA table_info(items)")
        columns = {row[1] for row in await cursor.fetchall()}
        await cursor.close()
        if "icon" not in columns:
            await conn.execute("ALTER TABLE items ADD COLUMN icon TEXT NOT NULL DEFAULT ''")

    async def _migrate_to_v6(self) -> None:
        """Add items.image (schema v5 -> v6); idempotent."""
        conn = self._connection()
        cursor = await conn.execute("PRAGMA table_info(items)")
        columns = {row[1] for row in await cursor.fetchall()}
        await cursor.close()
        if "image" not in columns:
            await conn.execute("ALTER TABLE items ADD COLUMN image TEXT NOT NULL DEFAULT ''")

    def _connection(self) -> aiosqlite.Connection:
        """Accessor for the open connection."""
        if self._conn is None:
            raise RuntimeError("InventoryRepository not initialized")
        return self._conn

    def _backups_dir(self) -> Path:
        """`<config>/simple_inventory/backups/`, created on first use. Blocking; run in the executor."""
        path = self._db_path.parent / "simple_inventory" / "backups"
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def async_checkpoint(self) -> None:
        """Fold the WAL into the main DB file without copying anything."""
        async with self._lock:
            await self._checkpoint_locked()

    async def _checkpoint_locked(self) -> None:
        """``async_checkpoint``'s body, for callers that already hold ``self._lock``."""
        if self._conn is None:
            return
        cursor = await self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        row = await cursor.fetchone()
        await cursor.close()
        if row is not None and row[0]:
            _LOGGER.warning(
                "WAL checkpoint did not fully complete (database busy); the main DB "
                "file may be missing recently committed data"
            )

    async def async_snapshot(self, label: str) -> Path:
        """Checkpoint the WAL, copy the DB file into backups/, prune to the 3 newest.

        *label* is the filename's distinguishing prefix, e.g. ``"manual"`` or
        ``"pre_migration_v5_to_v6"``. The timestamp makes each call's filename unique.
        """
        async with self._lock:
            return await self._snapshot_locked(label)

    async def _snapshot_locked(self, label: str) -> Path:
        """``async_snapshot``'s body, for callers that already hold ``self._lock``."""
        assert self._lock.locked()
        assert self._conn is not None
        await self._checkpoint_locked()
        return await self._hass.async_add_executor_job(self._do_snapshot, label)

    def _do_snapshot(self, label: str) -> Path:
        """Blocking half of a snapshot: mkdir, copy, prune to the 3 newest. Runs in the executor."""
        backups_dir = self._backups_dir()
        target = backups_dir / f"{label}_{time.time_ns()}.db"
        shutil.copy2(self._db_path, target)

        snapshots = _snapshots(backups_dir)
        for stale in snapshots[:-3]:
            stale.unlink()

        return target

    async def async_restore(self, filename: str | None) -> Path:
        """Replace the live DB with a snapshot from backups/; reopens the connection.

        *filename* is a name as returned by ``async_snapshot`` (no path components
        accepted, to rule out traversal); ``None`` restores the most recently taken
        snapshot (automatic or manual). Raises ``FileNotFoundError`` if nothing matches.

        Reopening runs the full ``async_initialize()`` path: a snapshot older than the
        current code's ``SCHEMA_VERSION`` is migrated forward immediately, and a newer
        one raises ``DatabaseFromNewerVersionError`` before any schema statement runs.
        On a failed reopen the connection is left open on the restored file without
        being migrated or schema-checked further; callers should treat the repository
        as unusable until a later ``async_initialize``/``async_restore`` call succeeds.
        """
        async with self._lock:
            source = await self._hass.async_add_executor_job(self._resolve_restore_source, filename)
            if self._conn is not None:
                await self._conn.close()
                self._conn = None
            await self._hass.async_add_executor_job(self._do_restore, source)

        await self.async_initialize()
        return source

    def pre_migration_snapshots(self) -> list[Path]:
        """``pre_migration_v*`` snapshots in backups/, oldest first. Blocking (filesystem
        only, no DB connection) — callers should run this via an executor job.
        """
        return [p for p in _snapshots(self._backups_dir()) if p.name.startswith("pre_migration_v")]

    def _resolve_restore_source(self, filename: str | None) -> Path:
        """Blocking half of a restore: locate and validate the snapshot. Runs in the executor."""
        backups_dir = self._backups_dir()
        if filename is None:
            candidates = _snapshots(backups_dir)
            if not candidates:
                raise FileNotFoundError("No snapshots available to restore")
            return candidates[-1]

        if "/" in filename or "\\" in filename or filename in (".", ".."):
            raise FileNotFoundError(filename)
        source = backups_dir / filename
        if not source.is_file():
            raise FileNotFoundError(filename)
        return source

    def _do_restore(self, source: Path) -> None:
        """Blocking half of a restore: drop stray WAL/SHM, then copy. Runs in the executor.

        Stray ``-wal``/``-shm`` siblings are removed BEFORE the main file is replaced,
        never after: SQLite validates WAL frames against the WAL header's own salt
        values, not against the main file's contents, so a window where a new main file
        coexists with an old WAL/SHM pair risks replaying the old database's frames onto
        the restored file on next open. Removing them first means a crash before the
        copy just leaves the old (still consistent) database in place, and a crash after
        the copy leaves the new database with no stale WAL to conflict with it.
        """
        for suffix in ("-wal", "-shm"):
            stray = self._db_path.with_name(self._db_path.name + suffix)
            if stray.exists():
                stray.unlink()
        shutil.copy2(source, self._db_path)

    async def fetch_inventory(self, inventory_id: str) -> dict[str, Any] | None:
        conn = self._connection()
        cursor = await conn.execute(f"{_INVENTORY_SELECT} WHERE id = ?", (inventory_id,))
        row = await cursor.fetchone()
        await cursor.close()
        return None if row is None else _inventory_from_row(row)

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
        async with self._transaction() as conn:
            await self._execute_upsert_inventory(
                conn, inventory_id, name, description, icon, entry_type, metadata
            )

    @staticmethod
    async def _execute_upsert_inventory(
        conn: aiosqlite.Connection,
        inventory_id: str,
        name: str,
        description: str = "",
        icon: str = "",
        entry_type: str = "",
        metadata: str | None = None,
    ) -> None:
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
        cursor = await conn.execute(f"{_INVENTORY_SELECT} ORDER BY name COLLATE NOCASE")
        rows = await cursor.fetchall()
        await cursor.close()
        return [_inventory_from_row(row) for row in rows]

    async def get_inventory_counts(self, inventory_id: str) -> dict[str, int]:
        """Aggregate counts for one inventory (diagnostics; no item data)."""
        conn = self._connection()
        cursor = await conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM items WHERE inventory_id = :inv) AS items,
                (SELECT COUNT(*) FROM items WHERE inventory_id = :inv AND quantity <= 0)
                    AS items_out_of_stock,
                (SELECT COUNT(*) FROM items WHERE inventory_id = :inv AND auto_add_enabled = 1)
                    AS auto_add_enabled,
                (SELECT COUNT(*) FROM locations WHERE inventory_id = :inv) AS locations,
                (SELECT COUNT(DISTINCT ic.category_id)
                    FROM item_categories ic JOIN items i ON i.id = ic.item_id
                    WHERE i.inventory_id = :inv) AS categories,
                (SELECT COUNT(*) FROM item_barcodes WHERE inventory_id = :inv) AS barcodes,
                (SELECT COUNT(*) FROM item_aliases WHERE inventory_id = :inv) AS aliases,
                (SELECT COUNT(*) FROM consumption_history WHERE inventory_id = :inv)
                    AS history_events
            """,
            {"inv": inventory_id},
        )
        row = await cursor.fetchone()
        await cursor.close()
        assert row is not None
        return {key: int(row[key]) for key in row.keys()}

    async def get_todo_list_references(self, inventory_id: str) -> dict[str, int]:
        """Map each todo list entity id referenced by the inventory's items to its item count."""
        conn = self._connection()
        cursor = await conn.execute(
            """
            SELECT todo_list, COUNT(*) AS item_count
            FROM items
            WHERE inventory_id = ? AND TRIM(COALESCE(todo_list, '')) != ''
            GROUP BY todo_list
            ORDER BY todo_list
            """,
            (inventory_id,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return {str(row["todo_list"]): int(row["item_count"]) for row in rows}

    async def list_orphaned_inventories(self, known_ids: Collection[str]) -> list[dict[str, Any]]:
        """Return inventories whose id is not in *known_ids*, with their item counts."""
        conn = self._connection()
        cursor = await conn.execute("""
            SELECT inv.id, inv.name, COUNT(i.id) AS item_count
            FROM inventories inv
            LEFT JOIN items i ON i.inventory_id = inv.id
            GROUP BY inv.id
            ORDER BY inv.name COLLATE NOCASE
            """)
        rows = await cursor.fetchall()
        await cursor.close()
        return [
            {"id": row["id"], "name": row["name"], "item_count": int(row["item_count"])}
            for row in rows
            if row["id"] not in known_ids
        ]

    async def create_item(self, inventory_id: str, data: dict[str, Any]) -> str:
        """Insert a new item; returns item_id.

        Plain INSERT: a name that already exists in the inventory (case-insensitive)
        raises ``aiosqlite.IntegrityError``. Callers check ``get_item_by_name`` first.
        """
        async with self._transaction() as conn:
            return await self._insert_item(conn, inventory_id, data)

    @staticmethod
    async def _insert_item(
        conn: aiosqlite.Connection, inventory_id: str, data: dict[str, Any]
    ) -> str:
        item_id = data.get("id") or str(uuid.uuid4())
        await conn.execute(
            """
            INSERT INTO items (
                id, inventory_id, name, description, unit, expiry_alert_days,
                auto_add_enabled, auto_add_id_to_description_enabled,
                auto_add_to_list_quantity, desired_quantity, todo_list,
                todo_quantity_placement, price, icon
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id,
                inventory_id,
                data[FIELD_NAME],
                data.get(FIELD_DESCRIPTION, ""),
                data.get(FIELD_UNIT, ""),
                data.get(FIELD_EXPIRY_ALERT_DAYS, 0),
                int(data.get(FIELD_AUTO_ADD_ENABLED, False)),
                int(data.get(FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED, False)),
                round_quantity(data.get(FIELD_AUTO_ADD_TO_LIST_QUANTITY, 0)),
                round_quantity(data.get(FIELD_DESIRED_QUANTITY, 0)),
                data.get(FIELD_TODO_LIST, ""),
                data.get(FIELD_TODO_QUANTITY_PLACEMENT, "name"),
                data.get(FIELD_PRICE, DEFAULT_PRICE),
                data.get(FIELD_ICON, ""),
            ),
        )
        return cast(str, item_id)

    async def update_item(self, item_id: str, data: dict[str, Any]) -> bool:
        """Update an item record; returns True if a row was updated."""
        fields: list[str] = []
        params: list[Any] = []

        for field, column in ITEM_COLUMNS.items():
            if field in data:
                value = data[field]
                if field in _BOOLEAN_FIELDS:
                    value = int(value)
                elif field in _QUANTITY_FIELDS:
                    value = round_quantity(value)
                fields.append(f"{column} = ?")
                params.append(value)

        if not fields:
            return False

        params.append(item_id)
        async with self._transaction() as conn:
            cursor = await conn.execute(
                f"""
                UPDATE items
                SET {', '.join(fields)}, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                tuple(params),
            )
            return cursor.rowcount > 0

    async def list_item_barcodes(self, item_id: str) -> list[str]:
        """The item's barcodes, sorted (the first one is the item's default barcode)."""
        cursor = await self._connection().execute(
            "SELECT barcode FROM item_barcodes WHERE item_id = ? ORDER BY barcode", (item_id,)
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [str(row["barcode"]) for row in rows]

    async def list_item_ids_with_images(self, inventory_id: str | None = None) -> set[str]:
        """Ids of the items that have an image, optionally only those of one inventory."""
        sql = "SELECT id FROM items WHERE image != ''"
        params: tuple[str, ...] = ()
        if inventory_id is not None:
            sql += " AND inventory_id = ?"
            params = (inventory_id,)
        cursor = await self._connection().execute(sql, params)
        rows = await cursor.fetchall()
        await cursor.close()
        return {str(row["id"]) for row in rows}

    async def delete_item(self, item_id: str) -> bool:
        """Delete an item and any related rows."""
        conn = self._connection()
        async with self._lock:
            cursor = await conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
            await conn.commit()
            return cursor.rowcount > 0

    async def list_items_with_details(
        self, inventory_id: str, item_ids: Collection[str] | None = None
    ) -> list[dict[str, Any]]:
        """Return items with locations, categories, barcodes, aliases and batches.

        Each item also carries ``stocked_locations``: distinct locations holding stock.
        *item_ids*, when given, restricts the result to those items.
        """
        conn = self._connection()

        id_filter = ""
        params: tuple[str, ...] = (inventory_id,)
        if item_ids is not None:
            if not item_ids:
                return []
            id_filter = f" AND i.id IN ({', '.join('?' * len(item_ids))})"
            params = (inventory_id, *item_ids)

        cursor = await conn.execute(
            f"SELECT {_ITEM_SELECT} FROM items i WHERE i.inventory_id = ?{id_filter}"
            " ORDER BY LOWER(i.name)",
            params,
        )
        base_rows = await cursor.fetchall()
        await cursor.close()

        items: dict[str, dict[str, Any]] = {}
        for row in base_rows:
            items[row["id"]] = {
                **_item_from_row(row),
                FIELD_CATEGORY: "",
                FIELD_LOCATION: "",
                FIELD_LOCATIONS: [],
                FIELD_CATEGORIES: [],
                FIELD_BARCODES: [],
                FIELD_ALIASES: [],
                FIELD_BATCHES: [],
                FIELD_STOCKED_LOCATIONS: [],
            }

        if not items:
            return []

        cursor = await conn.execute(
            f"""
            SELECT il.item_id, l.name AS location
            FROM item_locations il
            JOIN locations l ON l.id = il.location_id
            JOIN items i ON i.id = il.item_id
            WHERE i.inventory_id = ?{id_filter}
            ORDER BY il.rowid
            """,
            params,
        )
        location_rows = await cursor.fetchall()
        await cursor.close()
        for row in location_rows:
            item = items.get(row["item_id"])
            if item is None:
                continue
            item[FIELD_LOCATIONS].append(row["location"])
            if not item[FIELD_LOCATION]:
                item[FIELD_LOCATION] = row["location"]

        cursor = await conn.execute(
            f"""
            SELECT ic.item_id, c.name AS category
            FROM item_categories ic
            JOIN categories c ON c.id = ic.category_id
            JOIN items i ON i.id = ic.item_id
            WHERE i.inventory_id = ?{id_filter}
            ORDER BY ic.rowid
            """,
            params,
        )
        category_rows = await cursor.fetchall()
        await cursor.close()
        for row in category_rows:
            item = items.get(row["item_id"])
            if item is None:
                continue
            item[FIELD_CATEGORIES].append(row["category"])
            if not item[FIELD_CATEGORY]:
                item[FIELD_CATEGORY] = row["category"]

        cursor = await conn.execute(
            f"""
            SELECT ib.item_id, ib.barcode
            FROM item_barcodes ib
            JOIN items i ON i.id = ib.item_id
            WHERE i.inventory_id = ?{id_filter}
            ORDER BY ib.barcode
            """,
            params,
        )
        barcode_rows = await cursor.fetchall()
        await cursor.close()
        for row in barcode_rows:
            if row["item_id"] in items:
                items[row["item_id"]][FIELD_BARCODES].append(row["barcode"])

        cursor = await conn.execute(
            f"""
            SELECT ia.item_id, ia.alias
            FROM item_aliases ia
            JOIN items i ON i.id = ia.item_id
            WHERE i.inventory_id = ?{id_filter}
            ORDER BY ia.alias
            """,
            params,
        )
        alias_rows = await cursor.fetchall()
        await cursor.close()
        for row in alias_rows:
            if row["item_id"] in items:
                items[row["item_id"]][FIELD_ALIASES].append(row["alias"])

        for batch in await self.list_inventory_batches(inventory_id):
            item = items.get(batch["item_id"])
            if item is None:
                continue
            item[FIELD_BATCHES].append(
                {
                    "id": batch["id"],
                    FIELD_QUANTITY: batch["quantity"],
                    FIELD_EXPIRY_DATE: batch["expiry_date"],
                    FIELD_LOCATION: batch["location"],
                    FIELD_UNIT_PRICE: batch["unit_price"],
                    FIELD_PURCHASED_AT: batch["purchased_at"],
                }
            )
            if batch["location"] and batch["location"] not in item[FIELD_STOCKED_LOCATIONS]:
                item[FIELD_STOCKED_LOCATIONS].append(batch["location"])

        return list(items.values())

    async def search_items(
        self, query: str, inventory_ids: Collection[str], limit: int
    ) -> list[tuple[str, str, int]]:
        """``(inventory_id, item_id, rank)`` of items in *inventory_ids* matching *query*.

        Matching is a casefolded substring test; best rank first. At most *limit* + 1 rows
        are returned so the caller can tell the result was cut.
        """
        if not query or not inventory_ids:
            return []
        params: dict[str, Any] = {"q": query.casefold(), "limit": limit + 1}
        placeholders = []
        for index, inventory_id in enumerate(inventory_ids):
            params[f"inv{index}"] = inventory_id
            placeholders.append(f":inv{index}")
        cursor = await self._connection().execute(
            _SEARCH_SQL.format(placeholders=", ".join(placeholders)), params
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [(row["inventory_id"], row["item_id"], row["rank"]) for row in rows]

    async def get_item_by_name(self, inventory_id: str, name: str) -> dict[str, Any] | None:
        """Retrieve item by inventory and case-insensitive name."""
        return await self._fetch_item(
            "WHERE i.inventory_id = ? AND i.name = ?", (inventory_id, name)
        )

    async def get_item_by_id(self, item_id: str) -> dict[str, Any] | None:
        """Retrieve item by its id."""
        return await self._fetch_item("WHERE i.id = ?", (item_id,))

    async def _fetch_item(self, clauses: str, params: Sequence[Any]) -> dict[str, Any] | None:
        """One item by the joins/WHERE in *clauses* (on ``items i``), or None."""
        cursor = await self._connection().execute(
            f"SELECT {_ITEM_SELECT} FROM items i {clauses}", params
        )
        row = await cursor.fetchone()
        await cursor.close()
        return _item_from_row(row) if row else None

    async def ensure_location(self, inventory_id: str, name: str) -> int:
        """Fetch or create a location for an inventory (existing casing is kept)."""
        async with self._transaction() as conn:
            return await self._ensure_location_row(conn, inventory_id, name)

    async def find_location_id(self, inventory_id: str, name: str) -> int | None:
        """Id of an existing location (case-insensitive), or None."""
        cursor = await self._connection().execute(
            "SELECT id FROM locations WHERE inventory_id = ? AND name = ?", (inventory_id, name)
        )
        row = await cursor.fetchone()
        await cursor.close()
        return int(row["id"]) if row else None

    async def list_location_names(self, inventory_id: str) -> list[str]:
        """Stored names of every location in an inventory, sorted case-insensitively."""
        cursor = await self._connection().execute(
            "SELECT name FROM locations WHERE inventory_id = ? ORDER BY name", (inventory_id,)
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [str(row["name"]) for row in rows]

    async def first_item_location_id(self, item_id: str) -> int | None:
        """The item's first usual location (insertion order), or None."""
        cursor = await self._connection().execute(
            "SELECT location_id FROM item_locations WHERE item_id = ? ORDER BY rowid LIMIT 1",
            (item_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        return int(row["location_id"]) if row else None

    async def has_stock_at_location(self, item_id: str, location_id: int) -> bool:
        """Whether the item has a batch with stock at the location."""
        cursor = await self._connection().execute(
            "SELECT 1 FROM item_batches WHERE item_id = ? AND location_id = ? AND quantity > 0"
            " LIMIT 1",
            (item_id, location_id),
        )
        row = await cursor.fetchone()
        await cursor.close()
        return row is not None

    @staticmethod
    async def _ensure_location_row(conn: aiosqlite.Connection, inventory_id: str, name: str) -> int:
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
        if row is None:
            raise RuntimeError("Failed to ensure location; no row returned")
        return cast(int, row["id"])

    async def set_item_locations(
        self,
        item_id: str,
        location_ids: Sequence[int],
    ) -> None:
        """Replace all location entries for an item (atomic; order is preserved)."""
        async with self._transaction() as conn:
            await self._replace_item_locations(conn, item_id, location_ids)

    @staticmethod
    async def _replace_item_locations(
        conn: aiosqlite.Connection, item_id: str, location_ids: Sequence[int]
    ) -> None:
        await conn.execute("DELETE FROM item_locations WHERE item_id = ?", (item_id,))
        if location_ids:
            await conn.executemany(
                "INSERT INTO item_locations (item_id, location_id) VALUES (?, ?)",
                [(item_id, loc_id) for loc_id in location_ids],
            )

    async def ensure_category(self, name: str) -> int:
        """Fetch or create a category (existing casing is kept)."""
        async with self._transaction() as conn:
            return await self._ensure_category_row(conn, name)

    @staticmethod
    async def _ensure_category_row(conn: aiosqlite.Connection, name: str) -> int:
        cursor = await conn.execute(
            """
            INSERT INTO categories (name)
            VALUES (?)
            ON CONFLICT(name) DO UPDATE SET
                name = categories.name
            RETURNING id
            """,
            (name,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            raise RuntimeError("Failed to ensure category; no row returned")
        return cast(int, row["id"])

    async def set_item_categories(self, item_id: str, category_ids: Sequence[int]) -> None:
        """Replace category associations for an item (atomic; order is preserved)."""
        async with self._transaction() as conn:
            await self._replace_item_categories(conn, item_id, category_ids)

    @staticmethod
    async def _replace_item_categories(
        conn: aiosqlite.Connection, item_id: str, category_ids: Sequence[int]
    ) -> None:
        await conn.execute("DELETE FROM item_categories WHERE item_id = ?", (item_id,))
        if category_ids:
            await conn.executemany(
                "INSERT INTO item_categories (item_id, category_id) VALUES (?, ?)",
                [(item_id, category_id) for category_id in category_ids],
            )

    async def find_relation_conflicts(
        self, inventory_id: str, item_id: str, barcodes: list[str], aliases: list[str]
    ) -> tuple[list[str], list[str]]:
        """Return the barcodes and aliases already owned by *other* items in the inventory.

        Matches exactly, mirroring the ``idx_item_barcodes_unique`` / ``idx_item_aliases_unique``
        constraints, so callers can reject an edit before writing anything.
        """
        conn = self._connection()
        taken: dict[str, list[str]] = {"item_barcodes": [], "item_aliases": []}
        for table, column, values in (
            ("item_barcodes", "barcode", barcodes),
            ("item_aliases", "alias", aliases),
        ):
            if not values:
                continue
            placeholders = ", ".join("?" * len(values))
            cursor = await conn.execute(
                f"SELECT {column} FROM {table} "  # noqa: S608 - internal constants only
                f"WHERE inventory_id = ? AND item_id != ? AND {column} IN ({placeholders})",
                (inventory_id, item_id, *values),
            )
            taken[table] = [row[column] for row in await cursor.fetchall()]
            await cursor.close()
        return taken["item_barcodes"], taken["item_aliases"]

    async def list_item_identifiers(self, inventory_id: str) -> list[tuple[str, str, str | None]]:
        """``(item_id, name, alias)`` for every item of the inventory and each of its aliases.

        An item without aliases appears once, with alias ``None``.
        """
        cursor = await self._connection().execute(
            """
            SELECT i.id AS item_id, i.name AS name, a.alias AS alias
            FROM items i
            LEFT JOIN item_aliases a ON a.item_id = i.id
            WHERE i.inventory_id = ?
            """,
            (inventory_id,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [(row["item_id"], row["name"], row["alias"]) for row in rows]

    async def get_item_by_barcode(self, inventory_id: str, barcode: str) -> dict[str, Any] | None:
        """Retrieve an item by barcode within an inventory."""
        return await self._fetch_item(
            "JOIN item_barcodes ib ON ib.item_id = i.id"
            " WHERE ib.inventory_id = ? AND ib.barcode = ?",
            (inventory_id, barcode),
        )

    async def get_item_by_barcode_global(self, barcode: str) -> list[dict[str, Any]]:
        """Cross-inventory barcode lookup. Returns all items matching the barcode."""
        conn = self._connection()
        cursor = await conn.execute(
            f"""
            SELECT {_ITEM_SELECT}, inv.name AS inventory_name
            FROM items i
            JOIN item_barcodes ib ON ib.item_id = i.id
            JOIN inventories inv ON inv.id = i.inventory_id
            WHERE ib.barcode = ?
            """,
            (barcode,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [_item_from_row(row, "inventory_name") for row in rows]

    async def set_item_barcodes(self, item_id: str, inventory_id: str, barcodes: list[str]) -> None:
        """Replace all barcodes for an item (atomic: a conflict leaves the old set intact)."""
        async with self._transaction() as conn:
            await conn.execute("DELETE FROM item_barcodes WHERE item_id = ?", (item_id,))
            if barcodes:
                await conn.executemany(
                    """
                    INSERT INTO item_barcodes (item_id, inventory_id, barcode)
                    VALUES (?, ?, ?)
                    """,
                    [(item_id, inventory_id, bc) for bc in barcodes],
                )

    async def set_item_aliases(self, item_id: str, inventory_id: str, aliases: list[str]) -> None:
        """Replace all aliases for an item (atomic: a conflict leaves the old set intact)."""
        async with self._transaction() as conn:
            await conn.execute("DELETE FROM item_aliases WHERE item_id = ?", (item_id,))
            if aliases:
                await conn.executemany(
                    """
                    INSERT INTO item_aliases (item_id, inventory_id, alias)
                    VALUES (?, ?, ?)
                    """,
                    [(item_id, inventory_id, alias) for alias in aliases],
                )

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
        batch_id: str = "",
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
                    location_from, location_to, timestamp, metadata, price, batch_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    batch_id,
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
            if len(end_date) == 10:
                # Date-only bound (YYYY-MM-DD): include every event on that day.
                next_day = date.fromisoformat(end_date) + timedelta(days=1)
                conditions.append("ch.timestamp < ?")
                params.append(next_day.isoformat())
            else:
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
                   ch.timestamp, ch.metadata, i.name AS item_name, ch.price, ch.batch_id
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
                "id": row["id"],
                "item_id": row["item_id"],
                "inventory_id": row["inventory_id"],
                "event_type": row["event_type"],
                "amount": float(row["amount"]),
                "quantity_before": float(row["quantity_before"]),
                "quantity_after": float(row["quantity_after"]),
                "source": row["source"],
                "location_from": row["location_from"],
                "location_to": row["location_to"],
                "timestamp": row["timestamp"],
                "metadata": row["metadata"],
                "item_name": row["item_name"] or "",
                FIELD_PRICE: float(row["price"]) if row["price"] else 0,
                "batch_id": row["batch_id"],
            }
            for row in rows
        ]

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
                       SUM(CASE WHEN price > 0 THEN 1 ELSE 0 END) AS priced_count,
                       MIN(CASE WHEN price > 0 THEN timestamp END) AS first_priced_ts
                FROM consumption_history
                WHERE item_id = ? AND event_type IN ('increment', 'add')
                  AND (? = '' OR timestamp >= ?)
            )
            SELECT d.cnt AS decrement_count, d.total AS total_consumed,
                   d.first_ts AS first_event_ts, d.last_ts AS last_event_ts,
                   (SELECT COUNT(*) FROM restocks) AS restock_count,
                   (SELECT GROUP_CONCAT(timestamp, '|') FROM restocks) AS restock_timestamps,
                   s.total_spend, s.priced_count AS restock_spend_count,
                   s.first_priced_ts AS first_spend_ts
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
                "first_spend_ts": None,
            }

        return {
            "item_id": item_id,
            "window_days": window_days,
            "window_start": window_start,
            **_consumption_from_row(row),
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
                       GROUP_CONCAT(timestamp, '|') AS timestamps,
                       COALESCE(SUM(price * amount), 0) AS total_spend,
                       SUM(CASE WHEN price > 0 THEN 1 ELSE 0 END) AS priced_count,
                       MIN(CASE WHEN price > 0 THEN timestamp END) AS first_priced_ts
                FROM consumption_history
                WHERE inventory_id = ? AND event_type IN ('increment', 'add')
                  AND (? = '' OR timestamp >= ?)
                GROUP BY item_id
            )
            SELECT i.id AS item_id, i.name AS item_name, i.quantity, i.unit,
                   COALESCE(c.cnt, 0) AS decrement_count, COALESCE(c.total, 0) AS total_consumed,
                   c.first_ts AS first_event_ts, c.last_ts AS last_event_ts,
                   COALESCE(r.cnt, 0) AS restock_count, r.timestamps AS restock_timestamps,
                   COALESCE(r.total_spend, 0) AS total_spend,
                   COALESCE(r.priced_count, 0) AS restock_spend_count,
                   r.first_priced_ts AS first_spend_ts
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

        return [
            {
                "item_id": row["item_id"],
                "item_name": row["item_name"],
                "current_quantity": float(row["quantity"]),
                "unit": row["unit"] or "",
                "window_days": window_days,
                "window_start": window_start,
                **_consumption_from_row(row),
            }
            for row in rows
        ]
