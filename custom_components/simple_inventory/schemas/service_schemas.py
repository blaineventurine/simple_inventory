"""Service call validation schemas."""

import voluptuous as vol
from homeassistant.helpers import config_validation as cv

from ..const import (
    DEFAULT_AUTO_ADD_TO_LIST_QUANTITY,
    DEFAULT_EXPIRY_ALERT_DAYS,
    DEFAULT_QUANTITY,
)

INVENTORY_ID = vol.Required("inventory_id")
NAME = vol.Required("name")
OLD_NAME = vol.Required("old_name")

ITEM_SCHEMA = {
    NAME: cv.string,
    vol.Optional("auto_add_enabled"): cv.boolean,
    vol.Optional("auto_add_id_to_description_enabled"): cv.boolean,
    vol.Optional("auto_add_to_list_quantity"): vol.All(
        vol.Coerce(int), vol.Range(min=DEFAULT_AUTO_ADD_TO_LIST_QUANTITY)
    ),
    vol.Optional("category"): cv.string,
    vol.Optional("description"): cv.string,
    vol.Optional("expiry_alert_days"): vol.All(
        vol.Coerce(int), vol.Range(min=DEFAULT_EXPIRY_ALERT_DAYS, max=365)
    ),
    vol.Optional("expiry_date"): cv.string,
    vol.Optional("location"): cv.string,
    vol.Optional("quantity"): vol.All(vol.Coerce(int), vol.Range(min=0)),
    vol.Optional("todo_list"): cv.string,
    vol.Optional("unit"): cv.string,
}

ADD_ITEM_SCHEMA = vol.Schema({INVENTORY_ID: cv.string, **ITEM_SCHEMA})

UPDATE_ITEM_SCHEMA = vol.Schema({INVENTORY_ID: cv.string, OLD_NAME: cv.string, **ITEM_SCHEMA})

REMOVE_ITEM_SCHEMA = vol.Schema(
    {
        INVENTORY_ID: cv.string,
        NAME: cv.string,
    }
)

QUANTITY_UPDATE_SCHEMA = vol.Schema(
    {
        INVENTORY_ID: cv.string,
        NAME: cv.string,
        vol.Optional("amount", default=DEFAULT_QUANTITY): vol.All(
            vol.Coerce(int), vol.Range(min=1)
        ),
    }
)


# Accepts either inventory_id OR inventory_name
def validate_get_items(data: dict) -> dict:
    """Validate that exactly one of inventory_id or inventory_name is provided."""
    has_id = "inventory_id" in data and data["inventory_id"]
    has_name = "inventory_name" in data and data["inventory_name"]

    if not (has_id or has_name):
        raise vol.Invalid("Either 'inventory_id' or 'inventory_name' is required")
    if has_id and has_name:
        raise vol.Invalid("Cannot specify both 'inventory_id' and 'inventory_name'")

    return data


GET_ITEMS_SCHEMA = vol.Schema(
    vol.All(
        {
            vol.Optional("inventory_id"): cv.string,
            vol.Optional("inventory_name"): cv.string,
        },
        validate_get_items,
    )
)

GET_ALL_ITEMS_SCHEMA = vol.Schema({})

ALL_SCHEMAS = {
    "add_item": ADD_ITEM_SCHEMA,
    "remove_item": REMOVE_ITEM_SCHEMA,
    "update_item": UPDATE_ITEM_SCHEMA,
    "increment_item": QUANTITY_UPDATE_SCHEMA,
    "decrement_item": QUANTITY_UPDATE_SCHEMA,
    "get_items": GET_ITEMS_SCHEMA,
    "get_items_from_all_inventories": GET_ALL_ITEMS_SCHEMA,
}
