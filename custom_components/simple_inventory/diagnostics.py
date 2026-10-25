"""Config entry diagnostics for Simple Inventory.

Only configuration and aggregate counts are reported. Item names, descriptions,
barcodes, aliases and prices are household data and never appear here.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import API_VERSION, CONF_DESCRIPTION, CONF_ICON, CONF_NAME, DOMAIN
from .data import get_repository
from .entries import entry_type, is_global_entry
from .storage.repository import LEGACY_MIGRATION_FLAG, InventoryRepository
from .todo_manager import supports_description


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    integration = await async_get_integration(hass, DOMAIN)
    repository = get_repository(hass)

    diagnostics: dict[str, Any] = {
        "integration_version": str(integration.version) if integration.version else None,
        "api_version": API_VERSION,
        "schema_version": None,
        "legacy_migrated": None,
        "entry": {
            "entry_type": entry_type(entry),
            "name": entry.data.get(CONF_NAME, entry.title),
            "icon": entry.data.get(CONF_ICON, ""),
            "has_description": bool(entry.data.get(CONF_DESCRIPTION)),
            "options": dict(entry.options),
            "state": entry.state.value,
        },
        "counts": None,
        "auto_add": None,
        "barcode_provider": None,
    }

    if repository is not None:
        diagnostics.update(await _async_database_diagnostics(hass, entry, repository))

    if is_global_entry(entry):
        diagnostics["inventories"] = [
            {
                "entry_id": other.entry_id,
                "name": other.data.get(CONF_NAME, other.title),
                "state": other.state.value,
            }
            for other in hass.config_entries.async_entries(DOMAIN)
            if other.entry_id != entry.entry_id
        ]

    return diagnostics


async def _async_database_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry, repository: InventoryRepository
) -> dict[str, Any]:
    schema_version = await repository.get_metadata_value("schema_version")
    counts = await repository.get_inventory_counts(entry.entry_id)
    enabled_items = counts.pop("auto_add_enabled")
    references = await repository.get_todo_list_references(entry.entry_id)
    provider = (await repository.get_barcode_provider_config()).get("provider")

    return {
        "schema_version": int(schema_version) if schema_version is not None else None,
        "legacy_migrated": await repository.get_metadata_value(LEGACY_MIGRATION_FLAG) == "1",
        "counts": counts,
        "auto_add": {
            "enabled_items": enabled_items,
            "todo_lists": [
                {
                    "entity_id": entity_id,
                    "items": count,
                    "exists": hass.states.get(entity_id) is not None,
                    "supports_description": supports_description(hass, entity_id),
                }
                for entity_id, count in references.items()
            ],
        },
        "barcode_provider": provider or None,
    }
