"""Golden tests: every repository reader's exact output (keys, order, types, values).

The database is filled with raw SQL so every column holds a distinctive non-default value;
the expected outputs were captured from the positional-index readers before B2 moved them
to named row access, so any drift in mapping, key order or coercion fails here.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from homeassistant.core import HomeAssistant

from custom_components.simple_inventory.storage.repository import InventoryRepository

_SEED = """
INSERT INTO inventories (id, name, description, icon, entry_type, metadata, created_at, updated_at)
VALUES ('inv1', 'Kitchen', 'Kitchen desc', 'mdi:fridge', 'inventory', '{"k": 1}',
        '2026-01-01 00:00:01', '2026-01-02 00:00:02'),
       ('inv2', 'attic', 'Attic desc', 'mdi:home', 'inventory', NULL,
        '2026-01-03 00:00:03', '2026-01-04 00:00:04');

INSERT INTO items (id, inventory_id, name, description, quantity, unit, expiry_date,
                   expiry_alert_days, auto_add_enabled, auto_add_id_to_description_enabled,
                   auto_add_to_list_quantity, desired_quantity, todo_list,
                   todo_quantity_placement, price, icon, image, created_at, updated_at)
VALUES ('item1', 'inv1', 'Milk', 'Whole milk', 3.5, 'l', '2026-02-01', 4, 1, 1, 1.5, 6.25,
        'todo.shopping', 'description', 1.99, 'mdi:cup', 'item1.webp',
        '2026-01-05 00:00:05', '2026-01-06 00:00:06'),
       ('item2', 'inv1', 'bread', 'Rye', 0, 'loaf', '', 0, 0, 0, 0, 0,
        '', 'name', 0, '', '', '2026-01-07 00:00:07', '2026-01-08 00:00:08'),
       ('item3', 'inv2', 'Box', 'Cardboard', 2, 'pcs', '', 1, 1, 0, 2, 3,
        'todo.attic', 'none', 0.5, 'mdi:box', '', '2026-01-09 00:00:09', '2026-01-10 00:00:10');

INSERT INTO locations (id, inventory_id, name) VALUES (1, 'inv1', 'Pantry'), (2, 'inv1', 'Fridge');
INSERT INTO item_locations (item_id, location_id) VALUES ('item1', 2), ('item1', 1);
INSERT INTO categories (id, name) VALUES (1, 'Dairy'), (2, 'Drinks');
INSERT INTO item_categories (item_id, category_id) VALUES ('item1', 2), ('item1', 1);
INSERT INTO item_barcodes (item_id, inventory_id, barcode)
VALUES ('item1', 'inv1', '222'), ('item1', 'inv1', '111'), ('item3', 'inv2', '111');
INSERT INTO item_aliases (item_id, inventory_id, alias)
VALUES ('item1', 'inv1', 'moo'), ('item1', 'inv1', 'lait');

INSERT INTO item_batches (id, item_id, inventory_id, quantity, expiry_date, location_id,
                          unit_price, purchased_at, created_at, updated_at)
VALUES ('b1', 'item1', 'inv1', 2.5, '2026-02-01', 2, 1.99, '2026-01-05', '2026-01-05', '2026-01-05'),
       ('b2', 'item1', 'inv1', 1, '', NULL, 0, '2026-01-04', '2026-01-04', '2026-01-04'),
       ('b3', 'item3', 'inv2', 2, '', NULL, 0.5, '2026-01-09', '2026-01-09', '2026-01-09');

INSERT INTO consumption_history (id, item_id, inventory_id, event_type, amount,
                                 quantity_before, quantity_after, source, location_from,
                                 location_to, timestamp, metadata, price, batch_id)
VALUES ('h1', 'item1', 'inv1', 'add', 4, 0, 4, 'service', '', 'Fridge',
        '2026-01-05T00:00:00', '', 1.99, 'b1'),
       ('h2', 'item1', 'inv1', 'decrement', 0.5, 4, 3.5, 'websocket', 'Fridge', '',
        '2026-01-06T00:00:00', '{"x": 1}', 0, ''),
       ('h3', 'item1', 'inv1', 'increment', 1, 3.5, 4.5, 'manual', '', 'Pantry',
        '2026-01-07T00:00:00', '', 0, 'b2');

