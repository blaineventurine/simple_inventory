"""WebSocket API for Simple Inventory."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN
from .providers.lookup import async_lookup_barcode_all_providers
from .services.domain_data import get_coordinators, get_repository

_LOGGER = logging.getLogger(__name__)


def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register WebSocket commands."""
    websocket_api.async_register_command(hass, ws_list_items)
    websocket_api.async_register_command(hass, ws_get_item)
    websocket_api.async_register_command(hass, ws_subscribe)
    websocket_api.async_register_command(hass, ws_get_history)
    websocket_api.async_register_command(hass, ws_export)
    websocket_api.async_register_command(hass, ws_import)
    websocket_api.async_register_command(hass, ws_get_item_consumption_rates)
    websocket_api.async_register_command(hass, ws_get_inventory_consumption_rates)
    websocket_api.async_register_command(hass, ws_lookup_by_barcode)
    websocket_api.async_register_command(hass, ws_lookup_barcode_product)
    websocket_api.async_register_command(hass, ws_get_barcode_provider_config)
    websocket_api.async_register_command(hass, ws_set_barcode_provider_config)
    websocket_api.async_register_command(hass, ws_scan_barcode)


async def _handle_list_items(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return all items for an inventory."""
    inventory_id = msg["inventory_id"]
    coordinator = get_coordinators(hass).get(inventory_id)
    if coordinator is None:
        connection.send_error(
            msg["id"],
            "inventory_not_found",
            f"Inventory '{inventory_id}' not found",
        )
        return

    items = await coordinator.async_list_items(inventory_id)
    connection.send_result(msg["id"], {"items": items})


async def _handle_get_item(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return a single item by name."""
    inventory_id = msg["inventory_id"]
    name = msg["name"]
    coordinator = get_coordinators(hass).get(inventory_id)
    if coordinator is None:
        connection.send_error(
            msg["id"],
            "inventory_not_found",
            f"Inventory '{inventory_id}' not found",
        )
        return

    item = await coordinator.async_get_item(inventory_id, name)
    if item is None:
        connection.send_error(
            msg["id"],
            "item_not_found",
            f"Item '{name}' not found in inventory '{inventory_id}'",
        )
        return

    connection.send_result(msg["id"], {"item": item})


async def _handle_get_history(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return history events."""
    inventory_id = msg["inventory_id"]
    coordinator = get_coordinators(hass).get(inventory_id)
    if coordinator is None:
        connection.send_error(
            msg["id"],
            "inventory_not_found",
            f"Inventory '{inventory_id}' not found",
        )
        return

    item_name = msg.get("item_name")
    event_type = msg.get("event_type")
    start_date = msg.get("start_date")
    end_date = msg.get("end_date")
    limit = msg.get("limit", 100)
    offset = msg.get("offset", 0)

    if item_name:
        events = await coordinator.async_get_item_history(
            inventory_id,
            item_name,
            event_type=event_type,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset,
        )
    else:
        events = await coordinator.async_get_inventory_history(
            inventory_id,
            event_type=event_type,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset,
        )

    connection.send_result(msg["id"], {"events": events})


async def _handle_export(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Export inventory data."""
    inventory_id = msg["inventory_id"]
    fmt = msg.get("format", "json")
    coordinator = get_coordinators(hass).get(inventory_id)
    if coordinator is None:
        connection.send_error(
            msg["id"],
            "inventory_not_found",
            f"Inventory '{inventory_id}' not found",
        )
        return

    try:
        result = await coordinator.async_export_inventory(inventory_id, fmt)
        connection.send_result(msg["id"], {"data": result, "format": fmt})
    except ValueError as exc:
        connection.send_error(msg["id"], "export_failed", str(exc))


async def _handle_import(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Import inventory data."""
    inventory_id = msg["inventory_id"]
    fmt = msg.get("format", "json")
    data = msg["data"]
    merge_strategy = msg.get("merge_strategy", "skip")

    coordinator = get_coordinators(hass).get(inventory_id)
    if coordinator is None:
        connection.send_error(
            msg["id"],
            "inventory_not_found",
            f"Inventory '{inventory_id}' not found",
        )
        return

    summary = await coordinator.async_import_inventory(inventory_id, data, fmt, merge_strategy)
    connection.send_result(msg["id"], summary)


def _handle_subscribe(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Subscribe to inventory update events."""
    inventory_id = msg.get("inventory_id")

    if inventory_id:
        event_type = f"{DOMAIN}_updated_{inventory_id}"
    else:
        event_type = f"{DOMAIN}_updated"

    async def _forward_event(event: Any) -> None:
        """Forward HA event to WS subscriber."""
        coordinator = get_coordinators(hass).get(inventory_id or "")
        if inventory_id and coordinator:
            items = await coordinator.async_list_items(inventory_id)
            connection.send_event(msg["id"], {"items": items})
        else:
            connection.send_event(msg["id"], {"event": "updated"})

    unsub = hass.bus.async_listen(event_type, _forward_event)
    connection.subscriptions[msg["id"]] = unsub
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/list_items",
        vol.Required("inventory_id"): str,
    }
)
@websocket_api.async_response
async def ws_list_items(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """WS command: list items."""
    await _handle_list_items(hass, connection, msg)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/get_item",
        vol.Required("inventory_id"): str,
        vol.Required("name"): str,
    }
)
@websocket_api.async_response
async def ws_get_item(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """WS command: get item."""
    await _handle_get_item(hass, connection, msg)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/export",
        vol.Required("inventory_id"): str,
        vol.Optional("format", default="json"): vol.In(["json", "csv"]),
    }
)
@websocket_api.async_response
async def ws_export(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """WS command: export inventory."""
    await _handle_export(hass, connection, msg)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/import",
        vol.Required("inventory_id"): str,
        vol.Required("data"): vol.Any(str, dict, list),
        vol.Optional("format", default="json"): vol.In(["json", "csv"]),
        vol.Optional("merge_strategy", default="skip"): vol.In(
            ["skip", "overwrite", "merge_quantities"]
        ),
    }
)
@websocket_api.async_response
async def ws_import(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """WS command: import inventory."""
    await _handle_import(hass, connection, msg)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/get_history",
        vol.Required("inventory_id"): str,
        vol.Optional("item_name"): str,
        vol.Optional("event_type"): str,
        vol.Optional("start_date"): str,
        vol.Optional("end_date"): str,
        vol.Optional("limit", default=100): int,
        vol.Optional("offset", default=0): int,
    }
)
@websocket_api.async_response
async def ws_get_history(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """WS command: get history."""
    await _handle_get_history(hass, connection, msg)


async def _handle_get_item_consumption_rates(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return consumption rates for a single item."""
    inventory_id = msg["inventory_id"]
    item_name = msg["item_name"]
    window_days = msg.get("window_days")

    coordinator = get_coordinators(hass).get(inventory_id)
    if coordinator is None:
        connection.send_error(
            msg["id"],
            "inventory_not_found",
            f"Inventory '{inventory_id}' not found",
        )
        return

    result = await coordinator.async_get_item_consumption_rates(
        inventory_id, item_name, window_days=window_days
    )
    if result is None:
        connection.send_error(
            msg["id"],
            "item_not_found",
            f"Item '{item_name}' not found in inventory '{inventory_id}'",
        )
        return

    connection.send_result(msg["id"], result)


async def _handle_get_inventory_consumption_rates(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return consumption rates for all items in an inventory."""
    inventory_id = msg["inventory_id"]
    window_days = msg.get("window_days")

    coordinator = get_coordinators(hass).get(inventory_id)
    if coordinator is None:
        connection.send_error(
            msg["id"],
            "inventory_not_found",
            f"Inventory '{inventory_id}' not found",
        )
        return

    result = await coordinator.async_get_inventory_consumption_rates(
        inventory_id, window_days=window_days
    )
    connection.send_result(msg["id"], result)


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
    """WS command: subscribe."""
    _handle_subscribe(hass, connection, msg)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/get_item_consumption_rates",
        vol.Required("inventory_id"): str,
        vol.Required("item_name"): str,
        vol.Optional("window_days"): vol.Any(vol.In([30, 60, 90]), None),
    }
)
@websocket_api.async_response
async def ws_get_item_consumption_rates(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """WS command: get item consumption rates."""
    await _handle_get_item_consumption_rates(hass, connection, msg)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/get_inventory_consumption_rates",
        vol.Required("inventory_id"): str,
        vol.Optional("window_days"): vol.Any(vol.In([30, 60, 90]), None),
    }
)
@websocket_api.async_response
async def ws_get_inventory_consumption_rates(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """WS command: get inventory consumption rates."""
    await _handle_get_inventory_consumption_rates(hass, connection, msg)


async def _handle_lookup_by_barcode(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Look up an item by barcode across all inventories."""
    barcode = msg["barcode"]
    coordinators = get_coordinators(hass)
    if not coordinators:
        connection.send_error(msg["id"], "no_inventories", "No inventories configured")
        return

    coordinator = next(iter(coordinators.values()))
    results = await coordinator.async_lookup_by_barcode(barcode)
    connection.send_result(msg["id"], {"items": results})


async def _handle_scan_barcode(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Scan a barcode and perform an action."""
    barcode = msg["barcode"]
    action = msg["action"]
    amount = msg.get("amount", 1.0)
    inventory_id = msg.get("inventory_id")
    price = msg.get("price")

    coordinators = get_coordinators(hass)
    if not coordinators:
        connection.send_error(msg["id"], "no_inventories", "No inventories configured")
        return

    if inventory_id:
        coordinator = coordinators.get(inventory_id)
        if coordinator is None:
            connection.send_error(
                msg["id"],
                "inventory_not_found",
                f"Inventory '{inventory_id}' not found",
            )
            return
    else:
        coordinator = next(iter(coordinators.values()))

    try:
        result = await coordinator.async_scan_barcode(
            barcode, action, amount, inventory_id, price=price
        )
        connection.send_result(msg["id"], result)
    except ValueError as exc:
        connection.send_error(msg["id"], "scan_failed", str(exc))


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/lookup_by_barcode",
        vol.Required("barcode"): str,
    }
)
@websocket_api.async_response
async def ws_lookup_by_barcode(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """WS command: lookup by barcode."""
    await _handle_lookup_by_barcode(hass, connection, msg)


async def _handle_lookup_barcode_product(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Look up a barcode, checking internal inventory first, then external providers."""
    barcode = msg["barcode"]

    # Check if an item with this barcode already exists in any inventory
    coordinators = get_coordinators(hass)
    if coordinators:
        coordinator = next(iter(coordinators.values()))
        existing = await coordinator.async_lookup_by_barcode(barcode)
        if existing:
            item = existing[0]
            product: dict[str, Any] = {"name": item.get("name", "")}
            if item.get("description"):
                product["description"] = item["description"]
            if item.get("category"):
                product["category"] = item["category"]
            if item.get("unit"):
                product["unit"] = item["unit"]
            results = [{"provider": "inventory", "found": True, "product": product}]
            connection.send_result(msg["id"], {"barcode": barcode, "results": results})
            return

    results = await async_lookup_barcode_all_providers(hass, barcode)
    connection.send_result(msg["id"], {"barcode": barcode, "results": results})


async def _handle_get_barcode_provider_config(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the current barcode provider configuration."""
    repository = get_repository(hass)
    if repository is None:
        connection.send_result(msg["id"], {})
        return
    config = await repository.get_barcode_provider_config()
    connection.send_result(msg["id"], config)


async def _handle_set_barcode_provider_config(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Set the barcode provider configuration."""
    provider = msg["provider"]
    repository = get_repository(hass)
    if repository is None:
        connection.send_error(msg["id"], "no_repository", "Repository not available")
        return
    await repository.set_barcode_provider_config({"provider": provider})
    connection.send_result(msg["id"], {"provider": provider})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/lookup_barcode_product",
        vol.Required("barcode"): str,
    }
)
@websocket_api.async_response
async def ws_lookup_barcode_product(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """WS command: lookup barcode product."""
    await _handle_lookup_barcode_product(hass, connection, msg)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/get_barcode_provider_config",
    }
)
@websocket_api.async_response
async def ws_get_barcode_provider_config(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """WS command: get barcode provider config."""
    await _handle_get_barcode_provider_config(hass, connection, msg)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/set_barcode_provider_config",
        vol.Required("provider"): str,
    }
)
@websocket_api.async_response
async def ws_set_barcode_provider_config(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """WS command: set barcode provider config."""
    await _handle_set_barcode_provider_config(hass, connection, msg)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/scan_barcode",
        vol.Required("barcode"): str,
        vol.Required("action"): vol.In(["increment", "decrement", "lookup"]),
        vol.Optional("amount", default=1.0): float,
        vol.Optional("inventory_id"): str,
        vol.Optional("price"): float,
    }
)
@websocket_api.async_response
async def ws_scan_barcode(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """WS command: scan barcode."""
    await _handle_scan_barcode(hass, connection, msg)
