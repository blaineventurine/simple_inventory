"""Item photo services (spec 2026-10-26, I7/I8): product photo, media file, clear."""

from __future__ import annotations

from typing import Any

from homeassistant.core import ServiceCall

from ..const import FIELD_BARCODE, FIELD_NAME
from ..coordinator import SimpleInventoryCoordinator
from .base_service import BaseServiceHandler
from .resolvers import resolve_item_name


class ImageService(BaseServiceHandler):
    """Handlers for set_item_image_from_barcode, set_item_image_from_media, clear_item_image."""

    async def async_set_item_image_from_barcode(self, call: ServiceCall) -> None:
        coordinator, inventory_id, item = await self._item_for_call(call)
        await coordinator.async_set_item_image_from_barcode(
            inventory_id, item["id"], call.data.get("lookup_barcode")
        )

    async def async_set_item_image_from_media(self, call: ServiceCall) -> None:
        coordinator, inventory_id, item = await self._item_for_call(call)
        await coordinator.async_set_item_image_from_media(
            inventory_id, item["id"], call.data["media_content_id"]
        )

    async def async_clear_item_image(self, call: ServiceCall) -> None:
        coordinator, inventory_id, item = await self._item_for_call(call)
        await coordinator.async_clear_item_image(inventory_id, item["id"])

    async def _item_for_call(
        self, call: ServiceCall
    ) -> tuple[SimpleInventoryCoordinator, str, dict[str, Any]]:
        """Resolve the call's inventory and item (exact name/alias, or barcode)."""
        coordinator, inventory_id = await self._coordinator_for_call(call)
        name = call.data.get(FIELD_NAME)
        if name:
            name = await resolve_item_name(coordinator, inventory_id, name, fuzzy=False)
        item = await coordinator.async_resolve_item(
            inventory_id, name, call.data.get(FIELD_BARCODE)
        )
        return coordinator, inventory_id, item
