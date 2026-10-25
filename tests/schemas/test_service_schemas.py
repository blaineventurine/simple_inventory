"""Tests for inventory_id/inventory_name cross-validation on service schemas."""

from __future__ import annotations

import pytest
import voluptuous as vol

from custom_components.simple_inventory.schemas.service_schemas import (
    ADD_ITEM_SCHEMA,
    ALL_SCHEMAS,
    CLEAR_ITEM_IMAGE_SCHEMA,
    DECREMENT_SCHEMA,
    GET_INVENTORY_CONSUMPTION_RATES_SCHEMA,
    GET_ITEMS_SCHEMA,
    INCREMENT_SCHEMA,
    REMOVE_BATCH_SCHEMA,
    REMOVE_ITEM_SCHEMA,
    SET_ITEM_IMAGE_FROM_BARCODE_SCHEMA,
    SET_ITEM_IMAGE_FROM_MEDIA_SCHEMA,
    TRANSFER_ITEM_SCHEMA,
    UPDATE_BATCH_SCHEMA,
    UPDATE_ITEM_SCHEMA,
)

MUTATING_SCHEMAS = {
    "add_item": (ADD_ITEM_SCHEMA, {"name": "milk"}),
    "remove_item": (REMOVE_ITEM_SCHEMA, {"name": "milk"}),
    "update_item": (UPDATE_ITEM_SCHEMA, {"old_name": "milk", "name": "whole milk"}),
    "increment_item": (INCREMENT_SCHEMA, {"name": "milk"}),
    "decrement_item": (DECREMENT_SCHEMA, {"name": "milk"}),
    "update_batch": (UPDATE_BATCH_SCHEMA, {"batch_id": "b1"}),
    "remove_batch": (REMOVE_BATCH_SCHEMA, {"batch_id": "b1"}),
    "transfer_item": (TRANSFER_ITEM_SCHEMA, {"name": "milk", "to_location": "Garage"}),
    "set_item_image_from_barcode": (SET_ITEM_IMAGE_FROM_BARCODE_SCHEMA, {"name": "milk"}),
    "set_item_image_from_media": (
        SET_ITEM_IMAGE_FROM_MEDIA_SCHEMA,
        {"name": "milk", "media_content_id": "media-source://media_source/local/milk.jpg"},
    ),
    "clear_item_image": (CLEAR_ITEM_IMAGE_SCHEMA, {"barcode": "123"}),
}


@pytest.mark.parametrize("service_name", list(MUTATING_SCHEMAS))
def test_accepts_inventory_id_only(service_name: str) -> None:
    schema, extra = MUTATING_SCHEMAS[service_name]
    result = schema({"inventory_id": "inv_1", **extra})
    assert result["inventory_id"] == "inv_1"
    assert "inventory_name" not in result


@pytest.mark.parametrize("service_name", list(MUTATING_SCHEMAS))
def test_accepts_inventory_name_only(service_name: str) -> None:
    schema, extra = MUTATING_SCHEMAS[service_name]
    result = schema({"inventory_name": "Kitchen", **extra})
    assert result["inventory_name"] == "Kitchen"
    assert "inventory_id" not in result


@pytest.mark.parametrize("service_name", list(MUTATING_SCHEMAS))
def test_rejects_neither_inventory_id_nor_name(service_name: str) -> None:
    schema, extra = MUTATING_SCHEMAS[service_name]
    with pytest.raises(
        vol.Invalid, match="inventory_id.*inventory_name|inventory_name.*inventory_id"
    ):
        schema(dict(extra))


@pytest.mark.parametrize("service_name", list(MUTATING_SCHEMAS))
def test_rejects_both_inventory_id_and_name(service_name: str) -> None:
    schema, extra = MUTATING_SCHEMAS[service_name]
    with pytest.raises(vol.Invalid, match="[Cc]annot specify both"):
        schema({"inventory_id": "inv_1", "inventory_name": "Kitchen", **extra})


def test_get_items_schema_still_accepts_either() -> None:
    assert GET_ITEMS_SCHEMA({"inventory_id": "inv_1"})["inventory_id"] == "inv_1"
    assert GET_ITEMS_SCHEMA({"inventory_name": "Kitchen"})["inventory_name"] == "Kitchen"
    with pytest.raises(vol.Invalid):
        GET_ITEMS_SCHEMA({})
    with pytest.raises(vol.Invalid):
        GET_ITEMS_SCHEMA({"inventory_id": "inv_1", "inventory_name": "Kitchen"})


