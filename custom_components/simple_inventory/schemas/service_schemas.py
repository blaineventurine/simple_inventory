"""Service call validation schemas."""
import voluptuous as vol
from homeassistant.helpers import config_validation as cv

INVENTORY_ID_FIELD = vol.Required("inventory_id")
NAME_FIELD = vol.Required("name")
OPTIONAL_NAME_FIELD = vol.Optional("name")
OPTIONAL_QUANTITY_FIELD = vol.Optional("quantity", default=1)
OPTIONAL_UNIT_FIELD = vol.Optional("unit", default="")
OPTIONAL_CATEGORY_FIELD = vol.Optional("category", default="")
OPTIONAL_EXPIRY_DATE_FIELD = vol.Optional("expiry_date", default="")
OPTIONAL_AUTO_ADD_ENABLED_FIELD = vol.Optional(
    "auto_add_enabled", default=False)
OPTIONAL_THRESHOLD_FIELD = vol.Optional("threshold", default=0)
OPTIONAL_TODO_LIST_FIELD = vol.Optional("todo_list", default="")

ITEM_SCHEMA = vol.Schema({
    INVENTORY_ID_FIELD: cv.string,
    NAME_FIELD: cv.string,
    OPTIONAL_QUANTITY_FIELD: cv.positive_int,
    OPTIONAL_UNIT_FIELD: cv.string,
    OPTIONAL_CATEGORY_FIELD: cv.string,
    OPTIONAL_EXPIRY_DATE_FIELD: cv.string,
    OPTIONAL_AUTO_ADD_ENABLED_FIELD: cv.boolean,
    OPTIONAL_THRESHOLD_FIELD: cv.positive_int,
    OPTIONAL_TODO_LIST_FIELD: cv.string,
})

REMOVE_SCHEMA = vol.Schema({
    INVENTORY_ID_FIELD: cv.string,
    NAME_FIELD: cv.string,
})

UPDATE_ITEM_SCHEMA = vol.Schema({
    INVENTORY_ID_FIELD: cv.string,
    vol.Required("old_name"): cv.string,
    NAME_FIELD: cv.string,
    vol.Optional("quantity"): vol.All(vol.Coerce(int), vol.Range(min=0)),
    vol.Optional("unit"): cv.string,
    vol.Optional("category"): cv.string,
    vol.Optional("expiry_date"): cv.string,
    vol.Optional("auto_add_enabled"): cv.boolean,
    vol.Optional("threshold"): vol.All(vol.Coerce(int), vol.Range(min=0)),
    vol.Optional("todo_list"): cv.string,
})

QUANTITY_UPDATE_SCHEMA = vol.Schema({
    INVENTORY_ID_FIELD: cv.string,
    NAME_FIELD: cv.string,
    vol.Optional("amount", default=1): cv.positive_int,
})

UPDATE_SETTINGS_SCHEMA = vol.Schema({
    INVENTORY_ID_FIELD: cv.string,
    NAME_FIELD: cv.string,
    vol.Optional("auto_add_enabled"): cv.boolean,
    vol.Optional("threshold"): vol.All(vol.Coerce(int), vol.Range(min=0)),
    vol.Optional("todo_list"): cv.string,
})

SET_EXPIRY_THRESHOLD_SCHEMA = vol.Schema({
    vol.Required("threshold_days"): vol.All(vol.Coerce(int), vol.Range(min=1, max=30))
})

INVENTORY_SCHEMAS = {
    "add_item": ITEM_SCHEMA,
    "remove_item": REMOVE_SCHEMA,
    "update_item": UPDATE_ITEM_SCHEMA,
}

QUANTITY_SCHEMAS = {
    "increment_item": QUANTITY_UPDATE_SCHEMA,
    "decrement_item": QUANTITY_UPDATE_SCHEMA,
}

SETTINGS_SCHEMAS = {
    "update_item_settings": UPDATE_SETTINGS_SCHEMA,
    "set_expiry_threshold": SET_EXPIRY_THRESHOLD_SCHEMA,
}

ALL_SCHEMAS = {
    **INVENTORY_SCHEMAS,
    **QUANTITY_SCHEMAS,
    **SETTINGS_SCHEMAS,
}
