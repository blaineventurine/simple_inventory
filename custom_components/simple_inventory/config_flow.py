"""Config flow with proper Home Assistant icon picker support."""

import logging

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

DEFAULT_ICON = "mdi:package-variant"


class SimpleInventoryConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Simple Inventory."""

    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Handle the initial step."""
        return await self.async_step_add_inventory(user_input)

    async def async_step_add_inventory(self, user_input=None) -> FlowResult:
        """Handle adding a new inventory."""
        errors = {}

        if user_input is not None:
            if await self._async_name_exists(user_input["name"]):
                errors["name"] = "Inventory name already exists"
            else:
                icon = user_input.get("icon") or DEFAULT_ICON

                return self.async_create_entry(
                    title=user_input["name"],
                    data={
                        "name": user_input["name"],
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
                    vol.Optional(
                        "description", default=defaults.get("description", "")
                    ): cv.string,
                }
            ),
            errors=errors,
            description_placeholders={
                "icon_help": "Click the icon field to open the icon picker with all Material Design Icons"
            },
        )

    async def async_step_internal(self, user_input=None) -> FlowResult:
        """Handle internal creation of global entry."""
        return self.async_create_entry(
            title="All Items Expiring Soon",
            data=user_input,
        )

    def _global_entry_exists(self) -> bool:
        """Check if global config entry already exists."""
        existing_entries = self._async_current_entries()
        return any(
            entry.data.get("entry_type") == "global" for entry in existing_entries
        )

    async def _async_name_exists(self, name: str) -> bool:
        """Check if inventory name already exists."""
        existing_entries = self._async_current_entries()
        existing_names = [
            entry.data.get("name", "").lower() for entry in existing_entries
        ]
        return name.lower() in existing_names

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for inventory configuration."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        errors = {}

        if user_input is not None:
            if await self._async_name_exists_excluding_current(user_input["name"]):
                errors["name"] = "Inventory name already exists"
            else:
                new_data = {
                    "name": user_input["name"],
                    "icon": user_input.get("icon", DEFAULT_ICON),
                    "description": user_input.get("description", ""),
                }

                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data=new_data,
                    title=user_input["name"],
                )

                self.hass.bus.async_fire(
                    f"{DOMAIN}_updated_{self.config_entry.entry_id}",
                    {"action": "renamed", "new_name": user_input["name"]},
                )

                return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "name", default=self.config_entry.data.get("name", "")
                    ): cv.string,
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
                "icon_help": "Click the icon field to browse all available icons",
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