def test_untouched_consumption_rates_schema_still_requires_inventory_id() -> None:
    """Out-of-scope schema must be unaffected — inventory_id stays strictly required."""
    with pytest.raises(vol.Invalid):
        GET_INVENTORY_CONSUMPTION_RATES_SCHEMA({})
    with pytest.raises(vol.Invalid):
        GET_INVENTORY_CONSUMPTION_RATES_SCHEMA({"inventory_name": "Kitchen"})  # not accepted here
    assert (
        GET_INVENTORY_CONSUMPTION_RATES_SCHEMA({"inventory_id": "inv_1"})["inventory_id"] == "inv_1"
    )


@pytest.mark.parametrize(
    "schema,data",
    [
        (ADD_ITEM_SCHEMA, {"inventory_id": "inv_1", "name": "   "}),
        (UPDATE_ITEM_SCHEMA, {"inventory_id": "inv_1", "old_name": "milk", "name": " "}),
        (UPDATE_ITEM_SCHEMA, {"inventory_id": "inv_1", "old_name": "  ", "name": "milk"}),
        (REMOVE_ITEM_SCHEMA, {"inventory_id": "inv_1", "name": "  "}),
        (INCREMENT_SCHEMA, {"inventory_id": "inv_1", "name": "\t"}),
        (DECREMENT_SCHEMA, {"inventory_id": "inv_1", "name": "\t"}),
    ],
)
def test_whitespace_only_names_rejected(schema: vol.Schema, data: dict) -> None:
    with pytest.raises(vol.Invalid):
        schema(data)


def test_names_are_stripped() -> None:
    result = UPDATE_ITEM_SCHEMA({"inventory_id": "inv_1", "old_name": " milk ", "name": " Milk "})
    assert result["old_name"] == "milk"
    assert result["name"] == "Milk"
    assert ADD_ITEM_SCHEMA({"inventory_id": "inv_1", "name": " eggs "})["name"] == "eggs"


@pytest.mark.parametrize("todo_list", ["", "todo.grocery"])
def test_todo_list_accepts_blank_or_todo_entity(todo_list: str) -> None:
    data = {"inventory_id": "inv_1", "name": "milk", "todo_list": todo_list}
    assert ADD_ITEM_SCHEMA(data)["todo_list"] == todo_list


@pytest.mark.parametrize("todo_list", ["light.kitchen", "grocery", "todo"])
def test_todo_list_rejects_non_todo_entities(todo_list: str) -> None:
    with pytest.raises(vol.Invalid):
        ADD_ITEM_SCHEMA({"inventory_id": "inv_1", "name": "milk", "todo_list": todo_list})


def test_increment_accepts_batch_fields() -> None:
    data = ALL_SCHEMAS["increment_item"](
        {
            "inventory_id": "k",
            "name": "Milk",
            "expiry_date": "2026-11-01",
            "location": "Fridge",
            "purchased_at": "2026-10-25",
        }
    )
    assert (data["expiry_date"], data["purchased_at"]) == ("2026-11-01", "2026-10-25")


@pytest.mark.parametrize("value", ["2026-13-01", "tomorrow", "01/11/2026"])
def test_batch_dates_must_be_iso(value: str) -> None:
    with pytest.raises(vol.Invalid):
        ALL_SCHEMAS["increment_item"]({"inventory_id": "k", "name": "Milk", "expiry_date": value})


def test_decrement_accepts_location_and_batch_id() -> None:
    data = ALL_SCHEMAS["decrement_item"](
        {"inventory_id": "k", "name": "Milk", "location": "Garage", "batch_id": "b1"}
    )
    assert (data["location"], data["batch_id"]) == ("Garage", "b1")


@pytest.mark.parametrize("service_name", ["update_batch", "remove_batch"])
def test_batch_services_require_batch_id(service_name: str) -> None:
    with pytest.raises(vol.Invalid):
        ALL_SCHEMAS[service_name]({"inventory_id": "k"})


def test_update_batch_accepts_all_fields() -> None:
    data = ALL_SCHEMAS["update_batch"](
        {
            "inventory_id": "k",
            "batch_id": "b1",
            "quantity": "0",
            "expiry_date": "2026-11-01",
            "location": "Fridge",
            "unit_price": "2.5",
            "purchased_at": "2026-10-25",
        }
    )
    assert data == {
        "inventory_id": "k",
        "batch_id": "b1",
        "quantity": 0.0,
        "expiry_date": "2026-11-01",
        "location": "Fridge",
        "unit_price": 2.5,
        "purchased_at": "2026-10-25",
    }


