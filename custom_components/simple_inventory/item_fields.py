"""Registry of scalar item fields.

One entry per item field; the coordinator's coercion sets and update allowlist, the
service layer's update allowlist, the repository's ``update_item`` column map and the
CSV import/export columns are all derived from it. Adding an updatable field here is
enough for the update pipeline; the service schema, TypedDicts and ``services.yaml``
stay explicit and are checked against this registry by ``tests/test_item_fields.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .const import (
    DEFAULT_TODO_QUANTITY_PLACEMENT,
    FIELD_AUTO_ADD_ENABLED,
    FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED,
    FIELD_AUTO_ADD_TO_LIST_QUANTITY,
    FIELD_CATEGORY,
    FIELD_DESCRIPTION,
    FIELD_DESIRED_QUANTITY,
    FIELD_EXPIRY_ALERT_DAYS,
    FIELD_EXPIRY_DATE,
    FIELD_ICON,
    FIELD_IMAGE,
    FIELD_LOCATION,
    FIELD_NAME,
    FIELD_PRICE,
    FIELD_QUANTITY,
    FIELD_TODO_LIST,
    FIELD_TODO_QUANTITY_PLACEMENT,
    FIELD_UNIT,
)

FieldKind = Literal["int", "float", "bool", "str", "date"]


@dataclass(frozen=True)
class ItemField:
    """A scalar item field.

    ``column``: the ``items`` column ``update_item`` writes; ``None`` when the value lives
    elsewhere (quantity and expiry in batches, location/category in relation tables).
    ``updatable``: accepted by the ``update_item`` service and coordinator update.
    ``export_default``: the CSV export cell when an item lacks the key. Export-only: it is
    not the add-item default (those live in ``const.DEFAULT_*`` and the coordinator).
    """

    name: str
    kind: FieldKind
    column: str | None
    updatable: bool
    export_default: Any


# Order is the CSV column order.
ITEM_FIELDS: tuple[ItemField, ...] = (
    ItemField(FIELD_NAME, "str", "name", False, ""),
    ItemField(FIELD_ICON, "str", "icon", True, ""),
    ItemField(FIELD_IMAGE, "str", "image", False, ""),
    ItemField(FIELD_DESCRIPTION, "str", "description", True, ""),
    ItemField(FIELD_QUANTITY, "float", None, True, 0),
    ItemField(FIELD_UNIT, "str", "unit", True, ""),
    ItemField(FIELD_PRICE, "float", "price", True, 0),
    ItemField(FIELD_LOCATION, "str", None, True, ""),
    ItemField(FIELD_CATEGORY, "str", None, True, ""),
    ItemField(FIELD_EXPIRY_DATE, "date", None, True, ""),
    ItemField(FIELD_EXPIRY_ALERT_DAYS, "int", "expiry_alert_days", True, 0),
    ItemField(FIELD_AUTO_ADD_ENABLED, "bool", "auto_add_enabled", True, False),
    ItemField(
        FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED,
        "bool",
        "auto_add_id_to_description_enabled",
        True,
        False,
    ),
    ItemField(FIELD_AUTO_ADD_TO_LIST_QUANTITY, "float", "auto_add_to_list_quantity", True, 0),
    ItemField(FIELD_DESIRED_QUANTITY, "float", "desired_quantity", True, 0),
    ItemField(FIELD_TODO_LIST, "str", "todo_list", True, ""),
    ItemField(
        FIELD_TODO_QUANTITY_PLACEMENT,
        "str",
        "todo_quantity_placement",
        True,
        DEFAULT_TODO_QUANTITY_PLACEMENT,
    ),
)


def item_field_names(*kinds: FieldKind, updatable_only: bool = False) -> tuple[str, ...]:
    """Names of registry fields of the given kinds (all kinds if none), in registry order."""
    return tuple(
        f.name
        for f in ITEM_FIELDS
        if (not kinds or f.kind in kinds) and (f.updatable or not updatable_only)
    )


UPDATABLE_ITEM_FIELDS: tuple[str, ...] = item_field_names(updatable_only=True)
ITEM_COLUMNS: dict[str, str] = {f.name: f.column for f in ITEM_FIELDS if f.column is not None}
