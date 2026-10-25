"""WebSocket API for Simple Inventory."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Coroutine
from functools import wraps
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_integration

from .const import (
    API_VERSION,
    ATTENTION_SECTIONS,
    CONF_DESCRIPTION,
    CONF_ICON,
    DOMAIN,
    FEATURES,
    FIELD_AMOUNT,
    FIELD_BARCODE,
    FIELD_CATEGORY,
    FIELD_DESCRIPTION,
    FIELD_ITEMS,
    FIELD_LIMIT,
    FIELD_NAME,
    FIELD_PRICE,
    FIELD_UNIT,
    updated_event,
)
from .coordinator import SimpleInventoryCoordinator
from .data import get_coordinators, get_hub, get_repository, get_service_handler
from .entries import enabled_inventory_entries, entry_display_name, inventory_display_name
from .providers.base import ProductInfo, ProviderResult
from .providers.lookup import async_lookup_barcode_all_providers
from .providers.registry import PROVIDER_REGISTRY
from .schemas.service_schemas import ISO_DATE
from .services.quantity_service import SCAN_BATCH_KEYS

_LOGGER = logging.getLogger(__name__)

_AsyncCommand = Callable[
    [HomeAssistant, websocket_api.ActiveConnection, dict[str, Any]], Coroutine[Any, Any, None]
]
_Responder = Callable[[HomeAssistant, dict[str, Any]], Awaitable[Any]]
_CoordinatorResponder = Callable[[dict[str, Any], SimpleInventoryCoordinator], Awaitable[Any]]


class _CommandError(Exception):
    """An error response with its own code and message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _responds(
    error_code: str, catch: type[Exception] = Exception, *, translated: bool = False
) -> Callable[[_Responder], _AsyncCommand]:
    """Send the handler's return value as the result and map failures to error responses.

    ``_CommandError`` becomes its own code and message; an exception of type *catch*
    becomes *error_code* with ``str(exc)`` (plus its translation when *translated*);
    anything else propagates to Home Assistant.
    """

    def decorate(func: _Responder) -> _AsyncCommand:
        @wraps(func)
        async def command(
            hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
        ) -> None:
            try:
                result = await func(hass, msg)
            except _CommandError as err:
                connection.send_error(msg["id"], err.code, err.message)
                return
            except catch as exc:
                details: dict[str, Any] = {}
                if translated and isinstance(exc, HomeAssistantError):
                    details = {
                        "translation_key": exc.translation_key,
                        "translation_domain": exc.translation_domain,
                        "translation_placeholders": exc.translation_placeholders,
                    }
                connection.send_error(msg["id"], error_code, str(exc), **details)
                return
            connection.send_result(msg["id"], result)

        return command

    return decorate


def _with_coordinator(
    error_code: str, catch: type[Exception] = Exception
) -> Callable[[_CoordinatorResponder], _AsyncCommand]:
    """Like ``_responds``, for handlers of ``msg["inventory_id"]``'s coordinator.

    An unknown inventory is answered with ``inventory_not_found``.
    """

    def decorate(func: _CoordinatorResponder) -> _AsyncCommand:
        @_responds(error_code, catch)
        @wraps(func)
        async def respond(hass: HomeAssistant, msg: dict[str, Any]) -> Any:
            inventory_id = msg["inventory_id"]
            coordinator = get_coordinators(hass).get(inventory_id)
            if coordinator is None:
                raise _CommandError("inventory_not_found", f"Inventory '{inventory_id}' not found")
            return await func(msg, coordinator)

        return respond

    return decorate


def _item_not_found(msg: dict[str, Any], name: str) -> _CommandError:
    return _CommandError(
        "item_not_found", f"Item '{name}' not found in inventory '{msg['inventory_id']}'"
    )


def _validate_import_data(msg: dict[str, Any]) -> dict[str, Any]:
    """Require CSV text for format=csv; parse a JSON string for format=json."""
    data = msg["data"]
    if msg["format"] == "csv":
        if not isinstance(data, str):
            raise vol.Invalid("CSV import data must be a string", path=["data"])
        return msg

    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError as err:
            raise vol.Invalid(f"Invalid JSON: {err}", path=["data"]) from err
        if not isinstance(data, dict | list):
            raise vol.Invalid("JSON import data must be an object or a list", path=["data"])
        msg["data"] = data
    return msg


