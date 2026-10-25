"""Service call validation schemas."""

from dataclasses import dataclass, field
from typing import Any

import voluptuous as vol
from homeassistant.core import SupportsResponse
from homeassistant.helpers import config_validation as cv

from ..const import (
    DEFAULT_AUTO_ADD_TO_LIST_QUANTITY,
    DEFAULT_DESIRED_QUANTITY,
    DEFAULT_EXPIRY_ALERT_DAYS,
    DEFAULT_QUANTITY,
    SERVICE_ADD_ITEM,
    SERVICE_CLEAR_ITEM_IMAGE,
    SERVICE_DECREMENT_ITEM,
    SERVICE_GET_ALL_ITEMS,
    SERVICE_GET_INVENTORY_CONSUMPTION_RATES,
    SERVICE_GET_ITEM_CONSUMPTION_RATES,
    SERVICE_GET_ITEMS,
    SERVICE_INCREMENT_ITEM,
    SERVICE_LOOKUP_BARCODE_PRODUCT,
    SERVICE_LOOKUP_BY_BARCODE,
    SERVICE_REMOVE_BATCH,
    SERVICE_REMOVE_ITEM,
    SERVICE_SCAN_BARCODE,
    SERVICE_SET_ITEM_IMAGE_FROM_BARCODE,
    SERVICE_SET_ITEM_IMAGE_FROM_MEDIA,
    SERVICE_TRANSFER_ITEM,
    SERVICE_UPDATE_BATCH,
    SERVICE_UPDATE_ITEM,
)

INVENTORY_ID = vol.Required("inventory_id")
INVENTORY_ID_OPTIONAL = vol.Optional("inventory_id")
INVENTORY_NAME = vol.Optional("inventory_name")
NAME = vol.Required("name")
OLD_NAME = vol.Required("old_name")

# Item names are stored stripped; whitespace-only names are rejected up front.
ITEM_NAME = vol.All(cv.string, str.strip, vol.Length(min=1))
OPTIONAL_ITEM_NAME = vol.All(cv.string, str.strip)
TODO_LIST = vol.Any("", cv.entity_domain("todo"))
# "" = default icon; otherwise HA's "prefix:name" form (e.g. mdi:apple).
ICON = vol.All(
    cv.string, str.strip, vol.Any("", cv.icon, msg='icon must be empty or "prefix:name"')
)


def _require_inventory_id_or_name(data: dict) -> dict:
    """Validate that exactly one of inventory_id or inventory_name is provided."""
    has_id = "inventory_id" in data and data["inventory_id"]
    has_name = "inventory_name" in data and data["inventory_name"]

    if not (has_id or has_name):
        raise vol.Invalid("Either 'inventory_id' or 'inventory_name' is required")
    if has_id and has_name:
        raise vol.Invalid("Cannot specify both 'inventory_id' and 'inventory_name'")

    return data


def _iso_date(value: Any) -> str:
    """YYYY-MM-DD string (empty allowed for 'no expiry')."""
    text = cv.string(value).strip()
    if text == "":
        return ""
    return cv.date(text).isoformat()


ISO_DATE = _iso_date

_BATCH_ADD_FIELDS = {
    vol.Optional("expiry_date"): ISO_DATE,
    vol.Optional("location"): cv.string,
    vol.Optional("purchased_at"): vol.All(ISO_DATE, vol.Length(min=10)),
}
_BATCH_TAKE_FIELDS = {
    vol.Optional("location"): cv.string,
    vol.Optional("batch_id"): cv.string,
}


ITEM_SCHEMA = {
    NAME: ITEM_NAME,
    vol.Optional("auto_add_enabled"): cv.boolean,
    vol.Optional("auto_add_id_to_description_enabled"): cv.boolean,
    vol.Optional("auto_add_to_list_quantity"): vol.All(
        vol.Coerce(float), vol.Range(min=DEFAULT_AUTO_ADD_TO_LIST_QUANTITY)
    ),
    vol.Optional("aliases"): cv.string,
    vol.Optional("barcode"): cv.string,
    vol.Optional("category"): cv.string,
    vol.Optional("description"): cv.string,
    vol.Optional("desired_quantity"): vol.All(
        vol.Coerce(float), vol.Range(min=DEFAULT_DESIRED_QUANTITY)
    ),
    vol.Optional("expiry_alert_days"): vol.All(
        vol.Coerce(int), vol.Range(min=DEFAULT_EXPIRY_ALERT_DAYS, max=365)
    ),
    vol.Optional("expiry_date"): ISO_DATE,
    vol.Optional("icon"): ICON,
    vol.Optional("location"): cv.string,
    vol.Optional("quantity"): vol.All(vol.Coerce(float), vol.Range(min=0)),
    vol.Optional("todo_list"): TODO_LIST,
    vol.Optional("todo_quantity_placement"): vol.In(["name", "description", "none"]),
    vol.Optional("unit"): cv.string,
    vol.Optional("price"): vol.All(vol.Coerce(float), vol.Range(min=0)),
}

