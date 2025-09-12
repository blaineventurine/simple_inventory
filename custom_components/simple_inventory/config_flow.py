"""Config flow."""

from __future__ import annotations

import logging
from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector, translation

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

DEFAULT_ICON = "mdi:package-variant"


async def clean_inventory_name(hass: HomeAssistant, name: str) -> str:
    """Remove the word 'inventory' from the name, unless it's the only word."""
    import re

    try:
        current_lang = hass.config.language
        translations = await translation.async_get_translations(
            hass, current_lang, "common", {DOMAIN}
        )
        full_key = f"component.{DOMAIN}.common.inventory_word"
        inventory_word = translations.get(full_key, "inventory").lower()
    except Exception:
        inventory_word = "inventory"

    if name.strip().lower() == inventory_word:
        return name.strip()

    pattern = rf"\b{re.escape(inventory_word)}\b"
    cleaned = re.sub(pattern, "", name, flags=re.IGNORECASE)
    return " ".join(cleaned.split()).strip()


class SimpleInventoryConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Simple Inventory."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step."""
        return await self.async_step_add_inventory(user_input)

    async def async_step_add_inventory(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle adding a new inventory."""
        errors = {}

        if user_input is not None:
            cleaned_name = await clean_inventory_name(self.hass, user_input["name"])

            if await self._async_name_exists(cleaned_name):
                errors["name"] = "name_exists"
            else:
                icon = user_input.get("icon") or DEFAULT_ICON

                return self.async_create_entry(
                    title=cleaned_name,
                    data={
                        "name": cleaned_name,
                        "icon": icon,
                        "description": user_input.get("description", ""),
                        "entry_type": "inventory",
                        "create_global": not self._global_entry_exists(),
                    },
                )

        # Preserve form data on errors
        defaults = user_input or {}

        return self.async_show_form(
            step_id="add_inventory",
            data_schema=vol.Schema(
                {
                    vol.Required("name", default=defaults.get("name", "")): cv.string,
                    vol.Optional(
                        "icon", default=defaults.get("icon", DEFAULT_ICON)
                    ): selector.IconSelector(),
                    vol.Optional("description", default=defaults.get("description", "")): cv.string,
                }
            ),
            errors=errors,
        )

    async def async_step_internal(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle internal creation of global entry."""
        return self.async_create_entry(
            title="All Items Expiring Soon",
            data=user_input or {},
        )

    def _global_entry_exists(self) -> bool:
        """Check if global config entry already exists."""
        existing_entries = self._async_current_entries()
        return any(entry.data.get("entry_type") == "global" for entry in existing_entries)

    async def _async_name_exists(self, name: str) -> bool:
        """Check if inventory name already exists."""
        existing_entries = self._async_current_entries()
        existing_names = [entry.data.get("name", "").lower() for entry in existing_entries]
        return name.lower() in existing_names

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlowHandler:
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for inventory configuration."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        pass

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options."""
        errors = {}

        if user_input is not None:
            cleaned_name = await clean_inventory_name(self.hass, user_input["name"])

            if await self._async_name_exists_excluding_current(cleaned_name):
                errors["name"] = "name_exists"
            else:
                new_data = {
                    "name": cleaned_name,
                    "icon": user_input.get("icon", DEFAULT_ICON),
                    "description": user_input.get("description", ""),
                }

                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data=new_data,
                    title=cleaned_name,
                )

                self.hass.bus.async_fire(
                    f"{DOMAIN}_updated_{self.config_entry.entry_id}",
                    {"action": "renamed", "new_name": cleaned_name},
                )

                return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required("name", default=self.config_entry.data.get("name", "")): cv.string,
                    vol.Optional(
                        "icon",
                        default=self.config_entry.data.get("icon", DEFAULT_ICON),
                    ): selector.IconSelector(),
                    vol.Optional(
                        "description",
                        default=self.config_entry.data.get("description", ""),
                    ): cv.string,
                }
            ),
            errors=errors,
            description_placeholders={
                "current_name": self.config_entry.data.get("name", ""),
            },
        )

    async def _async_name_exists_excluding_current(self, name: str) -> bool:
        """Check if name exists in other entries."""
        all_entries = self.hass.config_entries.async_entries(DOMAIN)
        return any(
            entry.entry_id != self.config_entry.entry_id
            and entry.data.get("name", "").lower() == name.lower()
            for entry in all_entries
        )