def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register WebSocket commands."""
    websocket_api.async_register_command(hass, ws_get_info)
    websocket_api.async_register_command(hass, ws_list_inventories)
    websocket_api.async_register_command(hass, ws_list_items)
    websocket_api.async_register_command(hass, ws_search)
    websocket_api.async_register_command(hass, ws_overview)
    websocket_api.async_register_command(hass, ws_get_item)
    websocket_api.async_register_command(hass, ws_subscribe)
    websocket_api.async_register_command(hass, ws_get_history)
    websocket_api.async_register_command(hass, ws_export)
    websocket_api.async_register_command(hass, ws_import)
    websocket_api.async_register_command(hass, ws_get_item_consumption_rates)
    websocket_api.async_register_command(hass, ws_get_inventory_consumption_rates)
    websocket_api.async_register_command(hass, ws_get_inventory_statistics)
    websocket_api.async_register_command(hass, ws_lookup_by_barcode)
    websocket_api.async_register_command(hass, ws_lookup_barcode_product)
    websocket_api.async_register_command(hass, ws_get_barcode_provider_config)
    websocket_api.async_register_command(hass, ws_set_barcode_provider_config)
    websocket_api.async_register_command(hass, ws_scan_barcode)


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/get_info"})
@websocket_api.async_response
async def ws_get_info(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Report integration version, frontend API version and features."""
    integration = await async_get_integration(hass, DOMAIN)
    connection.send_result(
        msg["id"],
        {
            "version": str(integration.version) if integration.version else None,
            "api_version": API_VERSION,
            "features": list(FEATURES),
        },
    )


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/list_inventories"})
@callback
def ws_list_inventories(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Every enabled inventory (not the global entry) with its sensor, sorted by name."""
    registry = er.async_get(hass)
    inventories = [
        {
            "id": entry.entry_id,
            "name": inventory_display_name(hass, entry.entry_id),
            "icon": str(entry.data.get(CONF_ICON, "")),
            "description": str(entry.data.get(CONF_DESCRIPTION, "")),
            "entity_id": registry.async_get_entity_id(
                "sensor", DOMAIN, f"inventory_{entry.entry_id}"
            ),
        }
        for entry in enabled_inventory_entries(hass)
    ]
    inventories.sort(key=lambda inventory: str(inventory["name"]).casefold())
    connection.send_result(msg["id"], {"inventories": inventories})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/list_items",
        vol.Required("inventory_id"): str,
    }
)
@websocket_api.async_response
@_with_coordinator("list_items_failed")
async def ws_list_items(
    msg: dict[str, Any], coordinator: SimpleInventoryCoordinator
) -> dict[str, Any]:
    """Return all items for an inventory."""
    return {FIELD_ITEMS: await coordinator.async_list_items(msg["inventory_id"])}


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/search",
        vol.Required("query"): vol.All(str, str.strip, vol.Length(max=100)),
        vol.Optional(FIELD_LIMIT, default=50): vol.All(int, vol.Range(min=1, max=200)),
    }
)
@websocket_api.async_response
@_responds("search_failed")
async def ws_search(hass: HomeAssistant, msg: dict[str, Any]) -> dict[str, Any]:
    """Items of every enabled inventory matching the query, best match first."""
    hub = get_hub(hass)
    if hub is None:
        return {FIELD_ITEMS: [], "truncated": False}
    return await hub.async_search(msg["query"], _enabled_inventory_names(hass), msg[FIELD_LIMIT])


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/overview"})
@websocket_api.async_response
@_responds("overview_failed")
async def ws_overview(hass: HomeAssistant, msg: dict[str, Any]) -> dict[str, Any]:
    """Summaries of every enabled inventory and what needs attention in them."""
    hub = get_hub(hass)
    if hub is None:
        return {"inventories": [], **{section: [] for section in ATTENTION_SECTIONS}}
    return await hub.async_overview(_enabled_inventory_names(hass))


def _enabled_inventory_names(hass: HomeAssistant) -> dict[str, str]:
    """Display name of every enabled inventory, by id: the scope of search and overview."""
    return {entry.entry_id: entry_display_name(entry) for entry in enabled_inventory_entries(hass)}


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/get_item",
        vol.Required("inventory_id"): str,
        vol.Required("name"): str,
    }
)
@websocket_api.async_response
@_with_coordinator("get_item_failed")
async def ws_get_item(
    msg: dict[str, Any], coordinator: SimpleInventoryCoordinator
) -> dict[str, Any]:
    """Return a single item by name."""
    item = await coordinator.async_get_item(msg["inventory_id"], msg[FIELD_NAME])
    if item is None:
        raise _item_not_found(msg, msg[FIELD_NAME])
    return {"item": item}


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/subscribe",
        vol.Optional("inventory_id"): str,
    }
)
@callback
def ws_subscribe(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Subscribe to inventory update events."""
    inventory_id = msg.get("inventory_id")

    async def _forward_event(event: Any) -> None:
        """Forward HA event to WS subscriber."""
        try:
            coordinator = get_coordinators(hass).get(inventory_id or "")
            if inventory_id and coordinator:
                items = await coordinator.async_list_items(inventory_id)
                connection.send_event(msg["id"], {FIELD_ITEMS: items})
            else:
                connection.send_event(msg["id"], {"event": "updated"})
        except Exception as exc:
            _LOGGER.error("Error forwarding inventory update event: %s", exc)

    unsub = hass.bus.async_listen(updated_event(inventory_id), _forward_event)
    connection.subscriptions[msg["id"]] = unsub
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/get_history",
        vol.Required("inventory_id"): str,
        vol.Optional("item_name"): str,
        vol.Optional("event_type"): str,
        vol.Optional("start_date"): str,
        vol.Optional("end_date"): str,
        vol.Optional("limit", default=100): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Optional("offset", default=0): vol.All(vol.Coerce(int), vol.Range(min=0)),
    }
)
@websocket_api.async_response
@_with_coordinator("history_failed")
async def ws_get_history(
    msg: dict[str, Any], coordinator: SimpleInventoryCoordinator
) -> dict[str, Any]:
    """Return history events for an inventory, or for one item when item_name is given."""
    filters: dict[str, Any] = {
        "event_type": msg.get("event_type"),
        "start_date": msg.get("start_date"),
        "end_date": msg.get("end_date"),
        "limit": msg.get("limit", 100),
        "offset": msg.get("offset", 0),
    }
    if item_name := msg.get("item_name"):
        events = await coordinator.async_get_item_history(msg["inventory_id"], item_name, **filters)
    else:
        events = await coordinator.async_get_inventory_history(msg["inventory_id"], **filters)
    return {"events": events}


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/export",
        vol.Required("inventory_id"): str,
        vol.Optional("format", default="json"): vol.In(["json", "csv"]),
    }
)
@websocket_api.async_response
@_with_coordinator("export_failed", catch=ValueError)
async def ws_export(msg: dict[str, Any], coordinator: SimpleInventoryCoordinator) -> dict[str, Any]:
    """Export inventory data."""
    fmt = msg.get("format", "json")
    return {
        "data": await coordinator.async_export_inventory(msg["inventory_id"], fmt),
        "format": fmt,
    }