ADD_ITEM_SCHEMA = vol.Schema(
    vol.All(
        {INVENTORY_ID_OPTIONAL: cv.string, INVENTORY_NAME: cv.string, **ITEM_SCHEMA},
        _require_inventory_id_or_name,
    )
)

UPDATE_ITEM_SCHEMA = vol.Schema(
    vol.All(
        {
            INVENTORY_ID_OPTIONAL: cv.string,
            INVENTORY_NAME: cv.string,
            OLD_NAME: ITEM_NAME,
            **ITEM_SCHEMA,
        },
        _require_inventory_id_or_name,
    )
)


def _require_name_or_barcode(data: dict) -> dict:
    """Validate that at least one of name or barcode is provided."""
    has_name = "name" in data and data["name"]
    has_barcode = "barcode" in data and data["barcode"]
    if not (has_name or has_barcode):
        raise vol.Invalid("At least one of 'name' or 'barcode' is required")
    return data


REMOVE_ITEM_SCHEMA = vol.Schema(
    vol.All(
        {
            INVENTORY_ID_OPTIONAL: cv.string,
            INVENTORY_NAME: cv.string,
            vol.Optional("name"): OPTIONAL_ITEM_NAME,
            vol.Optional("barcode"): cv.string,
        },
        _require_name_or_barcode,
        _require_inventory_id_or_name,
    )
)

_QUANTITY_FIELDS = {
    INVENTORY_ID_OPTIONAL: cv.string,
    INVENTORY_NAME: cv.string,
    vol.Optional("name"): OPTIONAL_ITEM_NAME,
    vol.Optional("barcode"): cv.string,
    vol.Optional("amount", default=DEFAULT_QUANTITY): vol.All(
        vol.Coerce(float), vol.Range(min=0, min_included=False)
    ),
    vol.Optional("price"): vol.All(vol.Coerce(float), vol.Range(min=0)),
}

INCREMENT_SCHEMA = vol.Schema(
    vol.All(
        _QUANTITY_FIELDS | _BATCH_ADD_FIELDS,
        _require_name_or_barcode,
        _require_inventory_id_or_name,
    )
)

DECREMENT_SCHEMA = vol.Schema(
    vol.All(
        _QUANTITY_FIELDS | _BATCH_TAKE_FIELDS,
        _require_name_or_barcode,
        _require_inventory_id_or_name,
    )
)

GET_ITEMS_SCHEMA = vol.Schema(
    vol.All(
        {
            vol.Optional("inventory_id"): cv.string,
            vol.Optional("inventory_name"): cv.string,
        },
        _require_inventory_id_or_name,
    )
)

GET_ALL_ITEMS_SCHEMA = vol.Schema({})

GET_INVENTORY_CONSUMPTION_RATES_SCHEMA = vol.Schema(
    {
        INVENTORY_ID: cv.string,
        vol.Optional("window_days"): vol.All(vol.Coerce(int), vol.Range(min=1)),
    }
)

GET_ITEM_CONSUMPTION_RATES_SCHEMA = vol.Schema(
    {
        INVENTORY_ID: cv.string,
        NAME: ITEM_NAME,
        vol.Optional("window_days"): vol.All(vol.Coerce(int), vol.Range(min=1)),
    }
)

LOOKUP_BY_BARCODE_SCHEMA = vol.Schema(
    {
        vol.Required("barcode"): cv.string,
    }
)

LOOKUP_BARCODE_PRODUCT_SCHEMA = vol.Schema(
    {
        vol.Required("barcode"): cv.string,
    }
)

SCAN_BARCODE_SCHEMA = vol.Schema(
    {
        vol.Required("barcode"): cv.string,
        vol.Required("action"): vol.In(["increment", "decrement", "lookup"]),
        vol.Optional("amount", default=1): vol.All(
            vol.Coerce(float), vol.Range(min=0, min_included=False)
        ),
        vol.Optional("inventory_id"): cv.string,
        vol.Optional("price"): vol.All(vol.Coerce(float), vol.Range(min=0)),
    }
    | _BATCH_ADD_FIELDS
    | _BATCH_TAKE_FIELDS
)

UPDATE_BATCH_SCHEMA = vol.Schema(
    vol.All(
        {
            INVENTORY_ID_OPTIONAL: cv.string,
            INVENTORY_NAME: cv.string,
            vol.Required("batch_id"): cv.string,
            vol.Optional("quantity"): vol.All(vol.Coerce(float), vol.Range(min=0)),
            vol.Optional("expiry_date"): ISO_DATE,
            vol.Optional("location"): cv.string,
            vol.Optional("unit_price"): vol.All(vol.Coerce(float), vol.Range(min=0)),
            vol.Optional("purchased_at"): vol.All(ISO_DATE, vol.Length(min=10)),
        },
        _require_inventory_id_or_name,
    )
)

REMOVE_BATCH_SCHEMA = vol.Schema(
    vol.All(
        {
            INVENTORY_ID_OPTIONAL: cv.string,
            INVENTORY_NAME: cv.string,
            vol.Required("batch_id"): cv.string,
        },
        _require_inventory_id_or_name,
    )
)