INSERT OR REPLACE INTO metadata (key, value)
VALUES ('barcode_lookup_provider', '{"provider": "off", "key": "abc"}');
"""


@pytest.fixture
async def repo(hass_with_tmp_config: HomeAssistant) -> AsyncGenerator[InventoryRepository, None]:
    repository = InventoryRepository(hass_with_tmp_config, db_filename="golden.db")
    await repository.async_initialize()
    try:
        conn = repository._connection()
        await conn.executescript(_SEED)
        await conn.commit()
        yield repository
    finally:
        await repository.async_close()


def _shape(value: Any) -> Any:
    """Expose dict key order and value types, which ``==`` alone ignores."""
    if isinstance(value, dict):
        return [(key, _shape(item)) for key, item in value.items()]
    if isinstance(value, list | tuple | set):
        items = sorted(value) if isinstance(value, set) else value
        return [type(value).__name__, *(_shape(item) for item in items)]
    return (type(value).__name__, value)


async def _all_readers(repo: InventoryRepository) -> dict[str, Any]:
    return {
        "fetch_inventory": await repo.fetch_inventory("inv1"),
        "fetch_inventory_null_metadata": await repo.fetch_inventory("inv2"),
        "list_inventories": await repo.list_inventories(),
        "get_inventory_counts": await repo.get_inventory_counts("inv1"),
        "get_todo_list_references": await repo.get_todo_list_references("inv1"),
        "list_orphaned_inventories": await repo.list_orphaned_inventories({"inv2"}),
        "get_metadata_value": await repo.get_metadata_value("barcode_lookup_provider"),
        "get_barcode_provider_config": await repo.get_barcode_provider_config(),
        "list_item_barcodes": await repo.list_item_barcodes("item1"),
        "list_item_ids_with_images": await repo.list_item_ids_with_images(),
        "list_items_with_details": await repo.list_items_with_details("inv1"),
        "get_item_by_name": await repo.get_item_by_name("inv1", "MILK"),
        "get_item_by_id": await repo.get_item_by_id("item3"),
        "get_item_by_barcode": await repo.get_item_by_barcode("inv1", "111"),
        "get_item_by_barcode_global": await repo.get_item_by_barcode_global("111"),
        "find_location_id": await repo.find_location_id("inv1", "pantry"),
        "list_location_names": await repo.list_location_names("inv1"),
        "first_item_location_id": await repo.first_item_location_id("item1"),
        "has_stock_at_location": await repo.has_stock_at_location("item1", 2),
        "find_relation_conflicts": await repo.find_relation_conflicts(
            "inv1", "item2", ["111", "999"], ["moo"]
        ),
        "get_item_history": await repo.get_item_history("item1"),
        "get_inventory_history": await repo.get_inventory_history("inv1", limit=2, offset=1),
        "get_item_consumption_stats": await repo.get_item_consumption_stats("item1"),
        "get_inventory_consumption_stats": await repo.get_inventory_consumption_stats("inv1"),
        "list_batches": await repo.list_batches("item1"),
        "list_inventory_batches": await repo.list_inventory_batches("inv1"),
        "get_batch": await repo.get_batch("b1"),
        "list_transfer_sources": await repo.list_transfer_sources("item1", to_location_id=1),
    }


async def test_readers_golden(repo: InventoryRepository) -> None:
    actual = {name: _shape(value) for name, value in (await _all_readers(repo)).items()}
    assert actual == EXPECTED


EXPECTED: dict[str, Any] = {
    "fetch_inventory": [
        ("id", ("str", "inv1")),
        ("name", ("str", "Kitchen")),
        ("description", ("str", "Kitchen desc")),
        ("icon", ("str", "mdi:fridge")),
        ("entry_type", ("str", "inventory")),
        ("metadata", ("str", '{"k": 1}')),
        ("created_at", ("str", "2026-01-01 00:00:01")),
        ("updated_at", ("str", "2026-01-02 00:00:02")),
    ],
    "fetch_inventory_null_metadata": [
        ("id", ("str", "inv2")),
        ("name", ("str", "attic")),
        ("description", ("str", "Attic desc")),
        ("icon", ("str", "mdi:home")),
        ("entry_type", ("str", "inventory")),
        ("metadata", ("NoneType", None)),
        ("created_at", ("str", "2026-01-03 00:00:03")),
        ("updated_at", ("str", "2026-01-04 00:00:04")),
    ],
    "list_inventories": [
        "list",
        [
            ("id", ("str", "inv2")),
            ("name", ("str", "attic")),
            ("description", ("str", "Attic desc")),
            ("icon", ("str", "mdi:home")),
            ("entry_type", ("str", "inventory")),
            ("metadata", ("NoneType", None)),
            ("created_at", ("str", "2026-01-03 00:00:03")),
            ("updated_at", ("str", "2026-01-04 00:00:04")),
        ],
        [
            ("id", ("str", "inv1")),
            ("name", ("str", "Kitchen")),
            ("description", ("str", "Kitchen desc")),
            ("icon", ("str", "mdi:fridge")),
            ("entry_type", ("str", "inventory")),
            ("metadata", ("str", '{"k": 1}')),
            ("created_at", ("str", "2026-01-01 00:00:01")),
            ("updated_at", ("str", "2026-01-02 00:00:02")),
        ],
    ],
    "get_inventory_counts": [
        ("items", ("int", 2)),
        ("items_out_of_stock", ("int", 1)),
        ("auto_add_enabled", ("int", 1)),
        ("locations", ("int", 2)),
        ("categories", ("int", 2)),
        ("barcodes", ("int", 2)),
        ("aliases", ("int", 2)),
        ("history_events", ("int", 3)),
    ],
    "get_todo_list_references": [("todo.shopping", ("int", 1))],
    "list_orphaned_inventories": [
        "list",
        [("id", ("str", "inv1")), ("name", ("str", "Kitchen")), ("item_count", ("int", 2))],
    ],
    "get_metadata_value": ("str", '{"provider": "off", "key": "abc"}'),
    "get_barcode_provider_config": [("provider", ("str", "off")), ("key", ("str", "abc"))],
    "list_item_barcodes": ["list", ("str", "111"), ("str", "222")],
    "list_item_ids_with_images": ["set", ("str", "item1")],
    "list_items_with_details": [
        "list",
        [
            ("id", ("str", "item2")),
            ("inventory_id", ("str", "inv1")),
            ("name", ("str", "bread")),
            ("description", ("str", "Rye")),
            ("quantity", ("float", 0.0)),
            ("unit", ("str", "loaf")),
            ("expiry_date", ("str", "")),
            ("expiry_alert_days", ("int", 0)),
            ("auto_add_enabled", ("bool", False)),
            ("auto_add_id_to_description_enabled", ("bool", False)),
            ("auto_add_to_list_quantity", ("float", 0.0)),
            ("desired_quantity", ("float", 0.0)),
            ("todo_list", ("str", "")),
            ("todo_quantity_placement", ("str", "name")),
            ("price", ("float", 0.0)),
            ("created_at", ("str", "2026-01-07 00:00:07")),
            ("updated_at", ("str", "2026-01-08 00:00:08")),
            ("icon", ("str", "")),
            ("image", ("str", "")),
            ("category", ("str", "")),
            ("location", ("str", "")),
            ("locations", ["list"]),
            ("categories", ["list"]),
            ("barcodes", ["list"]),
            ("aliases", ["list"]),
            ("batches", ["list"]),
            ("stocked_locations", ["list"]),
        ],
        [
            ("id", ("str", "item1")),
            ("inventory_id", ("str", "inv1")),
            ("name", ("str", "Milk")),
            ("description", ("str", "Whole milk")),
            ("quantity", ("float", 3.5)),
            ("unit", ("str", "l")),
            ("expiry_date", ("str", "2026-02-01")),
            ("expiry_alert_days", ("int", 4)),
            ("auto_add_enabled", ("bool", True)),
            ("auto_add_id_to_description_enabled", ("bool", True)),
            ("auto_add_to_list_quantity", ("float", 1.5)),
            ("desired_quantity", ("float", 6.25)),
            ("todo_list", ("str", "todo.shopping")),
            ("todo_quantity_placement", ("str", "description")),
            ("price", ("float", 1.99)),
            ("created_at", ("str", "2026-01-05 00:00:05")),
            ("updated_at", ("str", "2026-01-06 00:00:06")),
            ("icon", ("str", "mdi:cup")),
            ("image", ("str", "item1.webp")),
            ("category", ("str", "Drinks")),
            ("location", ("str", "Fridge")),
            ("locations", ["list", ("str", "Fridge"), ("str", "Pantry")]),
            ("categories", ["list", ("str", "Drinks"), ("str", "Dairy")]),
            ("barcodes", ["list", ("str", "111"), ("str", "222")]),
            ("aliases", ["list", ("str", "lait"), ("str", "moo")]),
            (
                "batches",
                [
                    "list",
                    [
                        ("id", ("str", "b1")),
                        ("quantity", ("float", 2.5)),
                        ("expiry_date", ("str", "2026-02-01")),
                        ("location", ("str", "Fridge")),
                        ("unit_price", ("float", 1.99)),
                        ("purchased_at", ("str", "2026-01-05")),
                    ],
                    [
                        ("id", ("str", "b2")),
                        ("quantity", ("float", 1.0)),
                        ("expiry_date", ("str", "")),
                        ("location", ("str", "")),
                        ("unit_price", ("float", 0.0)),
                        ("purchased_at", ("str", "2026-01-04")),
                    ],
                ],
            ),
            ("stocked_locations", ["list", ("str", "Fridge")]),
        ],
    ],
    "get_item_by_name": [
        ("id", ("str", "item1")),
        ("inventory_id", ("str", "inv1")),
        ("name", ("str", "Milk")),
        ("description", ("str", "Whole milk")),
        ("quantity", ("float", 3.5)),
        ("unit", ("str", "l")),
        ("expiry_date", ("str", "2026-02-01")),
        ("expiry_alert_days", ("int", 4)),
        ("auto_add_enabled", ("bool", True)),
        ("auto_add_id_to_description_enabled", ("bool", True)),
        ("auto_add_to_list_quantity", ("float", 1.5)),
        ("desired_quantity", ("float", 6.25)),
        ("todo_list", ("str", "todo.shopping")),
        ("todo_quantity_placement", ("str", "description")),
        ("price", ("float", 1.99)),
        ("created_at", ("str", "2026-01-05 00:00:05")),
        ("updated_at", ("str", "2026-01-06 00:00:06")),
        ("icon", ("str", "mdi:cup")),
        ("image", ("str", "item1.webp")),
    ],
    "get_item_by_id": [
        ("id", ("str", "item3")),
        ("inventory_id", ("str", "inv2")),
        ("name", ("str", "Box")),
        ("description", ("str", "Cardboard")),
        ("quantity", ("float", 2.0)),
        ("unit", ("str", "pcs")),
        ("expiry_date", ("str", "")),
        ("expiry_alert_days", ("int", 1)),
        ("auto_add_enabled", ("bool", True)),
        ("auto_add_id_to_description_enabled", ("bool", False)),
        ("auto_add_to_list_quantity", ("float", 2.0)),
        ("desired_quantity", ("float", 3.0)),
        ("todo_list", ("str", "todo.attic")),
        ("todo_quantity_placement", ("str", "none")),
        ("price", ("float", 0.5)),
        ("created_at", ("str", "2026-01-09 00:00:09")),
        ("updated_at", ("str", "2026-01-10 00:00:10")),
        ("icon", ("str", "mdi:box")),
        ("image", ("str", "")),
    ],
    "get_item_by_barcode": [
        ("id", ("str", "item1")),
        ("inventory_id", ("str", "inv1")),
        ("name", ("str", "Milk")),
        ("description", ("str", "Whole milk")),
        ("quantity", ("float", 3.5)),
        ("unit", ("str", "l")),
        ("expiry_date", ("str", "2026-02-01")),
        ("expiry_alert_days", ("int", 4)),
        ("auto_add_enabled", ("bool", True)),
        ("auto_add_id_to_description_enabled", ("bool", True)),
        ("auto_add_to_list_quantity", ("float", 1.5)),
        ("desired_quantity", ("float", 6.25)),
        ("todo_list", ("str", "todo.shopping")),
        ("todo_quantity_placement", ("str", "description")),
        ("price", ("float", 1.99)),
        ("created_at", ("str", "2026-01-05 00:00:05")),
        ("updated_at", ("str", "2026-01-06 00:00:06")),
        ("icon", ("str", "mdi:cup")),
        ("image", ("str", "item1.webp")),
    ],
    "get_item_by_barcode_global": [
        "list",
        [
            ("id", ("str", "item1")),
            ("inventory_id", ("str", "inv1")),
            ("inventory_name", ("str", "Kitchen")),
            ("name", ("str", "Milk")),
            ("description", ("str", "Whole milk")),
            ("quantity", ("float", 3.5)),
            ("unit", ("str", "l")),
            ("expiry_date", ("str", "2026-02-01")),
            ("expiry_alert_days", ("int", 4)),
            ("auto_add_enabled", ("bool", True)),
            ("auto_add_id_to_description_enabled", ("bool", True)),
            ("auto_add_to_list_quantity", ("float", 1.5)),
            ("desired_quantity", ("float", 6.25)),
            ("todo_list", ("str", "todo.shopping")),
            ("todo_quantity_placement", ("str", "description")),
            ("price", ("float", 1.99)),
            ("created_at", ("str", "2026-01-05 00:00:05")),
            ("updated_at", ("str", "2026-01-06 00:00:06")),
            ("icon", ("str", "mdi:cup")),
            ("image", ("str", "item1.webp")),
        ],
        [
            ("id", ("str", "item3")),
            ("inventory_id", ("str", "inv2")),
            ("inventory_name", ("str", "attic")),
            ("name", ("str", "Box")),
            ("description", ("str", "Cardboard")),
            ("quantity", ("float", 2.0)),
            ("unit", ("str", "pcs")),
            ("expiry_date", ("str", "")),
            ("expiry_alert_days", ("int", 1)),
            ("auto_add_enabled", ("bool", True)),
            ("auto_add_id_to_description_enabled", ("bool", False)),
            ("auto_add_to_list_quantity", ("float", 2.0)),
            ("desired_quantity", ("float", 3.0)),
            ("todo_list", ("str", "todo.attic")),
            ("todo_quantity_placement", ("str", "none")),
            ("price", ("float", 0.5)),
            ("created_at", ("str", "2026-01-09 00:00:09")),
            ("updated_at", ("str", "2026-01-10 00:00:10")),
            ("icon", ("str", "mdi:box")),
            ("image", ("str", "")),
        ],
    ],
    "find_location_id": ("int", 1),
    "list_location_names": ["list", ("str", "Fridge"), ("str", "Pantry")],
    "first_item_location_id": ("int", 2),
    "has_stock_at_location": ("bool", True),
    "find_relation_conflicts": ["tuple", ["list", ("str", "111")], ["list", ("str", "moo")]],
    "get_item_history": [
        "list",
        [
            ("id", ("str", "h3")),
            ("item_id", ("str", "item1")),
            ("inventory_id", ("str", "inv1")),
            ("event_type", ("str", "increment")),
            ("amount", ("float", 1.0)),
            ("quantity_before", ("float", 3.5)),
            ("quantity_after", ("float", 4.5)),
            ("source", ("str", "manual")),
            ("location_from", ("str", "")),
            ("location_to", ("str", "Pantry")),
            ("timestamp", ("str", "2026-01-07T00:00:00")),
            ("metadata", ("str", "")),
            ("item_name", ("str", "Milk")),
            ("price", ("int", 0)),
            ("batch_id", ("str", "b2")),
        ],
        [
            ("id", ("str", "h2")),
            ("item_id", ("str", "item1")),
            ("inventory_id", ("str", "inv1")),
            ("event_type", ("str", "decrement")),
            ("amount", ("float", 0.5)),
            ("quantity_before", ("float", 4.0)),
            ("quantity_after", ("float", 3.5)),
            ("source", ("str", "websocket")),
            ("location_from", ("str", "Fridge")),
            ("location_to", ("str", "")),
            ("timestamp", ("str", "2026-01-06T00:00:00")),
            ("metadata", ("str", '{"x": 1}')),
            ("item_name", ("str", "Milk")),
            ("price", ("int", 0)),
            ("batch_id", ("str", "")),
        ],
        [
            ("id", ("str", "h1")),
            ("item_id", ("str", "item1")),
            ("inventory_id", ("str", "inv1")),
            ("event_type", ("str", "add")),
            ("amount", ("float", 4.0)),
            ("quantity_before", ("float", 0.0)),
            ("quantity_after", ("float", 4.0)),
            ("source", ("str", "service")),
            ("location_from", ("str", "")),
            ("location_to", ("str", "Fridge")),
            ("timestamp", ("str", "2026-01-05T00:00:00")),
            ("metadata", ("str", "")),
            ("item_name", ("str", "Milk")),
            ("price", ("float", 1.99)),
            ("batch_id", ("str", "b1")),
        ],
    ],
    "get_inventory_history": [
        "list",
        [
            ("id", ("str", "h2")),
            ("item_id", ("str", "item1")),
            ("inventory_id", ("str", "inv1")),
            ("event_type", ("str", "decrement")),
            ("amount", ("float", 0.5)),
            ("quantity_before", ("float", 4.0)),
            ("quantity_after", ("float", 3.5)),
            ("source", ("str", "websocket")),
            ("location_from", ("str", "Fridge")),
            ("location_to", ("str", "")),
            ("timestamp", ("str", "2026-01-06T00:00:00")),
            ("metadata", ("str", '{"x": 1}')),
            ("item_name", ("str", "Milk")),
            ("price", ("int", 0)),
            ("batch_id", ("str", "")),
        ],
        [
            ("id", ("str", "h1")),
            ("item_id", ("str", "item1")),
            ("inventory_id", ("str", "inv1")),
            ("event_type", ("str", "add")),
            ("amount", ("float", 4.0)),
            ("quantity_before", ("float", 0.0)),
            ("quantity_after", ("float", 4.0)),
            ("source", ("str", "service")),
            ("location_from", ("str", "")),
            ("location_to", ("str", "Fridge")),
            ("timestamp", ("str", "2026-01-05T00:00:00")),
            ("metadata", ("str", "")),
            ("item_name", ("str", "Milk")),
            ("price", ("float", 1.99)),
            ("batch_id", ("str", "b1")),
        ],
    ],
    "get_item_consumption_stats": [
        ("item_id", ("str", "item1")),
        ("window_days", ("NoneType", None)),
        ("window_start", ("str", "")),
        ("decrement_count", ("int", 1)),
        ("total_consumed", ("float", 0.5)),
        ("first_event_ts", ("str", "2026-01-06T00:00:00")),
        ("last_event_ts", ("str", "2026-01-06T00:00:00")),
        ("restock_count", ("int", 2)),
        (
            "restock_timestamps",
            ["list", ("str", "2026-01-05T00:00:00"), ("str", "2026-01-07T00:00:00")],
        ),
        ("total_spend", ("float", 7.96)),
        ("restock_spend_count", ("int", 1)),
        ("first_spend_ts", ("str", "2026-01-05T00:00:00")),
    ],
    "get_inventory_consumption_stats": [
        "list",
        [
            ("item_id", ("str", "item2")),
            ("item_name", ("str", "bread")),
            ("current_quantity", ("float", 0.0)),
            ("unit", ("str", "loaf")),
            ("window_days", ("NoneType", None)),
            ("window_start", ("str", "")),
            ("decrement_count", ("int", 0)),
            ("total_consumed", ("float", 0.0)),
            ("first_event_ts", ("NoneType", None)),
            ("last_event_ts", ("NoneType", None)),
            ("restock_count", ("int", 0)),
            ("restock_timestamps", ["list"]),
            ("total_spend", ("float", 0.0)),
            ("restock_spend_count", ("int", 0)),
            ("first_spend_ts", ("NoneType", None)),
        ],
        [
            ("item_id", ("str", "item1")),
            ("item_name", ("str", "Milk")),
            ("current_quantity", ("float", 3.5)),
            ("unit", ("str", "l")),
            ("window_days", ("NoneType", None)),
            ("window_start", ("str", "")),
            ("decrement_count", ("int", 1)),
            ("total_consumed", ("float", 0.5)),
            ("first_event_ts", ("str", "2026-01-06T00:00:00")),
            ("last_event_ts", ("str", "2026-01-06T00:00:00")),
            ("restock_count", ("int", 2)),
            (
                "restock_timestamps",
                ["list", ("str", "2026-01-05T00:00:00"), ("str", "2026-01-07T00:00:00")],
            ),
            ("total_spend", ("float", 7.96)),
            ("restock_spend_count", ("int", 1)),
            ("first_spend_ts", ("str", "2026-01-05T00:00:00")),
        ],
    ],
    "list_batches": [
        "list",
        [
            ("id", ("str", "b1")),
            ("item_id", ("str", "item1")),
            ("inventory_id", ("str", "inv1")),
            ("quantity", ("float", 2.5)),
            ("expiry_date", ("str", "2026-02-01")),
            ("location_id", ("int", 2)),
            ("location", ("str", "Fridge")),
            ("unit_price", ("float", 1.99)),
            ("purchased_at", ("str", "2026-01-05")),
        ],
        [
            ("id", ("str", "b2")),
            ("item_id", ("str", "item1")),
            ("inventory_id", ("str", "inv1")),
            ("quantity", ("float", 1.0)),
            ("expiry_date", ("str", "")),
            ("location_id", ("NoneType", None)),
            ("location", ("str", "")),
            ("unit_price", ("float", 0.0)),
            ("purchased_at", ("str", "2026-01-04")),
        ],
    ],
    "list_inventory_batches": [
        "list",
        [
            ("id", ("str", "b1")),
            ("item_id", ("str", "item1")),
            ("inventory_id", ("str", "inv1")),
            ("quantity", ("float", 2.5)),
            ("expiry_date", ("str", "2026-02-01")),
            ("location_id", ("int", 2)),
            ("location", ("str", "Fridge")),
            ("unit_price", ("float", 1.99)),
            ("purchased_at", ("str", "2026-01-05")),
        ],
        [
            ("id", ("str", "b2")),
            ("item_id", ("str", "item1")),
            ("inventory_id", ("str", "inv1")),
            ("quantity", ("float", 1.0)),
            ("expiry_date", ("str", "")),
            ("location_id", ("NoneType", None)),
            ("location", ("str", "")),
            ("unit_price", ("float", 0.0)),
            ("purchased_at", ("str", "2026-01-04")),
        ],
    ],
    "get_batch": [
        ("id", ("str", "b1")),
        ("item_id", ("str", "item1")),
        ("inventory_id", ("str", "inv1")),
        ("quantity", ("float", 2.5)),
        ("expiry_date", ("str", "2026-02-01")),
        ("location_id", ("int", 2)),
        ("location", ("str", "Fridge")),
        ("unit_price", ("float", 1.99)),
        ("purchased_at", ("str", "2026-01-05")),
    ],
    "list_transfer_sources": [
        "list",
        [
            ("id", ("str", "b1")),
            ("item_id", ("str", "item1")),
            ("inventory_id", ("str", "inv1")),
            ("quantity", ("float", 2.5)),
            ("expiry_date", ("str", "2026-02-01")),
            ("location_id", ("int", 2)),
            ("location", ("str", "Fridge")),
            ("unit_price", ("float", 1.99)),
            ("purchased_at", ("str", "2026-01-05")),
        ],
        [
            ("id", ("str", "b2")),
            ("item_id", ("str", "item1")),
            ("inventory_id", ("str", "inv1")),
            ("quantity", ("float", 1.0)),
            ("expiry_date", ("str", "")),
            ("location_id", ("NoneType", None)),
            ("location", ("str", "")),
            ("unit_price", ("float", 0.0)),
            ("purchased_at", ("str", "2026-01-04")),
        ],
    ],
}