def test_update_batch_allows_clearing_expiry() -> None:
    data = ALL_SCHEMAS["update_batch"]({"inventory_id": "k", "batch_id": "b1", "expiry_date": ""})
    assert data["expiry_date"] == ""


@pytest.mark.parametrize(
    "extra",
    [
        {"quantity": -1},
        {"unit_price": -0.01},
        {"expiry_date": "2026-13-01"},
        {"purchased_at": "tomorrow"},
        {"purchased_at": ""},
    ],
)
def test_update_batch_rejects_invalid_values(extra: dict) -> None:
    with pytest.raises(vol.Invalid):
        ALL_SCHEMAS["update_batch"]({"inventory_id": "k", "batch_id": "b1", **extra})


def test_transfer_item_accepts_all_fields() -> None:
    data = ALL_SCHEMAS["transfer_item"](
        {
            "inventory_id": "k",
            "barcode": "123",
            "to_location": " Garage ",
            "amount": "2",
            "from_location": "Fridge",
            "batch_id": "b1",
        }
    )
    assert data == {
        "inventory_id": "k",
        "barcode": "123",
        "to_location": "Garage",
        "amount": 2.0,
        "from_location": "Fridge",
        "batch_id": "b1",
    }


@pytest.mark.parametrize(
    "data",
    [
        {"name": "Milk"},
        {"name": "Milk", "to_location": "   "},
        {"name": "Milk", "to_location": "Garage", "amount": 0},
        {"name": "Milk", "to_location": "Garage", "amount": -1},
        {"to_location": "Garage"},
    ],
)
def test_transfer_item_rejects_invalid_calls(data: dict[str, object]) -> None:
    with pytest.raises(vol.Invalid):
        ALL_SCHEMAS["transfer_item"]({"inventory_id": "k", **data})


_ICON_BASES = [
    (ADD_ITEM_SCHEMA, {"inventory_id": "inv_1", "name": "milk"}),
    (UPDATE_ITEM_SCHEMA, {"inventory_id": "inv_1", "old_name": "milk", "name": "milk"}),
]


@pytest.mark.parametrize(("schema", "base"), _ICON_BASES)
@pytest.mark.parametrize(
    ("icon", "expected"),
    [
        ("", ""),
        ("mdi:apple", "mdi:apple"),
        ("  mdi:apple ", "mdi:apple"),
        ("hass:cart", "hass:cart"),
    ],
)
def test_item_icon_accepts_blank_or_prefixed_icon(
    schema: vol.Schema, base: dict[str, str], icon: str, expected: str
) -> None:
    assert schema({**base, "icon": icon})["icon"] == expected


@pytest.mark.parametrize(("schema", "base"), _ICON_BASES)
@pytest.mark.parametrize("icon", ["apple", "mdi apple", 5, None, ["mdi:apple"]])
def test_item_icon_rejects_invalid_values(
    schema: vol.Schema, base: dict[str, str], icon: object
) -> None:
    with pytest.raises(vol.Invalid):
        schema({**base, "icon": icon})


@pytest.mark.parametrize(("schema", "base"), _ICON_BASES)
def test_item_icon_is_optional(schema: vol.Schema, base: dict[str, str]) -> None:
    assert "icon" not in schema(dict(base))


@pytest.mark.parametrize(("schema", "base"), _ICON_BASES)
def test_item_icon_invalid_value_message(schema: vol.Schema, base: dict[str, str]) -> None:
    with pytest.raises(vol.Invalid, match='icon must be empty or "prefix:name"'):
        schema({**base, "icon": "cup"})


def test_image_services_identify_the_item_by_name_or_barcode() -> None:
    for name in ("set_item_image_from_barcode", "clear_item_image"):
        with pytest.raises(vol.Invalid, match="name.*barcode"):
            ALL_SCHEMAS[name]({"inventory_id": "k"})
    data = SET_ITEM_IMAGE_FROM_BARCODE_SCHEMA(
        {"inventory_id": "k", "barcode": "123", "lookup_barcode": " 456 "}
    )
    assert data["lookup_barcode"] == "456"


@pytest.mark.parametrize(
    "media_content_id", ["", "/media/milk.jpg", "https://example.org/milk.jpg", "local/milk.jpg"]
)
def test_set_item_image_from_media_needs_a_media_source_id(media_content_id: str) -> None:
    with pytest.raises(vol.Invalid):
        SET_ITEM_IMAGE_FROM_MEDIA_SCHEMA(
            {"inventory_id": "k", "name": "milk", "media_content_id": media_content_id}
        )
