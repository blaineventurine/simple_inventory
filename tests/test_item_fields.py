"""The item-field registry agrees with the explicit schema, TypedDicts and services.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import get_type_hints

from homeassistant.util.yaml import load_yaml_dict

from custom_components.simple_inventory.coordinator import SimpleInventoryCoordinator
from custom_components.simple_inventory.item_fields import (
    ITEM_COLUMNS,
    ITEM_FIELDS,
    UPDATABLE_ITEM_FIELDS,
)
from custom_components.simple_inventory.schemas.service_schemas import ITEM_SCHEMA
from custom_components.simple_inventory.services.inventory_service import InventoryService
from custom_components.simple_inventory.storage.repository import _ITEM_KEYS
from custom_components.simple_inventory.types import AddItemServiceData, UpdateItemServiceData

_SERVICES_YAML = (
    Path(__file__).parent.parent / "custom_components" / "simple_inventory" / "services.yaml"
)
_PY_TYPES = {"int": int, "float": float, "bool": bool, "str": str, "date": str}


def test_field_names_are_unique() -> None:
    names = [f.name for f in ITEM_FIELDS]
    assert len(names) == len(set(names))


def test_repository_reads_every_registry_column() -> None:
    assert set(ITEM_COLUMNS.values()) <= set(_ITEM_KEYS)
    assert all(f.column in (None, f.name) for f in ITEM_FIELDS)


def test_updatable_fields_are_in_the_item_schema() -> None:
    schema_keys = {str(key) for key in ITEM_SCHEMA}
    assert set(UPDATABLE_ITEM_FIELDS) <= schema_keys


def test_typed_dicts_declare_every_updatable_field_with_its_kind() -> None:
    by_name = {f.name: f for f in ITEM_FIELDS}
    for typed_dict in (AddItemServiceData, UpdateItemServiceData):
        hints = get_type_hints(typed_dict)
        for name in UPDATABLE_ITEM_FIELDS:
            assert hints.get(name) is _PY_TYPES[by_name[name].kind], (typed_dict, name)


def test_services_yaml_lists_every_updatable_field() -> None:
    services = load_yaml_dict(str(_SERVICES_YAML))
    for service in ("add_item", "update_item"):
        assert set(UPDATABLE_ITEM_FIELDS) <= set(services[service]["fields"]), service


def test_derived_sets_match_the_pre_registry_lists() -> None:
    """Pins the allowlists/coercion sets that were hand-maintained before the registry."""
    updatable = {
        "auto_add_enabled",
        "auto_add_id_to_description_enabled",
        "auto_add_to_list_quantity",
        "category",
        "description",
        "desired_quantity",
        "expiry_alert_days",
        "expiry_date",
        "icon",
        "location",
        "price",
        "quantity",
        "todo_list",
        "todo_quantity_placement",
        "unit",
    }
    assert set(InventoryService._UPDATEABLE_FIELDS) == updatable
    assert SimpleInventoryCoordinator._INTEGER_FIELDS == {"expiry_alert_days"}
    assert SimpleInventoryCoordinator._NUMERIC_FIELDS == {
        "quantity",
        "auto_add_to_list_quantity",
        "desired_quantity",
        "price",
    }
    assert SimpleInventoryCoordinator._BOOLEAN_FIELDS == {
        "auto_add_enabled",
        "auto_add_id_to_description_enabled",
    }
    assert SimpleInventoryCoordinator._STRING_FIELDS == {
        "unit",
        "category",
        "description",
        "expiry_date",
        "todo_list",
        "todo_quantity_placement",
        "location",
        "icon",
    }
    assert ITEM_COLUMNS == {
        "name": "name",
        "description": "description",
        "unit": "unit",
        "expiry_alert_days": "expiry_alert_days",
        "auto_add_enabled": "auto_add_enabled",
        "auto_add_id_to_description_enabled": "auto_add_id_to_description_enabled",
        "auto_add_to_list_quantity": "auto_add_to_list_quantity",
        "desired_quantity": "desired_quantity",
        "todo_list": "todo_list",
        "todo_quantity_placement": "todo_quantity_placement",
        "price": "price",
        "icon": "icon",
        "image": "image",
    }


def test_csv_export_output_is_unchanged() -> None:
    """Byte-for-byte golden output captured before the registry refactor."""
    coordinator = SimpleInventoryCoordinator.__new__(SimpleInventoryCoordinator)
    full = {
        "name": "=Milk",
        "icon": "mdi:cup",
        "image": "x.jpg",
        "description": "Whole",
        "quantity": 2.5,
        "unit": "L",
        "price": 1.25,
        "locations": ["Fridge", "Door"],
        "location": "Fridge",
        "categories": ["Dairy"],
        "category": "Dairy",
        "expiry_date": "2030-01-15",
        "expiry_alert_days": 3,
        "auto_add_enabled": True,
        "auto_add_id_to_description_enabled": True,
        "auto_add_to_list_quantity": 1.0,
        "desired_quantity": 4.0,
        "todo_list": "todo.shop",
        "todo_quantity_placement": "description",
        "barcodes": ["1", "2"],
        "aliases": ["moo"],
        "batches": [{"quantity": 2.5}],
    }
    scalar_only = {"location": "Shelf", "category": "Misc", "image": ""}

    assert coordinator._items_to_csv([full, {}, scalar_only]) == (
        "name,icon,image,description,quantity,unit,price,location,category,expiry_date,"
        "expiry_alert_days,auto_add_enabled,auto_add_id_to_description_enabled,"
        "auto_add_to_list_quantity,desired_quantity,todo_list,todo_quantity_placement,"
        "barcodes,aliases,batches\r\n"
        '\'=Milk,mdi:cup,1,Whole,2.5,L,1.25,"Fridge, Door",Dairy,2030-01-15,3,1,1,1.0,4.0,'
        'todo.shop,description,"1, 2",moo,"[{""quantity"": 2.5}]"\r\n'
        ",,0,,0,,0,,,,0,0,0,0,0,,name,,,[]\r\n"
        ",,0,,0,,0,Shelf,Misc,,0,0,0,0,0,,name,,,[]\r\n"
    )
