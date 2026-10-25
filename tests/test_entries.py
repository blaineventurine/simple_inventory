"""Tests for the config-entry vocabulary in entries.py."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryDisabler
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (  # type: ignore[import-untyped]
    MockConfigEntry,
)

from custom_components.simple_inventory.const import DOMAIN
from custom_components.simple_inventory.entries import (
    enabled_inventory_entries,
    inventory_display_name,
)


def _add(hass: HomeAssistant, entry_id: str, title: str, data: dict[str, str]) -> None:
    MockConfigEntry(domain=DOMAIN, entry_id=entry_id, title=title, data=data).add_to_hass(hass)


def test_display_name_prefers_the_stored_name(hass: HomeAssistant) -> None:
    _add(hass, "kitchen", "Kitchen Title", {"name": "Kitchen"})

    assert inventory_display_name(hass, "kitchen") == "Kitchen"


def test_display_name_falls_back_to_the_entry_title(hass: HomeAssistant) -> None:
    _add(hass, "kitchen", "Kitchen", {})

    assert inventory_display_name(hass, "kitchen") == "Kitchen"
    assert inventory_display_name(hass, "kitchen", default="Unknown Inventory") == "Kitchen"


def test_display_name_without_name_or_title_uses_default_or_id(hass: HomeAssistant) -> None:
    _add(hass, "kitchen", "", {})

    assert inventory_display_name(hass, "kitchen") == "kitchen"
    assert inventory_display_name(hass, "missing", default="Unknown Inventory") == (
        "Unknown Inventory"
    )


def test_enabled_inventory_entries_skip_global_disabled_and_nameless(hass: HomeAssistant) -> None:
    _add(hass, "kitchen", "Kitchen", {"name": "Kitchen", "entry_type": "inventory"})
    _add(hass, "global", "All", {"name": "All", "entry_type": "global"})
    _add(hass, "nameless", "Nameless", {"entry_type": "inventory"})
    MockConfigEntry(
        domain=DOMAIN,
        entry_id="attic",
        title="Attic",
        data={"name": "Attic", "entry_type": "inventory"},
        disabled_by=ConfigEntryDisabler.USER,
    ).add_to_hass(hass)

    assert [entry.entry_id for entry in enabled_inventory_entries(hass)] == ["kitchen"]
