"""Cross-inventory search: ranking, casefold matching, scope and the details id filter."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from homeassistant.core import HomeAssistant

from custom_components.simple_inventory.storage.repository import InventoryRepository

_SEED = """
INSERT INTO inventories (id, name) VALUES ('A', 'Zebra'), ('B', 'Fridge'), ('C', 'Orphan');

INSERT INTO items (id, inventory_id, name, description, unit)
VALUES ('cok', 'A', 'Čokolada', '', ''),
       ('butA', 'A', 'Butter', '', ''),
       ('pea', 'A', 'Peanut butter', '', ''),
       ('sug', 'A', 'Brown sugar', 'Dark muscovado', ''),
       ('rice', 'A', 'Rice', '', 'kg'),
       ('juice', 'A', '100% juice', NULL, NULL),
       ('creme', 'A', 'Crème', '', ''),
       ('strasse', 'A', 'Straße', '', ''),
       ('sstrasse', 'A', 'Strasse', '', ''),
       ('butB', 'B', 'Butter', '', ''),
       ('butC', 'C', 'Butter Z', '', '');

INSERT INTO locations (id, inventory_id, name)
VALUES (1, 'A', 'Pantry'), (2, 'A', 'Basement'), (3, 'B', 'Fridge door');
INSERT INTO item_locations (item_id, location_id) VALUES ('cok', 1), ('butB', 3);
INSERT INTO categories (id, name) VALUES (1, 'Dairy');
INSERT INTO item_categories (item_id, category_id) VALUES ('butA', 1);
INSERT INTO item_barcodes (item_id, inventory_id, barcode) VALUES ('butA', 'A', '5099874031102');
INSERT INTO item_aliases (item_id, inventory_id, alias)
VALUES ('cok', 'A', 'dark chocolate'), ('pea', 'A', 'peanut');
INSERT INTO item_batches (id, item_id, inventory_id, quantity, expiry_date, location_id,
                          unit_price, purchased_at, created_at, updated_at)
VALUES ('b1', 'rice', 'A', 1, '', 2, 0, '2026-01-01', '2026-01-01', '2026-01-01');
"""

AB = ["A", "B"]


@pytest.fixture
async def repo(hass_with_tmp_config: HomeAssistant) -> AsyncGenerator[InventoryRepository, None]:
    repository = InventoryRepository(hass_with_tmp_config, db_filename="search.db")
    await repository.async_initialize()
    try:
        conn = repository._connection()
        await conn.executescript(_SEED)
        await conn.commit()
        yield repository
    finally:
        await repository.async_close()


async def test_exact_matches_first_ties_by_inventory_name(repo: InventoryRepository) -> None:
    # Inventory B ("Fridge") sorts before A ("Zebra"): by name, not by id.
    assert await repo.search_items("butter", AB, 50) == [
        ("B", "butB", 0),
        ("A", "butA", 0),
        ("A", "pea", 2),
    ]


async def test_casefold_equal_names_tie_by_item_id(repo: InventoryRepository) -> None:
    # "Straße" (inserted first) and "Strasse" fold equal in one inventory; the id decides.
    assert await repo.search_items("strasse", AB, 50) == [
        ("A", "sstrasse", 0),
        ("A", "strasse", 0),
    ]


async def test_prefix_before_contains(repo: InventoryRepository) -> None:
    assert await repo.search_items("pea", AB, 50) == [("A", "pea", 1)]


@pytest.mark.parametrize(
    ("query", "item_id", "rank"),
    [
        ("dark choc", "cok", 3),
        ("4031", "butA", 4),
        ("dairy", "butA", 5),
        ("pantry", "cok", 6),
        ("basement", "rice", 6),
        ("muscovado", "sug", 7),
        ("kg", "rice", 8),
    ],
)
async def test_field_ranks(repo: InventoryRepository, query: str, item_id: str, rank: int) -> None:
    assert await repo.search_items(query, AB, 50) == [("A", item_id, rank)]


async def test_casefold_matching(repo: InventoryRepository) -> None:
    assert await repo.search_items("čok", AB, 50) == [("A", "cok", 1)]
    assert await repo.search_items("ČOK", AB, 50) == [("A", "cok", 1)]
    assert await repo.search_items("CREME", AB, 50) == []
    assert ("A", "strasse", 0) in await repo.search_items("STRASSE", AB, 50)


async def test_wildcards_are_literal(repo: InventoryRepository) -> None:
    assert await repo.search_items("%", AB, 50) == [("A", "juice", 2)]
    assert await repo.search_items("_", AB, 50) == []


async def test_item_appears_once_with_best_rank(repo: InventoryRepository) -> None:
    assert await repo.search_items("peanut", AB, 50) == [("A", "pea", 1)]


async def test_limit_returns_one_extra_row(repo: InventoryRepository) -> None:
    assert len(await repo.search_items("butter", AB, 1)) == 2


async def test_unlisted_inventory_never_returned(repo: InventoryRepository) -> None:
    assert all(row[0] != "C" for row in await repo.search_items("butter z", AB, 50))
    assert await repo.search_items("butter z", AB, 50) == []


async def test_empty_inputs(repo: InventoryRepository) -> None:
    assert await repo.search_items("", AB, 50) == []
    assert await repo.search_items("butter", [], 50) == []


async def test_null_description_and_unit(repo: InventoryRepository) -> None:
    assert await repo.search_items("juice", AB, 50) == [("A", "juice", 2)]


async def test_details_item_ids_filter(repo: InventoryRepository) -> None:
    full = await repo.list_items_with_details("A")
    butter = next(item for item in full if item["id"] == "butA")
    assert await repo.list_items_with_details("A", item_ids={"butA"}) == [butter]
    rice = next(item for item in full if item["id"] == "rice")
    assert await repo.list_items_with_details("A", item_ids={"rice"}) == [rice]
    assert await repo.list_items_with_details("A", item_ids=set()) == []
