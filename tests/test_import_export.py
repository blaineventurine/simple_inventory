"""Import/export tests against a real SQLite repository."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import MagicMock

import pytest
from homeassistant.core import Event, HomeAssistant

from custom_components.simple_inventory.const import (
    DOMAIN,
    FIELD_ALIASES,
    FIELD_AUTO_ADD_ENABLED,
    FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED,
    FIELD_AUTO_ADD_TO_LIST_QUANTITY,
    FIELD_BARCODE,
    FIELD_BARCODES,
    FIELD_CATEGORIES,
    FIELD_CATEGORY,
    FIELD_DESCRIPTION,
    FIELD_DESIRED_QUANTITY,
    FIELD_EXPIRY_ALERT_DAYS,
    FIELD_EXPIRY_DATE,
    FIELD_ICON,
    FIELD_IMAGE,
    FIELD_LOCATION,
    FIELD_LOCATIONS,
    FIELD_NAME,
    FIELD_PRICE,
    FIELD_QUANTITY,
    FIELD_TODO_LIST,
    FIELD_TODO_QUANTITY_PLACEMENT,
    FIELD_UNIT,
)
from custom_components.simple_inventory.coordinator import SimpleInventoryCoordinator
from custom_components.simple_inventory.hub import InventoryHub
from custom_components.simple_inventory.item_fields import ITEM_FIELDS
from custom_components.simple_inventory.storage.repository import InventoryRepository

SOURCE = "kitchen_123"
TARGET = "cabin_456"

# Keys that legitimately differ between the source and the imported copy.
_VOLATILE_KEYS = ("id", "inventory_id", "created_at", "updated_at", FIELD_DESCRIPTION)


@pytest.fixture
async def repo(hass_with_tmp_config: HomeAssistant) -> AsyncGenerator[InventoryRepository, None]:
    repository = InventoryRepository(hass_with_tmp_config, db_filename="test_import_export.db")
    await repository.async_initialize()
    try:
        yield repository
    finally:
        await repository.async_close()


@pytest.fixture
async def coordinator(
    hass_with_tmp_config: HomeAssistant, repo: InventoryRepository
) -> SimpleInventoryCoordinator:
    await repo.upsert_inventory(SOURCE, "Kitchen", entry_type="inventory")
    await repo.upsert_inventory(TARGET, "Cabin", entry_type="inventory")
    entry = MagicMock()
    entry.entry_id = SOURCE
    return SimpleInventoryCoordinator(
        hass_with_tmp_config, entry, repo, InventoryHub(hass_with_tmp_config, repo)
    )


async def _seed_full_item(
    coordinator: SimpleInventoryCoordinator, description: str = "Whole milk"
) -> None:
    """Add an item with every field set to a non-default value."""
    await coordinator.async_add_item(
        SOURCE,
        **{
            FIELD_NAME: "Milk",
            FIELD_DESCRIPTION: description,
            FIELD_QUANTITY: 2.5,
            FIELD_UNIT: "L",
            FIELD_PRICE: 1.25,
            FIELD_EXPIRY_DATE: "2030-01-15",
            FIELD_ICON: "mdi:cup",
            FIELD_EXPIRY_ALERT_DAYS: 3,
            FIELD_AUTO_ADD_ENABLED: True,
            FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED: True,
            FIELD_AUTO_ADD_TO_LIST_QUANTITY: 1.5,
            FIELD_DESIRED_QUANTITY: 4.0,
            FIELD_TODO_LIST: "todo.shopping",
            FIELD_TODO_QUANTITY_PLACEMENT: "description",
            FIELD_LOCATION: "Fridge, Door",
            FIELD_CATEGORY: "Dairy, Breakfast",
            FIELD_BARCODE: "0123456789012, 5000000000001",
            FIELD_ALIASES: "moo juice, lait",
        },
    )


async def _seed_simple_item(
    coordinator: SimpleInventoryCoordinator,
    inventory_id: str,
    name: str,
    **fields: Any,
) -> None:
    await coordinator.async_add_item(inventory_id, **{FIELD_NAME: name, **fields})


def _comparable(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop volatile keys; batch IDs are database-local so they are dropped too."""
    return [
        {
            **{k: v for k, v in item.items() if k not in _VOLATILE_KEYS},
            "batches": [
                {k: v for k, v in batch.items() if k != "id"} for batch in item.get("batches", [])
            ],
        }
        for item in items
    ]


async def _item(
    coordinator: SimpleInventoryCoordinator, inventory_id: str, name: str
) -> dict[str, Any] | None:
    for item in await coordinator.async_list_items(inventory_id):
        if item[FIELD_NAME].lower() == name.lower():
            return item
    return None


async def _history(
    coordinator: SimpleInventoryCoordinator, inventory_id: str
) -> list[dict[str, Any]]:
    return await coordinator.repository.get_inventory_history(inventory_id)


# ---------------------------------------------------------------------------
# 1. Round trip preserves every field
# ---------------------------------------------------------------------------


