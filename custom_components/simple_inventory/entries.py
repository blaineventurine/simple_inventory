"""What a Simple Inventory config entry is: its type and its display name.

Kept free of other integration modules so the config flow, sensors, coordinator and
resolvers can all import it.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_ENTRY_TYPE, CONF_NAME, DOMAIN, ENTRY_TYPE_GLOBAL, ENTRY_TYPE_INVENTORY


def entry_type(entry: ConfigEntry) -> str:
    """The entry's type; entries created before the key existed are inventories."""
    return str(entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_INVENTORY))


def is_global_entry(entry: ConfigEntry) -> bool:
    """True for the single cross-inventory (expiry sensors) entry."""
    return entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_GLOBAL


def inventory_entries(hass: HomeAssistant) -> list[ConfigEntry]:
    """Every named, non-global inventory entry."""
    return [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if not is_global_entry(entry) and entry.data.get(CONF_NAME)
    ]


def enabled_inventory_entries(hass: HomeAssistant) -> list[ConfigEntry]:
    """Inventory entries not disabled; a disabled one has no sensor or data to show."""
    return [entry for entry in inventory_entries(hass) if entry.disabled_by is None]


def entry_display_name(entry: ConfigEntry, default: str | None = None) -> str:
    """*entry*'s stored name, else its title; ``default`` (or its id) when it has neither."""
    name = entry.data.get(CONF_NAME) or entry.title
    if name:
        return str(name)
    return entry.entry_id if default is None else default


def inventory_display_name(hass: HomeAssistant, entry_id: str, default: str | None = None) -> str:
    """Human-readable name of an entry: its stored name, else its title.

    ``default`` (or the id itself) when the entry is unknown or has neither.
    """
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.entry_id == entry_id:
            return entry_display_name(entry, default)
    return entry_id if default is None else default
