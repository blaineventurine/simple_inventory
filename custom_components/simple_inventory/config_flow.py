"""Config flow for Simple Inventory integration."""
import logging
import voluptuous as vol
from typing import Any, Dict

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Icon suggestions for common inventory types
ICON_SUGGESTIONS = {
    "freezer": "mdi:snowflake",
    "fridge": "mdi:fridge",
    "pantry": "mdi:food",
    "cleaning": "mdi:spray-bottle",
    "tools": "mdi:hammer-wrench",
    "medicine": "mdi:pill",
    "office": "mdi:briefcase",
    "garage": "mdi:garage",
    "bathroom": "mdi:shower",
    "laundry": "mdi:washing-machine",
    "garden": "mdi:flower",
    "pet": "mdi:paw",
    "craft": "mdi:palette",
    "electronics": "mdi:memory",
    "books": "mdi:book-open-page-variant",
    "clothes": "mdi:tshirt-crew",
    "default": "mdi:package-variant"
}


class SimpleInventoryConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Simple Inventory."""

    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Handle the initial step."""
        return self.async_show_menu(
            menu_options={
                "add_inventory": "Add New Inventory",
                "manage_inventories": "Manage Existing Inventories"
            })

    async def async_step_add_inventory(self, user_input=None) -> FlowResult:
        """Handle adding a new inventory."""
        errors = {}

        if user_input is not None:
            # Check if inventory name already exists
            existing_entries = self._async_current_entries()
            existing_names = [entry.data.get(
                "name", "").lower() for entry in existing_entries]

            if user_input["name"].lower() in existing_names:
                errors["name"] = "name_exists"
            else:
                # Auto-suggest icon based on name if not provided
                suggested_icon = self._suggest_icon(user_input["name"])
                icon = user_input.get("icon", suggested_icon)

                return self.async_create_entry(
                    title=user_input["name"],
                    data={
                        "name": user_input["name"],
                        "icon": icon,
                        "description": user_input.get("description", ""),
                    }
                )

        # Show form for creating new inventory
        return self.async_show_form(
            step_id="add_inventory",
            data_schema=vol.Schema({
                vol.Required("name"): cv.string,
                vol.Optional("icon"): cv.string,
                vol.Optional("description"): cv.string,
            }),
            errors=errors,
            description_placeholders={
                "name_examples": "Examples: Kitchen Freezer, Garage Fridge, Pantry, Tool Shed, Medicine Cabinet",
                "icon_examples": "Examples: mdi:snowflake, mdi:fridge, mdi:food, mdi:hammer-wrench, mdi:pill",
                "icon_help": "Leave blank for auto-suggestion based on name"
            }
        )

    def _suggest_icon(self, name: str) -> str:
        """Suggest an icon based on the inventory name."""
        name_lower = name.lower()

        # Check for keywords in the name
        for keyword, icon in ICON_SUGGESTIONS.items():
            if keyword in name_lower:
                return icon

        # Default icon
        return ICON_SUGGESTIONS["default"]

    async def async_step_manage_inventories(self, user_input=None) -> FlowResult:
        """Handle managing existing inventories."""
        existing_entries = self._async_current_entries()

        if not existing_entries:
            return self.async_show_form(
                step_id="manage_inventories",
                data_schema=vol.Schema({}),
                description_placeholders={
                    "message": "No inventories created yet. Use 'Add Inventory' to create your first one."
                }
            )

        # Show list of existing inventories with options to configure or delete
        inventory_options = {
            entry.entry_id: f"{
                entry.title} - {len(self._get_inventory_items(entry.entry_id))} items"
            for entry in existing_entries
        }

        if user_input is not None:
            selected_entry_id = user_input["inventory"]
            return await self.async_step_configure_inventory(selected_entry_id)

        return self.async_show_form(
            step_id="manage_inventories",
            data_schema=vol.Schema({
                vol.Required("inventory"): vol.In(inventory_options),
            }),
            description_placeholders={
                "action": "Select an inventory to configure or delete"
            }
        )

    async def async_step_configure_inventory(self, entry_id: str, user_input=None) -> FlowResult:
        """Configure or delete a specific inventory."""
        entry = self.hass.config_entries.async_get_entry(entry_id)
        if not entry:
            return self.async_abort(reason="inventory_not_found")

        if user_input is not None:
            action = user_input["action"]

            if action == "delete":
                return await self.async_step_confirm_delete(entry_id)
            elif action == "configure":
                # Redirect to options flow
                return self.async_external_step(step_id="configure", url=f"/config/integrations/configure/{entry_id}")

        return self.async_show_form(
            step_id="configure_inventory",
            data_schema=vol.Schema({
                vol.Required("action"): vol.In({
                    "configure": "Configure settings",
                    "delete": "Delete inventory"
                }),
            }),
            description_placeholders={
                "inventory_name": entry.title,
                "item_count": str(len(self._get_inventory_items(entry_id)))
            }
        )

    async def async_step_confirm_delete(self, entry_id: str, user_input=None) -> FlowResult:
        """Confirm deletion of an inventory."""
        entry = self.hass.config_entries.async_get_entry(entry_id)
        if not entry:
            return self.async_abort(reason="inventory_not_found")

        if user_input is not None:
            if user_input["confirm"]:
                # Delete the config entry
                await self.hass.config_entries.async_remove(entry_id)
                return self.async_create_entry(
                    title="",
                    data={},
                    description="Inventory deleted successfully"
                )
            else:
                return await self.async_step_manage_inventories()

        item_count = len(self._get_inventory_items(entry_id))

        return self.async_show_form(
            step_id="confirm_delete",
            data_schema=vol.Schema({
                vol.Required("confirm", default=False): cv.boolean,
            }),
            description_placeholders={
                "inventory_name": entry.title,
                "item_count": str(item_count),
                "warning": f"This will permanently delete '{entry.title}' and all {item_count} items in it."
            }
        )

    def _get_inventory_items(self, entry_id: str) -> list:
        """Get items for a specific inventory."""
        # Access the coordinator data if available
        if DOMAIN in self.hass.data and "coordinator" in self.hass.data[DOMAIN]:
            coordinator = self.hass.data[DOMAIN]["coordinator"]
            items = coordinator.get_all_items(entry_id)
            return [{"name": name, **details} for name, details in items.items()]
        return []

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
        if user_input is not None:
            # Update the config entry data
            new_data = {**self.config_entry.data}
            new_data.update(user_input)

            # Save options separately
            new_options = {**self.config_entry.options}
            if "expiry_threshold" in user_input:
                new_options["expiry_threshold"] = user_input["expiry_threshold"]

            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data=new_data,
                options=new_options,
                title=user_input.get("name", self.config_entry.title)
            )

            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(
                    "name",
                    default=self.config_entry.data.get("name", "")
                ): cv.string,
                vol.Optional(
                    "icon",
                    default=self.config_entry.data.get(
                        "icon", "mdi:package-variant")
                ): cv.string,
                vol.Optional(
                    "description",
                    default=self.config_entry.data.get("description", "")
                ): cv.string,
                vol.Optional(
                    "expiry_threshold",
                    default=self.config_entry.options.get(
                        "expiry_threshold", 7)
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=30))
            }),
            description_placeholders={
                "current_name": self.config_entry.title,
                "icon_examples": "Examples: mdi:snowflake, mdi:fridge, mdi:food, mdi:hammer-wrench",
                "threshold_help": "Number of days in advance to warn about expiring items"
            }
        )