@websocket_api.websocket_command(
    vol.All(
        vol.Schema(
            {
                vol.Required("type"): f"{DOMAIN}/import",
                vol.Required("inventory_id"): str,
                vol.Required("data"): vol.Any(str, dict, list),
                vol.Optional("format", default="json"): vol.In(["json", "csv"]),
                vol.Optional("merge_strategy", default="skip"): vol.In(
                    ["skip", "overwrite", "merge_quantities"]
                ),
            }
        ),
        _validate_import_data,
    )
)
@websocket_api.async_response
@_with_coordinator("import_failed")
async def ws_import(msg: dict[str, Any], coordinator: SimpleInventoryCoordinator) -> Any:
    """Import inventory data."""
    return await coordinator.async_import_inventory(
        msg["inventory_id"],
        msg["data"],
        msg.get("format", "json"),
        msg.get("merge_strategy", "skip"),
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/get_item_consumption_rates",
        vol.Required("inventory_id"): str,
        vol.Required("item_name"): str,
        vol.Optional("window_days"): vol.Any(vol.All(vol.Coerce(int), vol.Range(min=1)), None),
    }
)
@websocket_api.async_response
@_with_coordinator("item_consumption_rates_failed")
async def ws_get_item_consumption_rates(
    msg: dict[str, Any], coordinator: SimpleInventoryCoordinator
) -> Any:
    """Return consumption rates for a single item."""
    result = await coordinator.async_get_item_consumption_rates(
        msg["inventory_id"], msg["item_name"], window_days=msg.get("window_days")
    )
    if result is None:
        raise _item_not_found(msg, msg["item_name"])
    return result


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/get_inventory_consumption_rates",
        vol.Required("inventory_id"): str,
        vol.Optional("window_days"): vol.Any(vol.All(vol.Coerce(int), vol.Range(min=1)), None),
    }
)
@websocket_api.async_response
@_with_coordinator("inventory_consumption_rates_failed")
async def ws_get_inventory_consumption_rates(
    msg: dict[str, Any], coordinator: SimpleInventoryCoordinator
) -> Any:
    """Return consumption rates for all items in an inventory."""
    return await coordinator.async_get_inventory_consumption_rates(
        msg["inventory_id"], window_days=msg.get("window_days")
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/get_inventory_statistics",
        vol.Required("inventory_id"): str,
    }
)
@websocket_api.async_response
@_with_coordinator("inventory_statistics_failed")
async def ws_get_inventory_statistics(
    msg: dict[str, Any], coordinator: SimpleInventoryCoordinator
) -> Any:
    """Return aggregate statistics for an inventory."""
    return await coordinator.async_get_inventory_statistics(msg["inventory_id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/lookup_by_barcode",
        vol.Required("barcode"): str,
    }
)
@websocket_api.async_response
@_responds("lookup_by_barcode_failed")
async def ws_lookup_by_barcode(hass: HomeAssistant, msg: dict[str, Any]) -> dict[str, Any]:
    """Look up an item by barcode across all inventories."""
    hub = get_hub(hass)
    if hub is None:
        raise _CommandError("no_inventories", "No inventories configured")
    return {FIELD_ITEMS: await hub.async_lookup_by_barcode(msg[FIELD_BARCODE])}


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/lookup_barcode_product",
        vol.Required("barcode"): str,
    }
)
@websocket_api.async_response
@_responds("lookup_barcode_product_failed")
async def ws_lookup_barcode_product(hass: HomeAssistant, msg: dict[str, Any]) -> dict[str, Any]:
    """Look up a barcode, checking internal inventory first, then external providers."""
    barcode = msg[FIELD_BARCODE]

    # Check if an item with this barcode already exists in any inventory
    hub = get_hub(hass)
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
            return {FIELD_BARCODE: barcode, "results": results}

    results = await async_lookup_barcode_all_providers(hass, barcode)
    return {FIELD_BARCODE: barcode, "results": results}


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/get_barcode_provider_config",
    }
)
@websocket_api.async_response
@_responds("get_barcode_provider_config_failed")
async def ws_get_barcode_provider_config(hass: HomeAssistant, msg: dict[str, Any]) -> Any:
    """Return the current barcode provider configuration."""
    repository = get_repository(hass)
    if repository is None:
        return {}
    return await repository.get_barcode_provider_config()


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/set_barcode_provider_config",
        vol.Required("provider"): vol.In(list(PROVIDER_REGISTRY)),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
