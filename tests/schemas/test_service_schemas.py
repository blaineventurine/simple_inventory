"""Tests for inventory_id/inventory_name cross-validation on service schemas."""

from __future__ import annotations

import pytest
import voluptuous as vol

from custom_components.simple_inventory.schemas.service_schemas import (
    ADD_ITEM_SCHEMA,
    GET_INVENTORY_CONSUMPTION_RATES_SCHEMA,
    GET_ITEMS_SCHEMA,
    QUANTITY_UPDATE_SCHEMA,
    REMOVE_ITEM_SCHEMA,
    UPDATE_ITEM_SCHEMA,
)

MUTATING_SCHEMAS = {
    "add_item": (ADD_ITEM_SCHEMA, {"name": "milk"}),
    "remove_item": (REMOVE_ITEM_SCHEMA, {"name": "milk"}),
    "update_item": (UPDATE_ITEM_SCHEMA, {"old_name": "milk", "name": "whole milk"}),
    "increment_item": (QUANTITY_UPDATE_SCHEMA, {"name": "milk"}),
    "decrement_item": (QUANTITY_UPDATE_SCHEMA, {"name": "milk"}),
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
