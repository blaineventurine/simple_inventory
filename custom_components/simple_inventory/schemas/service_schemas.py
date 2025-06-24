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
    vol.Optional("quantity"): vol.All(vol.Coerce(int), vol.Range(min=0)),
    vol.Optional("unit"): cv.string,
    vol.Optional("category"): cv.string,
    vol.Optional("expiry_date"): cv.string,
    vol.Optional("auto_add_enabled"): cv.boolean,
    vol.Optional("expiry_alert_days"): vol.All(
        vol.Coerce(int), vol.Range(min=DEFAULT_EXPIRY_ALERT_DAYS, max=365)
    ),
    vol.Optional("auto_add_to_list_quantity"): vol.All(
        vol.Coerce(int), vol.Range(min=DEFAULT_AUTO_ADD_TO_LIST_QUANTITY)
    ),
    vol.Optional("todo_list"): cv.string,
}

ADD_ITEM_SCHEMA = vol.Schema({INVENTORY_ID: cv.string, **ITEM_SCHEMA})

UPDATE_ITEM_SCHEMA = vol.Schema(
    {INVENTORY_ID: cv.string, OLD_NAME: cv.string, **ITEM_SCHEMA}
)

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

ALL_SCHEMAS = {
    "add_item": ADD_ITEM_SCHEMA,
    "remove_item": REMOVE_ITEM_SCHEMA,
    "update_item": UPDATE_ITEM_SCHEMA,
    "increment_item": QUANTITY_UPDATE_SCHEMA,
    "decrement_item": QUANTITY_UPDATE_SCHEMA,
}