async def test_json_round_trip_preserves_every_field(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    await _seed_full_item(coordinator)

    exported = await coordinator.async_export_inventory(SOURCE, "json")
    assert isinstance(exported, dict)
    # The derived "(inventory_id)" tag is not part of the exported description.
    assert exported["items"][0][FIELD_DESCRIPTION] == "Whole milk"
    assert exported["items"][0][FIELD_ICON] == "mdi:cup"
    # Simulate the websocket transport.
    payload = json.loads(json.dumps(exported))
    summary = await coordinator.async_import_inventory(TARGET, payload, "json")

    assert summary == {"added": 1, "updated": 0, "skipped": 0, "errors": []}
    source_items = await coordinator.async_list_items(SOURCE)
    target_items = await coordinator.async_list_items(TARGET)
    assert _comparable(target_items) == _comparable(source_items)
    target = target_items[0]
    assert target[FIELD_LOCATIONS] == ["Fridge", "Door"]
    assert target[FIELD_CATEGORIES] == ["Dairy", "Breakfast"]
    assert target[FIELD_BARCODES] == ["0123456789012", "5000000000001"]
    assert sorted(target[FIELD_ALIASES]) == ["lait", "moo juice"]
    # The inventory-ID tag follows the target inventory instead of being stacked.
    assert source_items[0][FIELD_DESCRIPTION] == f"Whole milk ({SOURCE})"
    assert target[FIELD_DESCRIPTION] == f"Whole milk ({TARGET})"


async def test_json_import_of_tagged_legacy_export_retags_description(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    """Older exports kept the source "(inventory_id)" tag in the description."""
    data = {
        "items": [
            {
                "inventory_id": SOURCE,
                FIELD_NAME: "Milk",
                FIELD_DESCRIPTION: f"Whole milk ({SOURCE})",
                FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED: True,
            }
        ]
    }

    await coordinator.async_import_inventory(TARGET, data, "json")

    item = await _item(coordinator, TARGET, "Milk")
    assert item is not None
    assert item[FIELD_DESCRIPTION] == f"Whole milk ({TARGET})"


async def test_csv_round_trip_preserves_every_field(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    await _seed_full_item(coordinator, description='=HYPERLINK("http://x")')

    exported = await coordinator.async_export_inventory(SOURCE, "csv")
    assert isinstance(exported, str)
    summary = await coordinator.async_import_inventory(TARGET, exported, "csv")

    assert summary == {"added": 1, "updated": 0, "skipped": 0, "errors": []}
    source_items = await coordinator.async_list_items(SOURCE)
    target_items = await coordinator.async_list_items(TARGET)
    assert _comparable(target_items) == _comparable(source_items)
    target = target_items[0]
    assert target[FIELD_BARCODES] == ["0123456789012", "5000000000001"]
    assert target[FIELD_LOCATIONS] == ["Fridge", "Door"]
    assert target[FIELD_DESCRIPTION] == f'=HYPERLINK("http://x") ({TARGET})'
    assert target[FIELD_ICON] == "mdi:cup"
    assert next(csv.DictReader(io.StringIO(exported)))[FIELD_ICON] == "mdi:cup"


@pytest.mark.parametrize("fmt", ["json", "csv"])
async def test_every_registry_field_round_trips(
    coordinator: SimpleInventoryCoordinator, fmt: str
) -> None:
    """A field added to ITEM_FIELDS must survive export -> import (extend the seed too)."""
    await _seed_full_item(coordinator)

    exported = await coordinator.async_export_inventory(SOURCE, fmt)
    if isinstance(exported, dict):
        exported = json.loads(json.dumps(exported))
    summary = await coordinator.async_import_inventory(TARGET, exported, fmt)

    assert summary["errors"] == []
    source = await _item(coordinator, SOURCE, "Milk")
    target = await _item(coordinator, TARGET, "Milk")
    assert source is not None and target is not None
    for field in ITEM_FIELDS:
        if field.name == FIELD_IMAGE:
            continue  # Only a has-image flag is exported; image files are not (I15).
        value = source[field.name]
        assert value != field.export_default, f"_seed_full_item must set {field.name}"
        if field.name == FIELD_DESCRIPTION:
            # The derived "(inventory_id)" tag follows the owning inventory.
            assert target[field.name] == value.replace(f"({SOURCE})", f"({TARGET})")
        else:
            assert target[field.name] == value, field.name


async def test_json_import_falls_back_to_scalar_location_and_category(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    data = {
        "items": [
            {
                FIELD_NAME: "Rice",
                FIELD_LOCATION: "Pantry, Shelf",
                FIELD_CATEGORY: "Grains",
                FIELD_BARCODE: "111, 222",
            }
        ]
    }

    summary = await coordinator.async_import_inventory(TARGET, data, "json")

    assert summary["added"] == 1
    item = await _item(coordinator, TARGET, "Rice")
    assert item is not None
    assert item[FIELD_LOCATIONS] == ["Pantry", "Shelf"]
    assert item[FIELD_CATEGORIES] == ["Grains"]
    assert item[FIELD_BARCODES] == ["111", "222"]


# ---------------------------------------------------------------------------
# 2. Validation parity with the service path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("bad_fields", "message"),
    [
        ({FIELD_QUANTITY: -1}, FIELD_QUANTITY),
        ({FIELD_QUANTITY: "lots"}, FIELD_QUANTITY),
        ({FIELD_QUANTITY: float("inf")}, FIELD_QUANTITY),
        ({FIELD_PRICE: -0.5}, FIELD_PRICE),
        ({FIELD_DESIRED_QUANTITY: -2}, FIELD_DESIRED_QUANTITY),
        ({FIELD_AUTO_ADD_TO_LIST_QUANTITY: -1}, FIELD_AUTO_ADD_TO_LIST_QUANTITY),
        ({FIELD_EXPIRY_ALERT_DAYS: -1}, FIELD_EXPIRY_ALERT_DAYS),
        ({FIELD_EXPIRY_ALERT_DAYS: 2.5}, FIELD_EXPIRY_ALERT_DAYS),
        ({FIELD_EXPIRY_ALERT_DAYS: 400}, FIELD_EXPIRY_ALERT_DAYS),
        ({FIELD_TODO_QUANTITY_PLACEMENT: "sideways"}, FIELD_TODO_QUANTITY_PLACEMENT),
        ({FIELD_EXPIRY_DATE: "31/12/2030"}, FIELD_EXPIRY_DATE),
        ({FIELD_EXPIRY_DATE: "2030-13-01"}, FIELD_EXPIRY_DATE),
        ({FIELD_AUTO_ADD_ENABLED: "maybe"}, FIELD_AUTO_ADD_ENABLED),
        ({FIELD_TODO_LIST: "light.kitchen"}, FIELD_TODO_LIST),
        ({FIELD_AUTO_ADD_ENABLED: True, FIELD_TODO_LIST: ""}, "todo list"),
        ({FIELD_LOCATIONS: [{"nested": True}]}, FIELD_LOCATIONS),
        ({FIELD_ICON: "cup"}, FIELD_ICON),
        ({FIELD_ICON: ["mdi:cup"]}, FIELD_ICON),
    ],
)
async def test_import_rejects_invalid_record(
    coordinator: SimpleInventoryCoordinator, bad_fields: dict[str, Any], message: str
) -> None:
    data = {"items": [{FIELD_NAME: "Bad", **bad_fields}, {FIELD_NAME: "Good", FIELD_QUANTITY: 1}]}

    summary = await coordinator.async_import_inventory(TARGET, data, "json")

    assert summary["added"] == 1
    assert len(summary["errors"]) == 1
    assert summary["errors"][0].startswith("Item 1 ('Bad'): ")
    assert message in summary["errors"][0]
    assert await _item(coordinator, TARGET, "Bad") is None
    assert await _item(coordinator, TARGET, "Good") is not None
    assert [e["event_type"] for e in await _history(coordinator, TARGET)] == ["import"]


async def test_import_normalises_valid_values(coordinator: SimpleInventoryCoordinator) -> None:
    data = [
        {
            FIELD_NAME: "  Beans  ",
            FIELD_QUANTITY: "0.1",
            FIELD_EXPIRY_ALERT_DAYS: "7",
            FIELD_EXPIRY_DATE: "2030-1-5",
            FIELD_AUTO_ADD_ENABLED: "false",
        }
    ]

    summary = await coordinator.async_import_inventory(TARGET, data, "json")

    assert summary["errors"] == []
    item = await _item(coordinator, TARGET, "Beans")
    assert item is not None
    assert item[FIELD_NAME] == "Beans"
    assert item[FIELD_QUANTITY] == 0.1
    assert item[FIELD_EXPIRY_ALERT_DAYS] == 7
    assert item[FIELD_EXPIRY_DATE] == "2030-01-05"
    assert item[FIELD_AUTO_ADD_ENABLED] is False


async def test_overwrite_with_invalid_record_leaves_item_untouched(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    await _seed_simple_item(coordinator, TARGET, "Milk", **{FIELD_QUANTITY: 5})
    data = {"items": [{FIELD_NAME: "Milk", FIELD_QUANTITY: 9, FIELD_PRICE: -1}]}

    summary = await coordinator.async_import_inventory(TARGET, data, "json", "overwrite")

    assert summary["updated"] == 0
    assert len(summary["errors"]) == 1
    item = await _item(coordinator, TARGET, "Milk")
    assert item is not None
    assert item[FIELD_QUANTITY] == 5


async def test_merge_quantities_rejects_negative_quantity(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    await _seed_simple_item(coordinator, TARGET, "Milk", **{FIELD_QUANTITY: 5})
    data = {"items": [{FIELD_NAME: "Milk", FIELD_QUANTITY: -10}]}

    summary = await coordinator.async_import_inventory(TARGET, data, "json", "merge_quantities")

    assert summary["updated"] == 0
    assert len(summary["errors"]) == 1
    item = await _item(coordinator, TARGET, "Milk")
    assert item is not None
    assert item[FIELD_QUANTITY] == 5


# ---------------------------------------------------------------------------
# 3. Malformed containers / entries
# ---------------------------------------------------------------------------


async def test_import_non_list_items_reports_error(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    summary = await coordinator.async_import_inventory(TARGET, {"items": "Milk"}, "json")

    assert summary["added"] == 0
    assert len(summary["errors"]) == 1
    assert "items" in summary["errors"][0]


async def test_import_non_dict_entries_reported_and_skipped(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    data = {"items": [1, "Milk", None, {FIELD_NAME: "Bread"}]}

    summary = await coordinator.async_import_inventory(TARGET, data, "json")

    assert summary["added"] == 1
    assert [e.split(":")[0] for e in summary["errors"]] == ["Item 1", "Item 2", "Item 3"]
    assert await _item(coordinator, TARGET, "Bread") is not None


async def test_import_unknown_merge_strategy_reports_error(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    await _seed_simple_item(coordinator, TARGET, "Milk")

    summary = await coordinator.async_import_inventory(
        TARGET, [{FIELD_NAME: "Milk"}], "json", "replace_everything"
    )

    assert summary["added"] == summary["updated"] == 0
    assert len(summary["errors"]) == 1


# ---------------------------------------------------------------------------
# 4. Per-item atomicity
# ---------------------------------------------------------------------------


async def test_new_item_with_conflicting_barcode_is_not_created(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    await _seed_simple_item(coordinator, TARGET, "Cheese", **{FIELD_BARCODE: "111"})
    history_before = await _history(coordinator, TARGET)
    data = {
        "items": [
            {
                FIELD_NAME: "Milk",
                FIELD_QUANTITY: 2,
                FIELD_LOCATIONS: ["Fridge"],
                "barcodes": ["111"],
            }
        ]
    }

    summary = await coordinator.async_import_inventory(TARGET, data, "json")

    assert summary["added"] == 0
    assert len(summary["errors"]) == 1
    assert summary["errors"][0].startswith("Item 1 ('Milk'): ")
    assert await _item(coordinator, TARGET, "Milk") is None
    assert await _history(coordinator, TARGET) == history_before
    cheese = await _item(coordinator, TARGET, "Cheese")
    assert cheese is not None
    assert cheese[FIELD_BARCODES] == ["111"]


async def test_overwrite_failure_restores_item(coordinator: SimpleInventoryCoordinator) -> None:
    await _seed_simple_item(
        coordinator, TARGET, "Cheese", **{FIELD_BARCODE: "111", FIELD_ALIASES: "cheddar"}
    )
    await _seed_simple_item(
        coordinator,
        TARGET,
        "Milk",
        **{FIELD_QUANTITY: 5, FIELD_BARCODE: "999", FIELD_LOCATION: "Fridge"},
    )
    before = await _item(coordinator, TARGET, "Milk")
    history_before = await _history(coordinator, TARGET)
    data = {
        "items": [
            {
                FIELD_NAME: "Milk",
                FIELD_QUANTITY: 8,
                FIELD_BARCODES: ["222"],
                FIELD_ALIASES: ["cheddar"],  # owned by Cheese -> conflict
                FIELD_LOCATIONS: ["Pantry"],
            }
        ]
    }

    summary = await coordinator.async_import_inventory(TARGET, data, "json", "overwrite")

    assert summary["updated"] == 0
    assert len(summary["errors"]) == 1
    after = await _item(coordinator, TARGET, "Milk")
    assert after is not None and before is not None
    assert _comparable([after]) == _comparable([before])
    assert await _history(coordinator, TARGET) == history_before


async def test_import_fires_update_event_when_items_written(
    hass_with_tmp_config: HomeAssistant, coordinator: SimpleInventoryCoordinator
) -> None:
    events: list[Event] = []
    hass_with_tmp_config.bus.async_listen(f"{DOMAIN}_updated_{TARGET}", events.append)

    await coordinator.async_import_inventory(TARGET, [{FIELD_NAME: "Milk"}], "json")
    await hass_with_tmp_config.async_block_till_done()

    assert len(events) == 1


# ---------------------------------------------------------------------------
# 5. CSV per-row errors
# ---------------------------------------------------------------------------


async def test_csv_bad_row_reported_and_other_rows_imported(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    csv_data = "name,quantity,expiry_alert_days\nMilk,2,1\nBread,lots,1\nEggs,12,x\nJam,1,\n"

    summary = await coordinator.async_import_inventory(TARGET, csv_data, "csv")

    assert summary["added"] == 2
    assert len(summary["errors"]) == 2
    assert summary["errors"][0].startswith("Row 3 ('Bread'): ")
    assert summary["errors"][1].startswith("Row 4 ('Eggs'): ")
    jam = await _item(coordinator, TARGET, "Jam")
    assert jam is not None
    assert jam[FIELD_EXPIRY_ALERT_DAYS] == 0


async def test_csv_import_reads_barcodes_column(coordinator: SimpleInventoryCoordinator) -> None:
    csv_data = 'name,barcodes,aliases\nMilk,"111, 222",moo\n'

    summary = await coordinator.async_import_inventory(TARGET, csv_data, "csv")

    assert summary["errors"] == []
    item = await _item(coordinator, TARGET, "Milk")
    assert item is not None
    assert item[FIELD_BARCODES] == ["111", "222"]
    assert item[FIELD_ALIASES] == ["moo"]


# ---------------------------------------------------------------------------
# 6. CSV formula injection
# ---------------------------------------------------------------------------


async def test_csv_export_neutralises_formula_cells(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    # Names are whitespace-stripped on add, so tab/CR prefixes are exercised via `unit`.
    cells = (("=cmd", "\tTab"), ("@sum", "-1"), ("+plus", "\rcr"), ("'=quoted", "ok"))
    for name, unit in cells:
        await _seed_simple_item(coordinator, SOURCE, name, **{FIELD_UNIT: unit})

    exported = await coordinator.async_export_inventory(SOURCE, "csv")
    assert isinstance(exported, str)

    rows = {row[FIELD_NAME]: row[FIELD_UNIT] for row in csv.DictReader(io.StringIO(exported))}
    assert rows == {
        "'=cmd": "'\tTab",
        "'@sum": "'-1",
        "'+plus": "'\rcr",
        "''=quoted": "ok",
    }

    summary = await coordinator.async_import_inventory(TARGET, exported, "csv")
    assert summary["errors"] == []
    imported = {i[FIELD_NAME]: i[FIELD_UNIT] for i in await coordinator.async_list_items(TARGET)}
    assert imported == dict(cells)


# ---------------------------------------------------------------------------
# 7. Overwrite replaces only fields present in the record
# ---------------------------------------------------------------------------


async def test_overwrite_only_replaces_present_fields(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    await _seed_full_item(coordinator)
    before = await _item(coordinator, SOURCE, "Milk")
    assert before is not None

    summary = await coordinator.async_import_inventory(
        SOURCE, [{FIELD_NAME: "milk", FIELD_QUANTITY: 9}], "json", "overwrite"
    )

    assert summary == {"added": 0, "updated": 1, "skipped": 0, "errors": []}
    after = await _item(coordinator, SOURCE, "Milk")
    assert after is not None
    assert after[FIELD_QUANTITY] == 9
    expected = {
        **before,
        FIELD_QUANTITY: 9,
        # Stock is replaced by one batch; unspecified batch fields keep the item's values.
        "batches": [{**before["batches"][0], FIELD_QUANTITY: 9}],
    }
    assert _comparable([after]) == _comparable([expected])
    assert after[FIELD_DESCRIPTION] == before[FIELD_DESCRIPTION]


async def test_overwrite_present_relations_replace_and_clear(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    await _seed_full_item(coordinator)

    summary = await coordinator.async_import_inventory(
        SOURCE,
        [{FIELD_NAME: "Milk", FIELD_LOCATION: "Garage", FIELD_CATEGORIES: [], FIELD_BARCODES: []}],
        "json",
        "overwrite",
    )

    assert summary["updated"] == 1
    after = await _item(coordinator, SOURCE, "Milk")
    assert after is not None
    assert after[FIELD_LOCATIONS] == ["Garage"]
    assert after[FIELD_CATEGORIES] == []
    assert after[FIELD_BARCODES] == []
    assert sorted(after[FIELD_ALIASES]) == ["lait", "moo juice"]
    assert after[FIELD_PRICE] == 1.25


async def test_overwrite_records_quantity_delta_in_history(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    await _seed_simple_item(coordinator, TARGET, "Milk", **{FIELD_QUANTITY: 5})

    await coordinator.async_import_inventory(
        TARGET, [{FIELD_NAME: "Milk", FIELD_QUANTITY: 8}], "json", "overwrite"
    )

    imports = [e for e in await _history(coordinator, TARGET) if e["event_type"] == "import"]
    # Overwrite replaces the stock: the old batch is emptied, then the new one is added.
    assert sorted((e["quantity_before"], e["quantity_after"], e["amount"]) for e in imports) == [
        (0, 8, 8),
        (5, 0, 5),
    ]


async def test_merge_quantities_adds_and_records_applied_amount(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    await _seed_simple_item(coordinator, TARGET, "Milk", **{FIELD_QUANTITY: 0.1})

    summary = await coordinator.async_import_inventory(
        TARGET,
        [{FIELD_NAME: "Milk", FIELD_QUANTITY: 0.2}, {FIELD_NAME: "Milk", FIELD_QUANTITY: 0}],
        "json",
        "merge_quantities",
    )

    assert summary == {"added": 0, "updated": 1, "skipped": 1, "errors": []}
    item = await _item(coordinator, TARGET, "Milk")
    assert item is not None
    assert item[FIELD_QUANTITY] == 0.3
    imports = [e for e in await _history(coordinator, TARGET) if e["event_type"] == "import"]
    assert len(imports) == 1
    assert imports[0]["amount"] == 0.2


# ---------------------------------------------------------------------------
# 8. Existing-name detection (case-insensitive, within one import too)
# ---------------------------------------------------------------------------


async def test_duplicate_names_within_import_are_skipped(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    data = [{FIELD_NAME: "Milk", FIELD_QUANTITY: 1}, {FIELD_NAME: "MILK", FIELD_QUANTITY: 4}]

    summary = await coordinator.async_import_inventory(TARGET, data, "json")

    assert summary == {"added": 1, "updated": 0, "skipped": 1, "errors": []}
    items = await coordinator.async_list_items(TARGET)
    assert [(i[FIELD_NAME], i[FIELD_QUANTITY]) for i in items] == [("Milk", 1)]


# ---------------------------------------------------------------------------
# 9. Batches
# ---------------------------------------------------------------------------


def _batches(item: dict[str, Any] | None) -> list[tuple[Any, ...]]:
    assert item is not None
    return [
        (b["quantity"], b["expiry_date"], b["location"], b["unit_price"], b["purchased_at"])
        for b in item["batches"]
    ]


async def _seed_two_batches(coordinator: SimpleInventoryCoordinator) -> None:
    await coordinator.async_add_item(
        SOURCE, name="Milk", quantity=2, expiry_date="2026-11-01", location="Fridge", price=1.5
    )
    await coordinator.async_increment_item(
        SOURCE, "Milk", 1, price=2, location="Garage", purchased_at="2026-09-30"
    )


@pytest.mark.parametrize("fmt", ["json", "csv"])
async def test_round_trip_preserves_batches(
    coordinator: SimpleInventoryCoordinator, fmt: str
) -> None:
    await _seed_two_batches(coordinator)
    exported = await coordinator.async_export_inventory(SOURCE, fmt)
    payload = json.loads(json.dumps(exported)) if fmt == "json" else exported

    summary = await coordinator.async_import_inventory(TARGET, payload, fmt)

    assert summary["errors"] == [] and summary["added"] == 1
    source = _batches(await _item(coordinator, SOURCE, "Milk"))
    assert len(source) == 2
    assert _batches(await _item(coordinator, TARGET, "Milk")) == source


async def test_json_export_batches_carry_no_database_ids(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    await _seed_two_batches(coordinator)
    exported = await coordinator.async_export_inventory(SOURCE, "json")
    assert isinstance(exported, dict)
    assert all("id" not in batch for batch in exported["items"][0]["batches"])


async def test_csv_export_batches_column_is_id_less_json(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    await _seed_two_batches(coordinator)
    exported = await coordinator.async_export_inventory(SOURCE, "csv")
    assert isinstance(exported, str)
    [row] = list(csv.DictReader(io.StringIO(exported)))
    batches = json.loads(row["batches"])
    assert len(batches) == 2
    assert all("id" not in batch for batch in batches)


async def test_old_export_without_batches_imports_as_one_batch(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    data = {
        "items": [
            {
                "name": "Rice",
                "quantity": 3,
                "expiry_date": "2027-01-01",
                "location": "Pantry",
                "price": 4,
            }
        ]
    }
    await coordinator.async_import_inventory(TARGET, data, "json")
    [(quantity, expiry, location, unit_price, _purchased)] = _batches(
        await _item(coordinator, TARGET, "Rice")
    )
    assert (quantity, expiry, location, unit_price) == (3, "2027-01-01", "Pantry", 4)


async def test_old_csv_without_batches_column_imports_as_one_batch(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    csv_data = "name,quantity,expiry_date,location\nRice,3,2027-01-01,Pantry\n"

    summary = await coordinator.async_import_inventory(TARGET, csv_data, "csv")

    assert summary["errors"] == []
    assert [b[:3] for b in _batches(await _item(coordinator, TARGET, "Rice"))] == [
        (3, "2027-01-01", "Pantry")
    ]


async def test_old_json_without_icon_imports_with_default_icon(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    summary = await coordinator.async_import_inventory(
        TARGET, {"items": [{FIELD_NAME: "Rice", FIELD_QUANTITY: 3}]}, "json"
    )

    assert summary["errors"] == []
    item = await _item(coordinator, TARGET, "Rice")
    assert item is not None and item[FIELD_ICON] == ""


async def test_old_csv_without_icon_column_imports_with_default_icon(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    summary = await coordinator.async_import_inventory(TARGET, "name,quantity\nRice,3\n", "csv")

    assert summary["errors"] == []
    item = await _item(coordinator, TARGET, "Rice")
    assert item is not None and item[FIELD_ICON] == ""


async def test_overwrite_icon_is_kept_when_absent_and_set_or_cleared_when_present(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    await _seed_simple_item(coordinator, TARGET, "Rice", **{FIELD_ICON: "mdi:rice"})

    async def icon_after(data: Any, fmt: str) -> str:
        summary = await coordinator.async_import_inventory(TARGET, data, fmt, "overwrite")
        assert summary["errors"] == []
        item = await _item(coordinator, TARGET, "Rice")
        assert item is not None
        return str(item[FIELD_ICON])

    assert await icon_after([{FIELD_NAME: "Rice", FIELD_UNIT: "kg"}], "json") == "mdi:rice"
    assert await icon_after("name,unit\nRice,g\n", "csv") == "mdi:rice"
    assert await icon_after([{FIELD_NAME: "Rice", FIELD_ICON: " mdi:grain "}], "json") == (
        "mdi:grain"
    )
    assert await icon_after("name,icon\nRice,\n", "csv") == ""


async def test_export_reports_only_whether_an_item_has_an_image(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    await _seed_simple_item(coordinator, SOURCE, "Milk")
    await _seed_simple_item(coordinator, SOURCE, "Rice")
    milk = await _item(coordinator, SOURCE, "Milk")
    assert milk is not None
    await coordinator.repository.update_item(milk["id"], {FIELD_IMAGE: "18f3a2b4c5d6e7f8abcd1234"})

    exported = await coordinator.async_export_inventory(SOURCE, "json")
    assert isinstance(exported, dict)
    assert {item[FIELD_NAME]: item[FIELD_IMAGE] for item in exported["items"]} == {
        "Milk": True,
        "Rice": False,
    }
    csv_text = await coordinator.async_export_inventory(SOURCE, "csv")
    assert isinstance(csv_text, str)
    rows = {row[FIELD_NAME]: row[FIELD_IMAGE] for row in csv.DictReader(io.StringIO(csv_text))}
    assert rows == {"Milk": "1", "Rice": "0"}


async def test_import_ignores_the_image_flag(coordinator: SimpleInventoryCoordinator) -> None:
    await _seed_simple_item(coordinator, TARGET, "Rice")

    json_summary = await coordinator.async_import_inventory(
        TARGET,
        [{FIELD_NAME: "Milk", FIELD_IMAGE: True}, {FIELD_NAME: "Rice", FIELD_IMAGE: True}],
        "json",
        "overwrite",
    )
    csv_summary = await coordinator.async_import_inventory(TARGET, "name,image\nTea,1\n", "csv")

    assert json_summary["errors"] == [] and csv_summary["errors"] == []
    for name in ("Milk", "Rice", "Tea"):
        item = await _item(coordinator, TARGET, name)
        assert item is not None and item[FIELD_IMAGE] == ""


async def test_merge_quantities_adds_a_batch(coordinator: SimpleInventoryCoordinator) -> None:
    await coordinator.async_add_item(SOURCE, name="Milk", quantity=2, expiry_date="2026-11-01")
    data = {"items": [{"name": "Milk", "quantity": 1, "expiry_date": "2026-12-01"}]}

    await coordinator.async_import_inventory(SOURCE, data, "json", "merge_quantities")

    item = await _item(coordinator, SOURCE, "Milk")
    assert [(b[0], b[1]) for b in _batches(item)] == [(2, "2026-11-01"), (1, "2026-12-01")]


async def test_overwrite_with_batches_replaces_stock(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    await coordinator.async_add_item(SOURCE, name="Milk", quantity=5)
    data = {"items": [{"name": "Milk", "batches": [{"quantity": 1, "expiry_date": "2026-11-01"}]}]}

    summary = await coordinator.async_import_inventory(SOURCE, data, "json", "overwrite")

    assert summary["updated"] == 1
    item = await _item(coordinator, SOURCE, "Milk")
    assert [(b[0], b[1]) for b in _batches(item)] == [(1, "2026-11-01")]
    imports = [h for h in await _history(coordinator, SOURCE) if h["event_type"] == "import"]
    assert sorted((h["quantity_before"], h["quantity_after"]) for h in imports) == [(0, 1), (5, 0)]


async def test_overwrite_failure_after_stock_replacement_restores_batches(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    await _seed_simple_item(coordinator, SOURCE, "Cheese", **{FIELD_BARCODE: "111"})
    await _seed_two_batches(coordinator)
    before = _batches(await _item(coordinator, SOURCE, "Milk"))
    history_before = await _history(coordinator, SOURCE)
    data = {
        "items": [
            {
                "name": "Milk",
                "batches": [{"quantity": 7, "expiry_date": "2027-01-01", "location": "Shed"}],
                FIELD_BARCODES: ["111"],  # owned by Cheese -> conflict after stock replacement
            }
        ]
    }

    summary = await coordinator.async_import_inventory(SOURCE, data, "json", "overwrite")

    assert summary["updated"] == 0
    assert len(summary["errors"]) == 1
    milk = await _item(coordinator, SOURCE, "Milk")
    assert _batches(milk) == before
    assert milk is not None and milk[FIELD_QUANTITY] == 3
    assert await _history(coordinator, SOURCE) == history_before


@pytest.mark.parametrize(
    "bad",
    [
        [{"quantity": -1}],
        [{"quantity": 0}],
        [{"quantity": 1, "expiry_date": "11/01/2026"}],
        [{"quantity": 1, "unit_price": -2}],
        [{"quantity": 1, "purchased_at": "yesterday"}],
        [{"expiry_date": "2026-11-01"}],
        ["batch"],
        "not-a-list",
    ],
)
async def test_invalid_batches_reject_the_record(
    coordinator: SimpleInventoryCoordinator, bad: Any
) -> None:
    data = {"items": [{"name": "Milk", "batches": bad}]}

    summary = await coordinator.async_import_inventory(TARGET, data, "json")

    assert summary["added"] == 0
    assert len(summary["errors"]) == 1 and summary["errors"][0].startswith("Item 1 ('Milk')")
    assert await _item(coordinator, TARGET, "Milk") is None


async def test_import_history_rows_have_import_source(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    await _seed_simple_item(coordinator, TARGET, "Milk", **{FIELD_QUANTITY: 5})
    data = [{FIELD_NAME: "Milk", FIELD_QUANTITY: 8}, {FIELD_NAME: "Bread", FIELD_QUANTITY: 1}]

    await coordinator.async_import_inventory(TARGET, data, "json", "overwrite")
    await coordinator.async_import_inventory(
        TARGET, [{FIELD_NAME: "Milk", FIELD_QUANTITY: 1}], "json", "merge_quantities"
    )

    imports = [e for e in await _history(coordinator, TARGET) if e["event_type"] == "import"]
    assert len(imports) == 4
    assert {e["source"] for e in imports} == {"import"}


@pytest.mark.parametrize("strategy", ["overwrite", "merge_quantities"])
async def test_import_fires_no_per_item_quantity_events(
    hass_with_tmp_config: HomeAssistant, coordinator: SimpleInventoryCoordinator, strategy: str
) -> None:
    await _seed_simple_item(coordinator, TARGET, "Milk")
    await hass_with_tmp_config.async_block_till_done()
    lifecycle: list[Event] = []
    updated: list[Event] = []
    for suffix in ("item_restocked", "item_depleted", "item_quantity_changed"):
        hass_with_tmp_config.bus.async_listen(f"{DOMAIN}_{suffix}", lifecycle.append)
    hass_with_tmp_config.bus.async_listen(f"{DOMAIN}_updated_{TARGET}", updated.append)
    data = [{FIELD_NAME: "Milk", FIELD_QUANTITY: 3}, {FIELD_NAME: "Bread", FIELD_QUANTITY: 2}]

    summary = await coordinator.async_import_inventory(TARGET, data, "json", strategy)
    await hass_with_tmp_config.async_block_till_done()

    assert summary["errors"] == []
    assert lifecycle == []
    assert len(updated) == 1


async def test_overwrite_expiry_without_stock_updates_the_single_batch(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    await coordinator.async_add_item(
        SOURCE, name="Milk", quantity=2, expiry_date="2026-11-01", price=1.5
    )
    data = [{FIELD_NAME: "Milk", FIELD_EXPIRY_DATE: "2027-01-01", FIELD_PRICE: 3}]

    summary = await coordinator.async_import_inventory(SOURCE, data, "json", "overwrite")

    assert summary == {"added": 0, "updated": 1, "skipped": 0, "errors": []}
    item = await _item(coordinator, SOURCE, "Milk")
    assert item is not None
    assert [(b[0], b[1], b[3]) for b in _batches(item)] == [(2, "2027-01-01", 3)]
    assert (item[FIELD_EXPIRY_DATE], item[FIELD_PRICE]) == ("2027-01-01", 3)


@pytest.mark.parametrize(
    ("record", "count"),
    [({FIELD_EXPIRY_DATE: "2027-01-01"}, 2), ({FIELD_PRICE: 9}, 2)],
)
async def test_overwrite_batch_field_on_multi_batch_item_is_rejected(
    coordinator: SimpleInventoryCoordinator, record: dict[str, Any], count: int
) -> None:
    await _seed_two_batches(coordinator)
    before = await _item(coordinator, SOURCE, "Milk")
    history_before = await _history(coordinator, SOURCE)

    summary = await coordinator.async_import_inventory(
        SOURCE, [{FIELD_NAME: "Milk", FIELD_UNIT: "L", **record}], "json", "overwrite"
    )

    assert summary["updated"] == 0
    assert len(summary["errors"]) == 1
    assert summary["errors"][0].startswith("Item 1 ('Milk'): ")
    assert f"{count} batches" in summary["errors"][0]
    after = await _item(coordinator, SOURCE, "Milk")
    assert after is not None and before is not None
    assert _comparable([after]) == _comparable([before])
    assert await _history(coordinator, SOURCE) == history_before


async def test_overwrite_expiry_on_item_without_batches_is_rejected(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    await _seed_simple_item(coordinator, SOURCE, "Milk", **{FIELD_QUANTITY: 0})

    summary = await coordinator.async_import_inventory(
        SOURCE, [{FIELD_NAME: "Milk", FIELD_EXPIRY_DATE: "2027-01-01"}], "json", "overwrite"
    )

    assert summary["updated"] == 0
    assert summary["errors"] == [
        "Item 1 ('Milk'): Milk has no stock; restock it with an expiry date instead"
    ]
    item = await _item(coordinator, SOURCE, "Milk")
    assert item is not None and item[FIELD_EXPIRY_DATE] == ""


async def test_overwrite_unchanged_batch_fields_are_a_no_op(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    await _seed_two_batches(coordinator)
    before = await _item(coordinator, SOURCE, "Milk")
    assert before is not None
    record = {
        FIELD_NAME: "Milk",
        FIELD_EXPIRY_DATE: before[FIELD_EXPIRY_DATE],
        FIELD_PRICE: before[FIELD_PRICE],
    }

    summary = await coordinator.async_import_inventory(SOURCE, [record], "json", "overwrite")

    assert summary["errors"] == []
    assert _batches(await _item(coordinator, SOURCE, "Milk")) == _batches(before)


async def test_overwrite_price_on_item_without_batches_sets_item_price(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    await _seed_simple_item(coordinator, SOURCE, "Milk", **{FIELD_QUANTITY: 0})

    summary = await coordinator.async_import_inventory(
        SOURCE, [{FIELD_NAME: "Milk", FIELD_PRICE: 4}], "json", "overwrite"
    )

    assert summary["errors"] == [] and summary["updated"] == 1
    item = await _item(coordinator, SOURCE, "Milk")
    assert item is not None and item[FIELD_PRICE] == 4 and item["batches"] == []


async def test_overwrite_batch_field_failure_restores_the_batch(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    await _seed_simple_item(coordinator, SOURCE, "Cheese", **{FIELD_BARCODE: "111"})
    await coordinator.async_add_item(SOURCE, name="Milk", quantity=2, expiry_date="2026-11-01")
    before = _batches(await _item(coordinator, SOURCE, "Milk"))
    record = {FIELD_NAME: "Milk", FIELD_EXPIRY_DATE: "2027-01-01", FIELD_BARCODES: ["111"]}

    summary = await coordinator.async_import_inventory(SOURCE, [record], "json", "overwrite")

    assert summary["updated"] == 0 and len(summary["errors"]) == 1
    milk = await _item(coordinator, SOURCE, "Milk")
    assert _batches(milk) == before
    assert milk is not None and milk[FIELD_EXPIRY_DATE] == "2026-11-01"


async def test_merge_quantities_batch_uses_record_price(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    await coordinator.async_add_item(SOURCE, name="Milk", quantity=2, price=1)
    data = [{FIELD_NAME: "Milk", FIELD_QUANTITY: 1, FIELD_PRICE: 3}]

    await coordinator.async_import_inventory(SOURCE, data, "json", "merge_quantities")

    item = await _item(coordinator, SOURCE, "Milk")
    assert sorted((b[0], b[3]) for b in _batches(item)) == [(1, 3), (2, 1)]


async def test_import_batch_location_is_first_non_empty_location(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    data = [{FIELD_NAME: "Rice", FIELD_QUANTITY: 3, FIELD_LOCATION: ", Pantry"}]

    summary = await coordinator.async_import_inventory(TARGET, data, "json")

    assert summary["errors"] == []
    assert [b[2] for b in _batches(await _item(coordinator, TARGET, "Rice"))] == ["Pantry"]


async def test_priced_merge_quantities_updates_item_price(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    await coordinator.async_add_item(SOURCE, name="Milk", quantity=1, price=2)
    data = [{FIELD_NAME: "Milk", FIELD_QUANTITY: 1, FIELD_PRICE: 4}]

    await coordinator.async_import_inventory(SOURCE, data, "json", "merge_quantities")

    item = await _item(coordinator, SOURCE, "Milk")
    assert item is not None and item[FIELD_PRICE] == 4
    assert sorted((b[0], b[3]) for b in _batches(item)) == [(1, 2), (1, 4)]


async def test_dry_run_reports_the_same_summary_as_a_real_import(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    data = {"items": [{"name": "Milk", "quantity": 2}, {"name": ""}]}

    preview = await coordinator.async_import_inventory(TARGET, data, "json", dry_run=True)
    real = await coordinator.async_import_inventory(TARGET, data, "json", dry_run=False)

    assert preview["added"] == real["added"] == 1
    assert preview["skipped"] == real["skipped"]
    assert len(preview["errors"]) == len(real["errors"]) == 1


async def test_dry_run_writes_nothing(coordinator: SimpleInventoryCoordinator) -> None:
    data = {"items": [{"name": "Milk", "quantity": 2}]}

    await coordinator.async_import_inventory(TARGET, data, "json", dry_run=True)

    items = await coordinator.async_list_items(TARGET)
    assert items == []


async def test_dry_run_detects_duplicate_names_within_the_same_batch(
    coordinator: SimpleInventoryCoordinator,
) -> None:
    data = {"items": [{"name": "Milk", "quantity": 1}, {"name": "Milk", "quantity": 2}]}

    preview = await coordinator.async_import_inventory(
        TARGET, data, "json", merge_strategy="skip", dry_run=True
    )

    assert preview["added"] == 1
    assert preview["skipped"] == 1


async def test_dry_run_does_not_sync_todo_lists(
    coordinator: SimpleInventoryCoordinator, hass_with_tmp_config: HomeAssistant
) -> None:
    data = {
        "items": [
            {
                "name": "Milk",
                "quantity": 1,
                "auto_add_enabled": True,
                "auto_add_to_list_quantity": 5,
                "todo_list": "todo.shopping",
            }
        ]
    }
    calls: list[Event] = []
    hass_with_tmp_config.bus.async_listen("simple_inventory_item_added_to_list", calls.append)

    await coordinator.async_import_inventory(TARGET, data, "json", dry_run=True)
    await hass_with_tmp_config.async_block_till_done()

    assert calls == []
