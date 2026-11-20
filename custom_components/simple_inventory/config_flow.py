"""Config flow."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping
from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState, ConfigFlowResult
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector, translation

from .const import (
    CONF_CREATE_GLOBAL,
    CONF_DESCRIPTION,
    CONF_ENTRY_TYPE,
    CONF_ICON,
    CONF_NAME,
    CONF_PANEL_ADMIN_ONLY,
    CONF_SHOW_PANEL,
    DEFAULT_INVENTORY_ICON,
    DOMAIN,
    ENTRY_TYPE_INVENTORY,
    GLOBAL_ENTRY_TITLE,
    match_key,
)
from .entries import is_global_entry
from .panel import async_sync_panel
from .voice_sentences import async_install_voice_sentences, can_offer_voice_sentences

_LOGGER = logging.getLogger(__name__)

GLOBAL_ENTRY_UNIQUE_ID = "global"
CONF_INSTALL_VOICE_SENTENCES = "install_voice_sentences"


def _is_usable_name(name: str) -> bool:
    """A cleaned inventory name must contain at least one letter or digit."""
    return any(char.isalnum() for char in name)


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


async def _async_validate_inventory_name(
    hass: HomeAssistant, raw_name: str, other_entries: Iterable[config_entries.ConfigEntry]
) -> tuple[str, str | None]:
    """Clean ``raw_name``; return it with the form error key, or None when it is valid."""
    cleaned = await clean_inventory_name(hass, raw_name)
    if not _is_usable_name(cleaned):
        return cleaned, "invalid_name"
    key = match_key(cleaned)
    if any(match_key(str(entry.data.get(CONF_NAME, ""))) == key for entry in other_entries):
        return cleaned, "name_exists"
    return cleaned, None


def _voice_sentences_field(defaults: Mapping[str, Any]) -> dict[Any, Any]:
    return {
        vol.Optional(
            CONF_INSTALL_VOICE_SENTENCES,
            default=defaults.get(CONF_INSTALL_VOICE_SENTENCES, False),
        ): cv.boolean
    }


def _inventory_schema(defaults: Mapping[str, Any], *, offer_voice_sentences: bool) -> vol.Schema:
    """The name/icon/description form shared by the config and options flows."""
    schema: dict[Any, Any] = {
        vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, "")): cv.string,
        vol.Optional(
            CONF_ICON, default=defaults.get(CONF_ICON, DEFAULT_INVENTORY_ICON)
        ): selector.IconSelector(),
        vol.Optional(CONF_DESCRIPTION, default=defaults.get(CONF_DESCRIPTION, "")): cv.string,
    }
    if offer_voice_sentences:
        schema.update(_voice_sentences_field(defaults))
    return vol.Schema(schema)


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
        errors: dict[str, str] = {}
        is_first_inventory = not self._global_entry_exists()
        offer_voice_sentences = is_first_inventory and can_offer_voice_sentences(self.hass)

        if user_input is not None:
            cleaned_name, error = await _async_validate_inventory_name(
                self.hass, user_input[CONF_NAME], self._async_current_entries()
            )
            if error:
                errors[CONF_NAME] = error
            else:
                if offer_voice_sentences and user_input.get(CONF_INSTALL_VOICE_SENTENCES):
                    await async_install_voice_sentences(self.hass)

                return self.async_create_entry(
                    title=cleaned_name,
                    data={
                        CONF_NAME: cleaned_name,
                        CONF_ICON: user_input.get(CONF_ICON) or DEFAULT_INVENTORY_ICON,
                        CONF_DESCRIPTION: user_input.get(CONF_DESCRIPTION, ""),
                        CONF_ENTRY_TYPE: ENTRY_TYPE_INVENTORY,
                        # Only the very first entry requests the global sensors, so a
                        # global entry the user deleted is not recreated by later adds.
                        CONF_CREATE_GLOBAL: not self._async_current_entries(),
                    },
                )

        return self.async_show_form(
            step_id="add_inventory",
            data_schema=_inventory_schema(
                user_input or {}, offer_voice_sentences=offer_voice_sentences
            ),
            errors=errors,
        )

    async def async_step_internal(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle internal creation of the (single) global entry."""
        await self.async_set_unique_id(GLOBAL_ENTRY_UNIQUE_ID)
        self._abort_if_unique_id_configured()
        # Global entries created before the unique_id existed have none set.
        if self._global_entry_exists():
            return self.async_abort(reason="already_configured")
        return self.async_create_entry(
            title=GLOBAL_ENTRY_TITLE,
            data=user_input or {},
        )

    def _global_entry_exists(self) -> bool:
        """Check if global config entry already exists."""
        return any(is_global_entry(entry) for entry in self._async_current_entries())

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "OptionsFlowHandler":
        """Get the options flow for this handler."""
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Inventory entries edit their name/icon/description; the global entry sets up the
    sidebar panel and offers the example voice sentences."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options."""
        if is_global_entry(self.config_entry):
            return await self.async_step_global_settings()

        entry = self.config_entry
        errors: dict[str, str] = {}
        if user_input is not None:
            other_entries = (
                other
                for other in self.hass.config_entries.async_entries(DOMAIN)
                if other.entry_id != entry.entry_id
            )
            cleaned_name, error = await _async_validate_inventory_name(
                self.hass, user_input[CONF_NAME], other_entries
            )
            if error:
                errors[CONF_NAME] = error
            else:
                # The entry's update listener reloads it: entities/device pick up the new
                # name and icon and setup mirrors the metadata into the repository.
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={
                        **entry.data,
                        CONF_NAME: cleaned_name,
                        CONF_ICON: user_input.get(CONF_ICON, DEFAULT_INVENTORY_ICON),
                        CONF_DESCRIPTION: user_input.get(CONF_DESCRIPTION, ""),
                    },
                    title=cleaned_name,
                )
                return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=_inventory_schema(entry.data, offer_voice_sentences=False),
            errors=errors,
            description_placeholders={"current_name": entry.data.get(CONF_NAME, "")},
        )

    async def async_step_global_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Sidebar panel settings, plus the bundled example voice sentences when offerable."""
        offer_voice_sentences = can_offer_voice_sentences(self.hass)
        if user_input is not None:
            if offer_voice_sentences and user_input.get(CONF_INSTALL_VOICE_SENTENCES):
                await async_install_voice_sentences(self.hass)
            panel_options = {
                CONF_SHOW_PANEL: bool(user_input.get(CONF_SHOW_PANEL, False)),
                CONF_PANEL_ADMIN_ONLY: bool(user_input.get(CONF_PANEL_ADMIN_ONLY, False)),
            }
            # Changed options reload the global entry, which registers or removes the panel.
            # Unchanged options fire no update listener, so re-sync here: saving again is how
            # the bundle-missing issue tells users to pick up a newly installed card.
            if (
                panel_options == dict(self.config_entry.options)
                and self.config_entry.state is ConfigEntryState.LOADED
            ):
                await async_sync_panel(self.hass, self.config_entry)
            return self.async_create_entry(title="", data=panel_options)

        options = self.config_entry.options
        schema: dict[Any, Any] = {
            vol.Optional(CONF_SHOW_PANEL, default=options.get(CONF_SHOW_PANEL, False)): cv.boolean,
            vol.Optional(
                CONF_PANEL_ADMIN_ONLY, default=options.get(CONF_PANEL_ADMIN_ONLY, False)
            ): cv.boolean,
        }
        if offer_voice_sentences:
            schema.update(_voice_sentences_field({}))
        return self.async_show_form(step_id="global_settings", data_schema=vol.Schema(schema))