@_responds("set_barcode_provider_config_failed")
async def ws_set_barcode_provider_config(hass: HomeAssistant, msg: dict[str, Any]) -> Any:
    """Set the barcode provider configuration."""
    provider = msg["provider"]
    repository = get_repository(hass)
    if repository is None:
        raise _CommandError("no_repository", "Repository not available")
    await repository.set_barcode_provider_config({"provider": provider})
    return {"provider": provider}


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/scan_barcode",
        vol.Required("barcode"): str,
        vol.Required("action"): vol.In(["increment", "decrement", "lookup"]),
        vol.Optional("amount", default=1.0): vol.All(
            vol.Coerce(float), vol.Range(min=0, min_included=False)
        ),
        vol.Optional("inventory_id"): str,
        vol.Optional("price"): vol.All(vol.Coerce(float), vol.Range(min=0)),
        vol.Optional("expiry_date"): ISO_DATE,
        vol.Optional("location"): str,
        vol.Optional("purchased_at"): vol.All(ISO_DATE, vol.Length(min=10)),
        vol.Optional("batch_id"): str,
    }
)
@websocket_api.async_response
@_responds("scan_failed", catch=HomeAssistantError, translated=True)
async def ws_scan_barcode(hass: HomeAssistant, msg: dict[str, Any]) -> Any:
    """Scan a barcode and perform an action."""
    service_handler = get_service_handler(hass)
    if service_handler is None:
        raise _CommandError("no_inventories", "No inventories configured")
    return await service_handler.quantity_service.async_scan_barcode(
        barcode=msg[FIELD_BARCODE],
        action=msg["action"],
        amount=msg.get(FIELD_AMOUNT, 1.0),
        inventory_id=msg.get("inventory_id"),
        price=msg.get(FIELD_PRICE),
        **{key: msg[key] for key in SCAN_BATCH_KEYS if key in msg},
    )
