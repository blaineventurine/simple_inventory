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

# Simple keyword-to-icon suggestions for auto-suggestion only
ICON_SUGGESTIONS = {
    "kitchen": "mdi:chef-hat",
    "bathroom": "mdi:shower",
    "garage": "mdi:garage",
    "tool": "mdi:hammer-wrench",
    "medicine": "mdi:pill",
    "clean": "mdi:spray-bottle",
    "office": "mdi:briefcase",
    "pet": "mdi:paw",
    "garden": "mdi:flower",
    "food": "mdi:food",
    "book": "mdi:book-open-page-variant",
    "pantry": "mdi:food",
    "fridge": "mdi:fridge",
    "laundry": "mdi:washing-machine",
    "craft": "mdi:palette",
    "electronic": "mdi:memory",
}

DEFAULT_ICON = "mdi:package-variant"


def suggest_icon_from_name(name: str) -> str:
    """Suggest an icon based on inventory name."""
    name_lower = name.lower().strip()

    for keyword, icon in ICON_SUGGESTIONS.items():
        if keyword in name_lower:
            return icon

    return DEFAULT_ICON


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
                errors["name"] = "name_exists"
            else:
                icon = user_input.get("icon") or suggest_icon_from_name(
                    user_input["name"]
                )

                return self.async_create_entry(
                    title=user_input["name"],
                    data={
                        "name": user_input["name"],
                        "icon": icon,
                        "description": user_input.get("description", ""),
                    },
                )

        # Preserve form data on errors
        defaults = user_input or {}
        suggested_icon = (
            suggest_icon_from_name(defaults.get("name", ""))
            if defaults.get("name")
            else DEFAULT_ICON
        )

        return self.async_show_form(
            step_id="add_inventory",
            data_schema=vol.Schema(
                {
                    vol.Required("name", default=defaults.get("name", "")): cv.string,
                    vol.Optional(
                        "icon", default=defaults.get("icon", suggested_icon)
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
                errors["name"] = "name_exists"
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
        for entry in all_entries:
            if entry.entry_id != self.config_entry.entry_id:
                if entry.data.get("name", "").lower() == name.lower():
                    return True
        return False
