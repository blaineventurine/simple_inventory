"""Protocol defining the coordinator interface expected by mixins."""

from __future__ import annotations

from typing import Any, Protocol

from ..storage.repository import InventoryRepository


class _CoordinatorProtocol(Protocol):
    """Structural type describing the attributes/methods mixins depend on."""

    repository: InventoryRepository

    async def async_initialize(self) -> None:
        pass

    async def async_list_items(self, inventory_id: str) -> list[dict[str, Any]]:
        pass

    async def _apply_location_updates(
        self,
        inventory_id: str,
        item_id: str,
        location_name: str,
    ) -> None:
        pass

    async def _apply_category_updates(self, item_id: str, category_name: str) -> None:
        pass

    async def _after_change(self, inventory_id: str) -> None:
        pass
