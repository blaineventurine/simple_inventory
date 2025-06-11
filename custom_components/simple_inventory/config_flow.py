"""Config flow for Simple Inventory integration."""
import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

ICON_SUGGESTIONS = {
    "bath": "mdi:shower",  # Alternative
    "bathroom": "mdi:shower",
    "book": "mdi:book-open-page-variant",  # Singular form
    "books": "mdi:book-open-page-variant",
    "cleaning": "mdi:spray-bottle",
    "clothes": "mdi:tshirt-crew",
    "clothing": "mdi:tshirt-crew",  # Alternative
    "craft": "mdi:palette",
    "crafts": "mdi:palette",  # Plural form
    "default": "mdi:package-variant",
    "electronic": "mdi:memory",  # Singular form
    "electronics": "mdi:memory",
    "freezer": "mdi:snowflake",
    "fridge": "mdi:fridge",
    "garage": "mdi:garage",
    "garden": "mdi:flower",
    "gardening": "mdi:flower",  # Alternative
    "laundry": "mdi:washing-machine",
    "medication": "mdi:pill",  # Alternative word
    "medicine": "mdi:pill",
    "office": "mdi:briefcase",
    "pantry": "mdi:food",
    "pet": "mdi:paw",
    "pets": "mdi:paw",  # Plural form
    "pills": "mdi:pill",  # Plural form
    "tool": "mdi:hammer-wrench",  # Add singular form explicitly
    "tools": "mdi:hammer-wrench",
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
            existing_entries = self._async_current_entries()
            existing_names = [entry.data.get(
                "name", "").lower() for entry in existing_entries]

            if user_input["name"].lower() in existing_names:
                errors["name"] = "name_exists"
            else:
                # Auto-suggest icon if none provided
                suggested_icon = self._suggest_icon(user_input["name"])
                icon = user_input.get("icon") or suggested_icon

                return self.async_create_entry(
                    title=user_input["name"],
                    data={
                        "name": user_input["name"],
                        "icon": icon,
                        "description": user_input.get("description", ""),
                    }
                )

        name_default = user_input.get("name", "") if user_input else ""
        icon_default = user_input.get("icon", "") if user_input else ""
        desc_default = user_input.get("description", "") if user_input else ""

        return self.async_show_form(
            step_id="add_inventory",
            data_schema=vol.Schema({
                vol.Required("name", default=name_default): cv.string,
                vol.Optional("icon", default=icon_default): cv.string,
                vol.Optional("description", default=desc_default): cv.string,
            }),
            errors=errors,
        )

    def _suggest_icon(self, name: str) -> str:
        """Suggest an icon based on the inventory name."""
        name_lower = name.lower()

        for keyword, icon in ICON_SUGGESTIONS.items():
            if keyword in name_lower:
                return icon

        for keyword, icon in ICON_SUGGESTIONS.items():
            # These end in 's' but aren't simple plurals
            if keyword in ['electronics', 'clothes']:
                continue

            if keyword.endswith('s') and len(keyword) > 1:
                singular = keyword[:-1]
                if singular in name_lower:
                    return icon

            elif not keyword.endswith('s'):
                plural = keyword + 's'
                if plural in name_lower:
                    return icon

        irregular_plurals = {
            'child': 'children',
            'children': 'child',
            'person': 'people',
            'people': 'person',
        }

        for keyword, icon in ICON_SUGGESTIONS.items():
            if keyword in irregular_plurals:
                if irregular_plurals[keyword] in name_lower:
                    return icon

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
            new_data = {**self.config_entry.data}
            new_data.update(user_input)

            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data=new_data,
                title=user_input.get("name", self.config_entry.title)
            )

            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(
                    "Name",
                    default=self.config_entry.data.get("name", "")
                ): cv.string,
                vol.Optional(
                    "Icon",
                    default=self.config_entry.data.get(
                        "icon", "mdi:package-variant")
                ): cv.string,
                vol.Optional(
                    "Description",
                    default=self.config_entry.data.get("description", "")
                ): cv.string,
            }),
        )
