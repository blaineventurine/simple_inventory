"""Service handlers for Simple Inventory integration."""

import logging
from typing import cast

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util.json import JsonObjectType

from ..const import (
    DOMAIN,
    FIELD_AMOUNT,
    FIELD_BARCODE,
    FIELD_CATEGORY,
    FIELD_DESCRIPTION,
    FIELD_ITEMS,
    FIELD_NAME,
    FIELD_PRICE,
    FIELD_UNIT,
)
from ..data import get_coordinators, get_hub
from ..entries import inventory_display_name
from ..providers.base import ProductInfo, ProviderResult
from ..providers.lookup import async_lookup_barcode_all_providers
from ..todo_manager import TodoManager
from .backup_service import BackupService
from .image_service import ImageService
from .inventory_service import InventoryService
from .quantity_service import SCAN_BATCH_KEYS, QuantityService
from .resolvers import inventory_not_loaded_error

_LOGGER = logging.getLogger(__name__)


class ServiceHandler:
    """Main service handler that coordinates specialized service handlers."""

    def __init__(
        self,
        hass: HomeAssistant,
        todo_manager: TodoManager,
    ):
        """Initialize the main service handler."""
        self.hass = hass
        self.todo_manager = todo_manager
        self.inventory_service = InventoryService(hass, todo_manager)
        self.quantity_service = QuantityService(hass, todo_manager)
        self.image_service = ImageService(hass)
        self.backup_service = BackupService(hass)

    async def async_add_item(self, call: ServiceCall) -> None:
        """Add an item to the inventory."""
        await self.inventory_service.async_add_item(call)

    async def async_remove_item(self, call: ServiceCall) -> None:
        """Remove an item from the inventory."""
        await self.inventory_service.async_remove_item(call)

    async def async_update_item(self, call: ServiceCall) -> None:
        """Update an existing item with new values."""
        await self.inventory_service.async_update_item(call)

    async def async_increment_item(self, call: ServiceCall) -> None:
        """Increment item quantity."""
        await self.quantity_service.async_increment_item(call)

    async def async_decrement_item(self, call: ServiceCall) -> None:
        """Decrement item quantity."""
        await self.quantity_service.async_decrement_item(call)

    async def async_update_batch(self, call: ServiceCall) -> None:
        """Edit one batch."""
        await self.inventory_service.async_update_batch(call)

    async def async_remove_batch(self, call: ServiceCall) -> None:
        """Delete one batch."""
        await self.inventory_service.async_remove_batch(call)

    async def async_transfer_item(self, call: ServiceCall) -> None:
        """Move stock between locations of one inventory."""
        await self.inventory_service.async_transfer_item(call)

    async def async_set_item_image_from_barcode(self, call: ServiceCall) -> None:
        """Use the barcode lookup's product photo as the item's photo."""
        await self.image_service.async_set_item_image_from_barcode(call)

    async def async_set_item_image_from_media(self, call: ServiceCall) -> None:
        """Copy a local media file as the item's photo."""
        await self.image_service.async_set_item_image_from_media(call)

    async def async_clear_item_image(self, call: ServiceCall) -> None:
        """Remove the item's photo."""
        await self.image_service.async_clear_item_image(call)

    async def async_backup_database(self, call: ServiceCall) -> JsonObjectType:
        """Snapshot the shared database on demand."""
        return await self.backup_service.async_backup_database(call)

    async def async_restore_database(self, call: ServiceCall) -> JsonObjectType:
        """Restore a database snapshot on demand."""
        return await self.backup_service.async_restore_database(call)

    async def async_get_items(self, call: ServiceCall) -> JsonObjectType:
        """Fetch items, fire an event, and return the result."""
        result = await self.inventory_service.async_get_items(call)
        self.hass.bus.async_fire(
            f"{DOMAIN}_get_items_result",
            {
                "context_id": call.context.id,
                "inventory_id": call.data.get("inventory_id"),
                "inventory_name": call.data.get("inventory_name"),
                "result": result,
            },
        )
        return result

    async def async_get_items_from_all_inventories(self, call: ServiceCall) -> JsonObjectType:
        """Fetch all inventories, fire an event, and return the result."""
        result = await self.inventory_service.async_get_items_from_all_inventories(call)
        self.hass.bus.async_fire(
            f"{DOMAIN}_get_all_items_result",
            {
                "context_id": call.context.id,
                "result": result,
            },
        )
        return result

    async def async_lookup_by_barcode(self, call: ServiceCall) -> JsonObjectType:
        """Look up an item by barcode across all inventories."""
        barcode: str = call.data[FIELD_BARCODE]
        hub = get_hub(self.hass)
        if hub is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="no_inventories_configured"
            )
        results = await hub.async_lookup_by_barcode(barcode)
        return cast(JsonObjectType, {FIELD_ITEMS: results})

    async def async_scan_barcode(self, call: ServiceCall) -> JsonObjectType:
        """Scan a barcode and perform an action."""
        data = call.data
        result = await self.quantity_service.async_scan_barcode(
            barcode=data[FIELD_BARCODE],
            action=data["action"],
            amount=data.get(FIELD_AMOUNT, 1.0),
            inventory_id=data.get("inventory_id"),
            price=data.get(FIELD_PRICE),
            **{key: data[key] for key in SCAN_BATCH_KEYS if key in data},
        )
        return cast(JsonObjectType, result)

    async def async_lookup_barcode_product(self, call: ServiceCall) -> JsonObjectType:
        """Look up a barcode, checking internal inventory first, then external providers."""
        barcode: str = call.data[FIELD_BARCODE]

        # Check if an item with this barcode already exists in any inventory
        hub = get_hub(self.hass)
        if hub is not None:
            existing = await hub.async_lookup_by_barcode(barcode)
            if existing:
                item = existing[0]
                product: ProductInfo = {"name": item.get(FIELD_NAME, "")}
                if item.get(FIELD_DESCRIPTION):
                    product["description"] = item[FIELD_DESCRIPTION]
                if item.get(FIELD_CATEGORY):
                    product["category"] = item[FIELD_CATEGORY]
                if item.get(FIELD_UNIT):
                    product["unit"] = item[FIELD_UNIT]
                results: list[ProviderResult] = [
                    {"provider": "inventory", "found": True, "product": product}
                ]
                return cast(JsonObjectType, {FIELD_BARCODE: barcode, "results": results})

        results = await async_lookup_barcode_all_providers(self.hass, barcode)
        return cast(JsonObjectType, {FIELD_BARCODE: barcode, "results": results})

    async def async_get_inventory_consumption_rates(self, call: ServiceCall) -> JsonObjectType:
        """Return consumption rates for all items in an inventory."""
        data = call.data
        inventory_id: str = data["inventory_id"]
        window_days: int | None = data.get("window_days")

        coordinators = get_coordinators(self.hass)
        coordinator = coordinators.get(inventory_id)
        if coordinator is None:
            raise inventory_not_loaded_error(self.hass, inventory_id)

        result = await coordinator.async_get_inventory_consumption_rates(
            inventory_id, window_days=window_days
        )
        return cast(JsonObjectType, result)

    async def async_get_item_consumption_rates(self, call: ServiceCall) -> JsonObjectType:
        """Return consumption rates for a single item."""
        data = call.data
        inventory_id: str = data["inventory_id"]
        item_name: str = data[FIELD_NAME]
        window_days: int | None = data.get("window_days")

        coordinators = get_coordinators(self.hass)
        coordinator = coordinators.get(inventory_id)
        if coordinator is None:
            raise inventory_not_loaded_error(self.hass, inventory_id)

        result = await coordinator.async_get_item_consumption_rates(
            inventory_id, item_name, window_days=window_days
        )
        if result is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="item_not_found",
                translation_placeholders={
                    "name": item_name,
                    "inventory": inventory_display_name(self.hass, inventory_id),
                },
            )
        return cast(JsonObjectType, result)


__all__ = ["ServiceHandler", "InventoryService", "QuantityService"]