TRANSFER_ITEM_SCHEMA = vol.Schema(
    vol.All(
        {
            INVENTORY_ID_OPTIONAL: cv.string,
            INVENTORY_NAME: cv.string,
            vol.Optional("name"): OPTIONAL_ITEM_NAME,
            vol.Optional("barcode"): cv.string,
            vol.Required("to_location"): vol.All(cv.string, str.strip, vol.Length(min=1)),
            vol.Optional("amount"): vol.All(
                vol.Coerce(float), vol.Range(min=0, min_included=False)
            ),
            vol.Optional("from_location"): cv.string,
            vol.Optional("batch_id"): cv.string,
        },
        _require_name_or_barcode,
        _require_inventory_id_or_name,
    )
)

# Identifies one item: an inventory (id or name) plus the item's name or barcode.
_ITEM_REF_FIELDS = {
    INVENTORY_ID_OPTIONAL: cv.string,
    INVENTORY_NAME: cv.string,
    vol.Optional("name"): OPTIONAL_ITEM_NAME,
    vol.Optional("barcode"): cv.string,
}


def _item_ref_schema(fields: dict[Any, Any]) -> vol.Schema:
    return vol.Schema(
        vol.All(
            {**_ITEM_REF_FIELDS, **fields},
            _require_name_or_barcode,
            _require_inventory_id_or_name,
        )
    )


SET_ITEM_IMAGE_FROM_BARCODE_SCHEMA = _item_ref_schema(
    {vol.Optional("lookup_barcode"): vol.All(cv.string, str.strip)}
)
SET_ITEM_IMAGE_FROM_MEDIA_SCHEMA = _item_ref_schema(
    {
        vol.Required("media_content_id"): vol.All(
            cv.string, vol.Match(r"^media-source://", msg="must be a media-source:// id")
        )
    }
)
CLEAR_ITEM_IMAGE_SCHEMA = _item_ref_schema({})


@dataclass(frozen=True)
class ServiceSpec:
    """One service: its schema, whether it can respond, and its ServiceHandler method."""

    name: str
    # vol.Schema defines __eq__ without __hash__; keep it out of eq/hash so specs hash.
    schema: vol.Schema = field(compare=False)
    response: SupportsResponse = SupportsResponse.NONE

    @property
    def handler(self) -> str:
        """Name of the ServiceHandler coroutine method that serves this service."""
        return f"async_{self.name}"


_OPTIONAL = SupportsResponse.OPTIONAL

# Every service this integration registers (and unregisters). services.yaml and the
# translation files must document exactly these (tests/test_service_registry.py).
SERVICES: tuple[ServiceSpec, ...] = (
    ServiceSpec(SERVICE_ADD_ITEM, ADD_ITEM_SCHEMA),
    ServiceSpec(SERVICE_REMOVE_ITEM, REMOVE_ITEM_SCHEMA),
    ServiceSpec(SERVICE_UPDATE_ITEM, UPDATE_ITEM_SCHEMA),
    ServiceSpec(SERVICE_INCREMENT_ITEM, INCREMENT_SCHEMA),
    ServiceSpec(SERVICE_DECREMENT_ITEM, DECREMENT_SCHEMA),
    ServiceSpec(SERVICE_GET_ITEMS, GET_ITEMS_SCHEMA, _OPTIONAL),
    ServiceSpec(SERVICE_GET_ALL_ITEMS, GET_ALL_ITEMS_SCHEMA, _OPTIONAL),
    ServiceSpec(
        SERVICE_GET_INVENTORY_CONSUMPTION_RATES, GET_INVENTORY_CONSUMPTION_RATES_SCHEMA, _OPTIONAL
    ),
    ServiceSpec(SERVICE_GET_ITEM_CONSUMPTION_RATES, GET_ITEM_CONSUMPTION_RATES_SCHEMA, _OPTIONAL),
    ServiceSpec(SERVICE_LOOKUP_BY_BARCODE, LOOKUP_BY_BARCODE_SCHEMA, _OPTIONAL),
    ServiceSpec(SERVICE_LOOKUP_BARCODE_PRODUCT, LOOKUP_BARCODE_PRODUCT_SCHEMA, _OPTIONAL),
    ServiceSpec(SERVICE_SCAN_BARCODE, SCAN_BARCODE_SCHEMA, _OPTIONAL),
    ServiceSpec(SERVICE_UPDATE_BATCH, UPDATE_BATCH_SCHEMA),
    ServiceSpec(SERVICE_REMOVE_BATCH, REMOVE_BATCH_SCHEMA),
    ServiceSpec(SERVICE_TRANSFER_ITEM, TRANSFER_ITEM_SCHEMA),
    ServiceSpec(SERVICE_SET_ITEM_IMAGE_FROM_BARCODE, SET_ITEM_IMAGE_FROM_BARCODE_SCHEMA),
    ServiceSpec(SERVICE_SET_ITEM_IMAGE_FROM_MEDIA, SET_ITEM_IMAGE_FROM_MEDIA_SCHEMA),
    ServiceSpec(SERVICE_CLEAR_ITEM_IMAGE, CLEAR_ITEM_IMAGE_SCHEMA),
)

ALL_SCHEMAS = {spec.name: spec.schema for spec in SERVICES}
