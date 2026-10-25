"""Protocol defining the coordinator interface expected by mixins."""

from __future__ import annotations

from typing import Any, Protocol

from homeassistant.core import HomeAssistant

from ..hub import InventoryHub
from ..storage._batches import StockChange
from ..storage.images import ImageStore
from ..storage.repository import InventoryRepository
from ._identifiers import ItemIdentifiers


class _CoordinatorProtocol(Protocol):
    """Structural type describing the attributes/methods mixins depend on."""

    hass: HomeAssistant
    repository: InventoryRepository
    images: ImageStore
    hub: InventoryHub

    async def async_initialize(self) -> None:
        pass

    async def async_list_items(self, inventory_id: str) -> list[dict[str, Any]]:
        pass

    async def _apply_barcode_updates(
        self, inventory_id: str, item_id: str, barcode_str: str
    ) -> None:
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

    async def _apply_alias_updates(
        self,
        inventory_id: str,
        item_id: str,
        aliases_str: str,
    ) -> None:
        pass

    async def _raise_on_name_alias_clashes(
        self,
        inventory_id: str,
        item_id: str,
        name: str | None,
        aliases_str: str | None,
        identifiers: ItemIdentifiers | None = None,
    ) -> None:
        pass

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
        pass

    async def _after_change(self, inventory_id: str) -> None:
        pass

    async def _resolve_item_name(
        self, inventory_id: str, name: str | None, barcode: str | None
    ) -> str:
        pass

    def _process_field_value(self, field: str, value: Any) -> Any:
        pass

    def _process_description_update(
        self,
        description: str | None,
        inventory_id: str,
        auto_add_id_enabled: bool,
    ) -> str:
        pass

    def _validate_auto_add_config(
        self,
        item_name: str,
        inventory_id: str,
        auto_add_enabled: bool,
        auto_add_quantity: float | None,
        todo_list: str | None,
    ) -> bool:
        pass
