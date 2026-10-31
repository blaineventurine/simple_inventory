"""Short-lived cache of ``InventoryHub.async_items_expiring_soon`` results."""

from __future__ import annotations

import logging
from time import monotonic
from typing import Any

_LOGGER = logging.getLogger(__name__)


class ExpiryCache:
    """Expiry entries per inventory id (``None`` = all inventories), kept for ``TTL`` seconds.

    Lets the sensors refreshing in one update cycle share a single database scan.
    Entries are copied in and out, so a caller decorating its result never changes
    what another caller receives.
    """

    TTL = 2.0  # seconds

    def __init__(self) -> None:
        self._entries: dict[str | None, tuple[float, list[dict[str, Any]]]] = {}

    def get(self, inventory_id: str | None) -> list[dict[str, Any]] | None:
        """Copies of the cached entries, or None on a miss or after the TTL."""
        cached = self._entries.get(inventory_id)
        if cached is None:
            _LOGGER.debug("Expiry cache MISS for %s", inventory_id)
            return None
        stored_at, entries = cached
        age = monotonic() - stored_at
        if age >= self.TTL:
            _LOGGER.debug("Expiry cache EXPIRED for %s (age=%.3fs)", inventory_id, age)
            return None
        _LOGGER.debug(
            "Expiry cache HIT for %s (age=%.3fs, %d entries)", inventory_id, age, len(entries)
        )
        return [dict(entry) for entry in entries]

    def put(self, inventory_id: str | None, entries: list[dict[str, Any]]) -> None:
        self._entries[inventory_id] = (monotonic(), [dict(entry) for entry in entries])

    def invalidate(self, inventory_id: str | None) -> None:
        self._entries.pop(inventory_id, None)
