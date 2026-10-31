"""Batch storage: the only write path for stock (and the derived item totals)."""

from __future__ import annotations

import contextlib
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

import aiosqlite

from ..const import QUANTITY_PRECISION, round_quantity

# D3: soonest expiry first, then oldest purchase; batches without expiry last.
_CONSUME_ORDER = "ORDER BY b.expiry_date = '', b.expiry_date, b.purchased_at, b.created_at, b.id"
# Derived items columns, correlated on the outer ``items`` row.
_DERIVED_QUANTITY = (
    "ROUND(COALESCE((SELECT SUM(b.quantity) FROM item_batches b WHERE b.item_id = items.id), 0),"
    f" {QUANTITY_PRECISION})"
)
_DERIVED_EXPIRY = (
    "COALESCE((SELECT MIN(b.expiry_date) FROM item_batches b"
    " WHERE b.item_id = items.id AND b.expiry_date != ''), '')"
)

_BATCH_SELECT = """
    SELECT b.id, b.item_id, b.inventory_id, b.quantity, b.expiry_date,
           b.location_id, COALESCE(l.name, '') AS location, b.unit_price, b.purchased_at
    FROM item_batches b
    LEFT JOIN locations l ON l.id = b.location_id
"""

_UPDATABLE_BATCH_COLUMNS = ("quantity", "expiry_date", "location_id", "unit_price", "purchased_at")


@dataclass(frozen=True)
class BatchChange:
    """One batch's quantity change within a stock operation."""

    batch_id: str
    location: str
    quantity_before: float
    quantity_after: float
    unit_price: float


@dataclass(frozen=True)
class StockChange:
    """Item totals before/after a stock operation and the batches it touched."""

    item_id: str
    item_before: float
    item_after: float
    batches: tuple[BatchChange, ...]


class InsufficientStockError(Exception):
    """A transfer asked for more than its source holds; nothing was written."""

    def __init__(self, available: float) -> None:
        super().__init__(f"Only {available} available to move")
        self.available = available


@dataclass(frozen=True)
class BatchMove:
    """Stock a transfer took from one source batch."""

    batch_id: str
    location_from: str
    moved: float
    destination_batch_id: str
    unit_price: float


@dataclass(frozen=True)
class TransferChange:
    """A transfer's result: the (unchanged) item total, the destination, each source move."""

    item_id: str
    item_total: float
    location_to: str
    moves: tuple[BatchMove, ...]


class _RepositoryProtocol(Protocol):
    def _connection(self) -> aiosqlite.Connection:
        """Open connection (provided by InventoryRepository)."""

    def _transaction(self) -> contextlib.AbstractAsyncContextManager[aiosqlite.Connection]:
        """Locked commit/rollback unit of work (provided by InventoryRepository)."""


# ``_BATCH_SELECT`` columns, in select order (``_batch_row`` maps by position).
_BATCH_KEYS = (
    "id",
    "item_id",
    "inventory_id",
    "quantity",
    "expiry_date",
    "location_id",
    "location",
    "unit_price",
    "purchased_at",
)


def _batch_row(row: aiosqlite.Row) -> dict[str, Any]:
    batch = dict(zip(_BATCH_KEYS, row, strict=True))
    batch["quantity"] = round_quantity(batch["quantity"])
    return batch


def _transfer_source_filter(
    item_id: str, to_location_id: int | None, from_location_id: int | None, batch_id: str | None
) -> tuple[str, tuple[Any, ...]]:
    """T2 sources: one batch; else one location's batches; else all not at the destination.

    ``to_location_id`` None means the destination does not exist yet, so nothing is there.
    """
    if batch_id is not None:
        return "WHERE b.item_id = ? AND b.id = ?", (item_id, batch_id)
    if from_location_id is not None:
        return "WHERE b.item_id = ? AND b.location_id = ?", (item_id, from_location_id)
    if to_location_id is not None:
        return "WHERE b.item_id = ? AND b.location_id IS NOT ?", (item_id, to_location_id)
    return "WHERE b.item_id = ?", (item_id,)


