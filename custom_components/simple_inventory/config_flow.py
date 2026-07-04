"""Config flow."""

from __future__ import annotations

import logging
import re
from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector, translation

from .const import DOMAIN
from .voice_sentences import async_install_voice_sentences, can_offer_voice_sentences

_LOGGER = logging.getLogger(__name__)

DEFAULT_ICON = "mdi:package-variant"


async def clean_inventory_name(hass: HomeAssistant, name: str) -> str:
    """Remove the word 'inventory' from the name, unless it's the only word."""
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
        is_first_inventory = not self._global_entry_exists()
        offer_voice_sentences = is_first_inventory and can_offer_voice_sentences(self.hass)

        if user_input is not None:
            cleaned_name = await clean_inventory_name(self.hass, user_input["name"])

            if await self._async_name_exists(cleaned_name):
                errors["name"] = "name_exists"
            else:
                icon = user_input.get("icon") or DEFAULT_ICON

                if offer_voice_sentences and user_input.get("install_voice_sentences"):
                    await async_install_voice_sentences(self.hass)

                return self.async_create_entry(
                    title=cleaned_name,
                    data={
                        "name": cleaned_name,
                        "icon": icon,
                        "description": user_input.get("description", ""),
                        "entry_type": "inventory",
                        "create_global": is_first_inventory,
                    },
                )

        defaults = user_input or {}

        schema_dict: dict[Any, Any] = {
            vol.Required("name", default=defaults.get("name", "")): cv.string,
            vol.Optional(
                "icon", default=defaults.get("icon", DEFAULT_ICON)
            ): selector.IconSelector(),
            vol.Optional("description", default=defaults.get("description", "")): cv.string,
        }
        if offer_voice_sentences:
            schema_dict[
                vol.Optional(
                    "install_voice_sentences",
                    default=defaults.get("install_voice_sentences", False),
                )
            ] = cv.boolean

        return self.async_show_form(
            step_id="add_inventory",
            data_schema=vol.Schema(schema_dict),
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
    ) -> "OptionsFlowHandler":
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for inventory configuration."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options."""
        errors = {}
        is_global_entry = self._config_entry.data.get("entry_type") == "global"
        offer_voice_sentences = is_global_entry and can_offer_voice_sentences(self.hass)

        if user_input is not None:
            cleaned_name = await clean_inventory_name(self.hass, user_input["name"])

            if await self._async_name_exists_excluding_current(cleaned_name):
                errors["name"] = "name_exists"
            else:
                updated_data = {
                    **self._config_entry.data,
                    "name": cleaned_name,
                    "icon": user_input.get("icon", DEFAULT_ICON),
                    "description": user_input.get("description", ""),
                }

                self.hass.config_entries.async_update_entry(
                    self._config_entry,
                    data=updated_data,
                    title=cleaned_name,
                )

                await self._async_update_repository_metadata(updated_data)

                self.hass.bus.async_fire(
                    f"{DOMAIN}_updated_{self._config_entry.entry_id}",
                    {"action": "renamed", "new_name": cleaned_name},
                )

                if offer_voice_sentences and user_input.get("install_voice_sentences"):
                    await async_install_voice_sentences(self.hass)

                return self.async_create_entry(title="", data={})

        schema_dict: dict[Any, Any] = {
            vol.Required("name", default=self._config_entry.data.get("name", "")): cv.string,
            vol.Optional(
                "icon",
                default=self._config_entry.data.get("icon", DEFAULT_ICON),
            ): selector.IconSelector(),
            vol.Optional(
                "description",
                default=self._config_entry.data.get("description", ""),
            ): cv.string,
        }
        if offer_voice_sentences:
            schema_dict[
                vol.Optional(
                    "install_voice_sentences",
                    default=(user_input or {}).get("install_voice_sentences", False),
                )
            ] = cv.boolean

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
            description_placeholders={
                "current_name": self._config_entry.data.get("name", ""),
            },
        )

    async def _async_name_exists_excluding_current(self, name: str) -> bool:
        """Check if name exists in other entries."""
        all_entries = self.hass.config_entries.async_entries(DOMAIN)
        return any(
            entry.entry_id != self._config_entry.entry_id
            and entry.data.get("name", "").lower() == name.lower()
            for entry in all_entries
        )

    async def _async_update_repository_metadata(self, data: dict[str, Any]) -> None:
        """Mirror option changes into the SQLite repository."""
        domain_data = self.hass.data.get(DOMAIN)
        if not domain_data:
            return

        coordinator = (
            domain_data.get("coordinators", {}).get(self._config_entry.entry_id)
            if "coordinators" in domain_data
            else None
        )
        repository = domain_data.get("repository")

        if coordinator:
            await coordinator.async_upsert_inventory_metadata(
                inventory_id=self._config_entry.entry_id,
                name=data.get("name", self._config_entry.title or self._config_entry.entry_id),
                description=data.get("description", ""),
                icon=data.get("icon", DEFAULT_ICON),
                entry_type=data.get("entry_type", "inventory"),
                metadata=None,
            )
        elif repository:
            await repository.upsert_inventory(
                inventory_id=self._config_entry.entry_id,
                name=data.get("name", self._config_entry.title or self._config_entry.entry_id),
                description=data.get("description", ""),
                icon=data.get("icon", DEFAULT_ICON),
                entry_type=data.get("entry_type", "inventory"),
                metadata=None,
            )