class _BatchRepositoryMixin(_RepositoryProtocol):
    """Batch reads/writes. Every write refreshes items.quantity/expiry_date in-transaction."""

    async def list_batches(self, item_id: str) -> list[dict[str, Any]]:
        cursor = await self._connection().execute(
            f"{_BATCH_SELECT} WHERE b.item_id = ? {_CONSUME_ORDER}", (item_id,)
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [_batch_row(row) for row in rows]

    async def list_inventory_batches(self, inventory_id: str) -> list[dict[str, Any]]:
        cursor = await self._connection().execute(
            f"{_BATCH_SELECT} WHERE b.inventory_id = ? {_CONSUME_ORDER}", (inventory_id,)
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [_batch_row(row) for row in rows]

    async def get_batch(self, batch_id: str) -> dict[str, Any] | None:
        cursor = await self._connection().execute(f"{_BATCH_SELECT} WHERE b.id = ?", (batch_id,))
        row = await cursor.fetchone()
        await cursor.close()
        return _batch_row(row) if row else None

    async def add_stock(
        self,
        item_id: str,
        inventory_id: str,
        quantity: float,
        *,
        expiry_date: str = "",
        location_id: int | None = None,
        unit_price: float = 0.0,
        purchased_at: str,
    ) -> StockChange:
        """Add stock, topping up the batch with equal expiry/location/price (D4).

        A quantity that rounds to 0 is a no-op (no batch written); a negative quantity
        raises ``ValueError`` — consumption goes through ``consume_stock``.
        """
        quantity = round_quantity(quantity)
        if quantity < 0:
            raise ValueError("add_stock quantity must be positive")
        if quantity == 0:
            before = await self._item_total(self._connection(), item_id)
            return StockChange(item_id, before, before, ())
        async with self._transaction() as conn:
            before = await self._item_total(conn, item_id)
            cursor = await conn.execute(
                f"{_BATCH_SELECT} WHERE b.item_id = ? AND b.expiry_date = ?"
                " AND b.location_id IS ? AND b.unit_price = ? LIMIT 1",
                (item_id, expiry_date, location_id, unit_price),
            )
            row = await cursor.fetchone()
            await cursor.close()
            if row:
                existing = _batch_row(row)
                new_quantity = round_quantity(existing["quantity"] + quantity)
                await conn.execute(
                    "UPDATE item_batches SET quantity = ?, purchased_at = MIN(purchased_at, ?),"
                    " updated_at = datetime('now') WHERE id = ?",
                    (new_quantity, purchased_at, existing["id"]),
                )
                touched = BatchChange(
                    existing["id"],
                    existing["location"],
                    existing["quantity"],
                    new_quantity,
                    unit_price,
                )
            else:
                batch_id = await self._insert_batch(
                    conn,
                    item_id,
                    inventory_id,
                    quantity,
                    expiry_date,
                    location_id,
                    unit_price,
                    purchased_at,
                )
                touched = BatchChange(
                    batch_id,
                    await self._location_name(conn, location_id),
                    0.0,
                    quantity,
                    unit_price,
                )
            after = await self._refresh_item_totals(conn, item_id)
        return StockChange(item_id, before, after, (touched,))

    async def consume_stock(
        self,
        item_id: str,
        quantity: float,
        *,
        location_id: int | None = None,
        batch_id: str | None = None,
    ) -> StockChange:
        """Consume up to *quantity* in D3 order (optionally one location/batch); D7 deletes empties."""
        remaining = round_quantity(quantity)
        where = "WHERE b.item_id = ?"
        params: list[Any] = [item_id]
        if batch_id is not None:
            where += " AND b.id = ?"
            params.append(batch_id)
        elif location_id is not None:
            where += " AND b.location_id = ?"
            params.append(location_id)

        touched: list[BatchChange] = []
        async with self._transaction() as conn:
            before = await self._item_total(conn, item_id)
            cursor = await conn.execute(f"{_BATCH_SELECT} {where} {_CONSUME_ORDER}", tuple(params))
            rows = await cursor.fetchall()
            await cursor.close()
            for row in rows:
                if remaining <= 0:
                    break
                batch = _batch_row(row)
                take = min(batch["quantity"], remaining)
                left = round_quantity(batch["quantity"] - take)
                remaining = round_quantity(remaining - take)
                if left <= 0:
                    await conn.execute("DELETE FROM item_batches WHERE id = ?", (batch["id"],))
                else:
                    await conn.execute(
                        "UPDATE item_batches SET quantity = ?, updated_at = datetime('now')"
                        " WHERE id = ?",
                        (left, batch["id"]),
                    )
                touched.append(
                    BatchChange(
                        batch["id"], batch["location"], batch["quantity"], left, batch["unit_price"]
                    )
                )
            after = await self._refresh_item_totals(conn, item_id)
        return StockChange(item_id, before, after, tuple(touched))

    async def update_batch(self, batch_id: str, fields: dict[str, Any]) -> StockChange | None:
        """Update batch columns; quantity <= 0 deletes the batch (D7). None if unknown."""
        unknown = set(fields) - set(_UPDATABLE_BATCH_COLUMNS)
        if unknown:
            raise ValueError(f"Unknown batch fields: {sorted(unknown)}")
        async with self._transaction() as conn:
            cursor = await conn.execute(f"{_BATCH_SELECT} WHERE b.id = ?", (batch_id,))
            row = await cursor.fetchone()
            await cursor.close()
            if row is None:
                return None
            batch = _batch_row(row)
            before = await self._item_total(conn, batch["item_id"])
            new_quantity = round_quantity(fields.get("quantity", batch["quantity"]))
            if new_quantity <= 0:
                await conn.execute("DELETE FROM item_batches WHERE id = ?", (batch_id,))
                new_quantity = 0.0
            elif fields:
                assignments = ", ".join(f"{column} = ?" for column in fields)
                values = [
                    round_quantity(value) if column == "quantity" else value
                    for column, value in fields.items()
                ]
                await conn.execute(
                    f"UPDATE item_batches SET {assignments}, updated_at = datetime('now')"  # noqa: S608
                    " WHERE id = ?",
                    (*values, batch_id),
                )
            after = await self._refresh_item_totals(conn, batch["item_id"])
            location = await self._location_name(
                conn, fields.get("location_id", batch["location_id"])
            )
        change = BatchChange(
            batch_id,
            location,
            batch["quantity"],
            new_quantity,
            float(fields.get("unit_price", batch["unit_price"])),
        )
        return StockChange(batch["item_id"], before, after, (change,))

    async def delete_batch(self, batch_id: str) -> StockChange | None:
        return await self.update_batch(batch_id, {"quantity": 0})

    async def list_transfer_sources(
        self,
        item_id: str,
        *,
        to_location_id: int | None,
        from_location_id: int | None = None,
        batch_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Batches a transfer would take from (T2), in D3 order. Read-only."""
        where, params = _transfer_source_filter(item_id, to_location_id, from_location_id, batch_id)
        cursor = await self._connection().execute(
            f"{_BATCH_SELECT} {where} {_CONSUME_ORDER}", params
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [_batch_row(row) for row in rows]

    async def transfer_stock(
        self,
        item_id: str,
        inventory_id: str,
        quantity: float | None,
        *,
        to_location_id: int,
        from_location_id: int | None = None,
        batch_id: str | None = None,
    ) -> TransferChange:
        """Move *quantity* (None = everything) from the T2 sources to *to_location_id*.

        One transaction: moved stock keeps expiry, unit price and purchase date and merges
        by D4 at the destination (earliest purchase date kept); emptied sources are deleted
        (D7); the destination is appended to the item's usual locations. Raises
        ``InsufficientStockError`` (nothing written) when the sources hold less, and
        ``ValueError`` for a non-positive *quantity* or when there are no sources.
        """
        if quantity is not None and round_quantity(quantity) <= 0:
            raise ValueError(f"transfer quantity must be positive, got {quantity}")
        where, params = _transfer_source_filter(item_id, to_location_id, from_location_id, batch_id)
        moves: list[BatchMove] = []
        async with self._transaction() as conn:
            cursor = await conn.execute(f"{_BATCH_SELECT} {where} {_CONSUME_ORDER}", params)
            sources = [_batch_row(row) for row in await cursor.fetchall()]
            await cursor.close()
            available = round_quantity(sum(batch["quantity"] for batch in sources))
            remaining = available if quantity is None else round_quantity(quantity)
            if not sources:
                raise ValueError("no stock to transfer")
            if remaining > available:
                raise InsufficientStockError(available)
            for batch in sources:
                if remaining <= 0:
                    break
                take = min(batch["quantity"], remaining)
                remaining = round_quantity(remaining - take)
                destination_id = await self._move_batch_stock(
                    conn, inventory_id, batch, take, to_location_id
                )
                moves.append(
                    BatchMove(
                        batch["id"], batch["location"], take, destination_id, batch["unit_price"]
                    )
                )
            if moves:
                # T4: appended after the existing rows, so the first usual location stays first.
                await conn.execute(
                    "INSERT OR IGNORE INTO item_locations (item_id, location_id) VALUES (?, ?)",
                    (item_id, to_location_id),
                )
            total = await self._refresh_item_totals(conn, item_id)
            location_to = await self._location_name(conn, to_location_id)
        return TransferChange(item_id, total, location_to, tuple(moves))

    @staticmethod
    async def _move_batch_stock(
        conn: aiosqlite.Connection,
        inventory_id: str,
        batch: dict[str, Any],
        quantity: float,
        to_location_id: int,
    ) -> str:
        """Move *quantity* of *batch* to the destination; returns the destination batch id."""
        left = round_quantity(batch["quantity"] - quantity)
        cursor = await conn.execute(
            "SELECT id, quantity FROM item_batches WHERE item_id = ? AND expiry_date = ?"
            " AND location_id = ? AND unit_price = ? AND id != ? LIMIT 1",
            (
                batch["item_id"],
                batch["expiry_date"],
                to_location_id,
                batch["unit_price"],
                batch["id"],
            ),
        )
        target = await cursor.fetchone()
        await cursor.close()
        if target is None and left <= 0:
            # The whole batch moves and nothing there matches it: relocate it in place.
            await conn.execute(
                "UPDATE item_batches SET location_id = ?, updated_at = datetime('now') WHERE id = ?",
                (to_location_id, batch["id"]),
            )
            return str(batch["id"])
        if target is None:
            destination_id = await _BatchRepositoryMixin._insert_batch(
                conn,
                batch["item_id"],
                inventory_id,
                quantity,
                batch["expiry_date"],
                to_location_id,
                batch["unit_price"],
                batch["purchased_at"],
            )
        else:
            destination_id = str(target["id"])
            await conn.execute(
                "UPDATE item_batches SET quantity = ?, purchased_at = MIN(purchased_at, ?),"
                " updated_at = datetime('now') WHERE id = ?",
                (
                    round_quantity(target["quantity"] + quantity),
                    batch["purchased_at"],
                    destination_id,
                ),
            )
        if left <= 0:
            await conn.execute("DELETE FROM item_batches WHERE id = ?", (batch["id"],))
        else:
            await conn.execute(
                "UPDATE item_batches SET quantity = ?, updated_at = datetime('now') WHERE id = ?",
                (left, batch["id"]),
            )
        return destination_id

    @staticmethod
    async def _insert_batch(
        conn: aiosqlite.Connection,
        item_id: str,
        inventory_id: str,
        quantity: float,
        expiry_date: str,
        location_id: int | None,
        unit_price: float,
        purchased_at: str,
    ) -> str:
        batch_id = str(uuid.uuid4())
        await conn.execute(
            """
            INSERT INTO item_batches (
                id, item_id, inventory_id, quantity, expiry_date, location_id,
                unit_price, purchased_at, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            """,
            (
                batch_id,
                item_id,
                inventory_id,
                round_quantity(quantity),
                expiry_date,
                location_id,
                unit_price,
                purchased_at,
            ),
        )
        return batch_id

    @staticmethod
    async def _refresh_item_totals(conn: aiosqlite.Connection, item_id: str) -> float:
        """Recompute derived items.quantity / items.expiry_date; returns the new quantity."""
        await conn.execute(
            f"UPDATE items SET quantity = {_DERIVED_QUANTITY}, expiry_date = {_DERIVED_EXPIRY},"
            " updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (item_id,),
        )
        return await _BatchRepositoryMixin._item_total(conn, item_id)

    @staticmethod
    async def _refresh_all_item_totals(conn: aiosqlite.Connection) -> None:
        """Set-based _refresh_item_totals for every item whose derived columns are stale."""
        await conn.execute(f"""
            UPDATE items SET quantity = {_DERIVED_QUANTITY}, expiry_date = {_DERIVED_EXPIRY},
                updated_at = CURRENT_TIMESTAMP
            WHERE quantity IS NOT {_DERIVED_QUANTITY} OR expiry_date IS NOT {_DERIVED_EXPIRY}
            """)

    @staticmethod
    async def _item_total(conn: aiosqlite.Connection, item_id: str) -> float:
        cursor = await conn.execute("SELECT quantity FROM items WHERE id = ?", (item_id,))
        row = await cursor.fetchone()
        await cursor.close()
        return round_quantity(row["quantity"]) if row else 0.0

    @staticmethod
    async def _location_name(conn: aiosqlite.Connection, location_id: int | None) -> str:
        if location_id is None:
            return ""
        cursor = await conn.execute("SELECT name FROM locations WHERE id = ?", (location_id,))
        row = await cursor.fetchone()
        await cursor.close()
        return str(row["name"]) if row else ""
