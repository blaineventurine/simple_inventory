"""An item name may not equal another item's alias, nor an alias another item's name.

Item resolution matches names and aliases case-insensitively, so either clash would make
the name ambiguous and the item unaddressable by name.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.exceptions import ServiceValidationError

from ..error_assertions import assert_translated_error
from ..harness import TodoStack


async def _aliases(stack: TodoStack, name: str) -> list[str]:
    items = await stack.coordinators["kitchen"].async_list_items("kitchen")
    [item] = [i for i in items if i["name"] == name]
    return list(item["aliases"])


@pytest.fixture
async def stack(todo_stack: TodoStack) -> TodoStack:
    await todo_stack.call("add_item", inventory_id="kitchen", name="Milk", aliases="whole milk")
    await todo_stack.call("add_item", inventory_id="kitchen", name="Bread")
    return todo_stack


async def test_add_item_name_matching_another_items_alias_is_rejected(stack: TodoStack) -> None:
    with pytest.raises(ServiceValidationError) as err:
        await stack.call("add_item", inventory_id="kitchen", name="Whole Milk")

    assert_translated_error(
        err.value, "name_is_alias", name="Whole Milk", item="Milk", inventory="Kitchen"
    )
    assert await stack.item("kitchen", "Whole Milk") is None


async def test_add_item_alias_matching_another_items_name_is_rejected(stack: TodoStack) -> None:
    with pytest.raises(ServiceValidationError) as err:
        await stack.call("add_item", inventory_id="kitchen", name="Toast", aliases="BREAD, rye")

    assert_translated_error(err.value, "alias_is_item_name", aliases="BREAD", inventory="Kitchen")
    assert await stack.item("kitchen", "Toast") is None


async def test_add_item_alias_matching_another_alias_in_other_case_is_rejected(
    stack: TodoStack,
) -> None:
    with pytest.raises(ServiceValidationError) as err:
        await stack.call("add_item", inventory_id="kitchen", name="Cream", aliases="Whole Milk")

    assert_translated_error(err.value, "alias_conflict", aliases="Whole Milk")
    assert await stack.item("kitchen", "Cream") is None


async def test_rename_onto_another_items_alias_is_rejected(stack: TodoStack) -> None:
    with pytest.raises(ServiceValidationError) as err:
        await stack.call("update_item", inventory_id="kitchen", old_name="Bread", name="whole milk")

    assert_translated_error(
        err.value, "name_is_alias", name="whole milk", item="Milk", inventory="Kitchen"
    )
    assert await stack.item("kitchen", "Bread") is not None


async def test_update_alias_matching_another_items_name_is_rejected(stack: TodoStack) -> None:
    with pytest.raises(ServiceValidationError) as err:
        await stack.call(
            "update_item", inventory_id="kitchen", old_name="Milk", name="Milk", aliases="bread"
        )

    assert_translated_error(err.value, "alias_is_item_name", aliases="bread", inventory="Kitchen")
    assert await _aliases(stack, "Milk") == ["whole milk"]


async def test_alias_equal_to_own_name_is_allowed(stack: TodoStack) -> None:
    await stack.call(
        "update_item", inventory_id="kitchen", old_name="Bread", name="Bread", aliases="BREAD"
    )
    await stack.call("add_item", inventory_id="kitchen", name="Rice", aliases="rice")
    # Renaming an item onto one of its own aliases is fine too.
    await stack.call("update_item", inventory_id="kitchen", old_name="Milk", name="Whole milk")

    assert await _aliases(stack, "Bread") == ["BREAD"]
    assert await _aliases(stack, "Rice") == ["rice"]
    assert await _aliases(stack, "Whole milk") == ["whole milk"]
    await stack.call("increment_item", inventory_id="kitchen", name="whole milk", amount=1)


async def test_unchanged_name_and_aliases_are_not_rechecked(stack: TodoStack) -> None:
    """Data that already clashes (stored before this check) does not block other edits."""
    conn = stack.repo._connection()
    await conn.execute(
        "INSERT INTO item_aliases (item_id, inventory_id, alias) "
        "SELECT id, inventory_id, 'bread' FROM items WHERE name = 'Milk'"
    )
    await conn.commit()

    await stack.call(
        "update_item",
        inventory_id="kitchen",
        old_name="Milk",
        name="Milk",
        aliases="whole milk, bread",
        unit="l",
    )

    assert sorted(await _aliases(stack, "Milk")) == ["bread", "whole milk"]


async def test_import_rejects_clashes_per_record(stack: TodoStack) -> None:
    coordinator = stack.coordinators["kitchen"]
    data = {
        "items": [
            {"name": "Whole milk"},
            {"name": "Toast", "aliases": ["bread"]},
            {"name": "Rice", "aliases": ["basmati"]},
        ]
    }

    result = await coordinator.async_import_inventory("kitchen", data, "json")

    assert result["added"] == 1
    assert len(result["errors"]) == 2
    assert result["errors"][0].startswith("Item 1 ('Whole milk')")
    assert result["errors"][1].startswith("Item 2 ('Toast')")
    assert await stack.item("kitchen", "Whole milk") is None
    assert await stack.item("kitchen", "Toast") is None
    assert await _aliases(stack, "Rice") == ["basmati"]


async def test_csv_overwrite_rejects_alias_matching_another_name(stack: TodoStack) -> None:
    coordinator = stack.coordinators["kitchen"]
    csv_data = "name,aliases\nMilk,bread\n"

    result = await coordinator.async_import_inventory("kitchen", csv_data, "csv", "overwrite")

    assert result["updated"] == 0
    assert len(result["errors"]) == 1
    assert result["errors"][0].startswith("Row 2 ('Milk')")
    assert await _aliases(stack, "Milk") == ["whole milk"]


async def test_ambiguity_error_lists_the_distinct_items(stack: TodoStack) -> None:
    conn = stack.repo._connection()
    await conn.execute(
        "INSERT INTO item_aliases (item_id, inventory_id, alias) "
        "SELECT id, inventory_id, 'bread' FROM items WHERE name = 'Milk'"
    )
    await conn.commit()

    with pytest.raises(ServiceValidationError) as err:
        await stack.call("increment_item", inventory_id="kitchen", name="Bread", amount=1)

    assert_translated_error(
        err.value, "ambiguous_item", name="Bread", inventory="Kitchen", matches="Bread, Milk"
    )


async def test_add_name_differing_only_in_non_ascii_case_is_rejected(stack: TodoStack) -> None:
    await stack.call("add_item", inventory_id="kitchen", name="Čokolada")

    with pytest.raises(ServiceValidationError) as err:
        await stack.call("add_item", inventory_id="kitchen", name="čokolada")

    assert_translated_error(err.value, "duplicate_item_name", name="Čokolada", inventory="Kitchen")
    names = [i["name"] for i in await stack.coordinators["kitchen"].async_list_items("kitchen")]
    assert names.count("Čokolada") == 1 and "čokolada" not in names


async def test_rename_onto_name_differing_only_in_non_ascii_case_is_rejected(
    stack: TodoStack,
) -> None:
    await stack.call("add_item", inventory_id="kitchen", name="Čokolada")

    with pytest.raises(ServiceValidationError) as err:
        await stack.call("update_item", inventory_id="kitchen", old_name="Bread", name="čokolada")

    assert_translated_error(err.value, "duplicate_item_name", name="Čokolada", inventory="Kitchen")
    assert await stack.item("kitchen", "Bread") is not None


async def test_recasing_own_non_ascii_name_is_allowed(stack: TodoStack) -> None:
    await stack.call("add_item", inventory_id="kitchen", name="Čokolada")

    await stack.call("update_item", inventory_id="kitchen", old_name="Čokolada", name="čokolada")

    names = [i["name"] for i in await stack.coordinators["kitchen"].async_list_items("kitchen")]
    assert "čokolada" in names and "Čokolada" not in names


@pytest.mark.parametrize(
    ("strategy", "added", "updated", "skipped"),
    [("skip", 0, 0, 1), ("merge_quantities", 0, 1, 0), ("overwrite", 0, 1, 0)],
)
async def test_import_matches_name_differing_only_in_non_ascii_case(
    stack: TodoStack, strategy: str, added: int, updated: int, skipped: int
) -> None:
    """Import finds the existing item as resolution would, exactly like an ASCII-case match."""
    await stack.call("add_item", inventory_id="kitchen", name="Čokolada", quantity=1, unit="g")
    coordinator = stack.coordinators["kitchen"]

    result = await coordinator.async_import_inventory(
        "kitchen", {"items": [{"name": "čokolada", "quantity": 2, "unit": "bar"}]}, "json", strategy
    )

    assert (result["added"], result["updated"], result["skipped"]) == (added, updated, skipped)
    assert result["errors"] == []
    items = {i["name"]: i for i in await coordinator.async_list_items("kitchen")}
    assert "čokolada" not in items
    expected = {"skip": (1.0, "g"), "merge_quantities": (3.0, "g"), "overwrite": (2.0, "bar")}
    assert (items["Čokolada"]["quantity"], items["Čokolada"]["unit"]) == expected[strategy]


async def test_non_ascii_name_matching_another_items_alias_is_rejected(stack: TodoStack) -> None:
    await stack.call("add_item", inventory_id="kitchen", name="Chocolate", aliases="Čokolada")

    with pytest.raises(ServiceValidationError) as err:
        await stack.call("add_item", inventory_id="kitchen", name="čokolada")
    assert_translated_error(
        err.value, "name_is_alias", name="čokolada", item="Chocolate", inventory="Kitchen"
    )
    with pytest.raises(ServiceValidationError) as err:
        await stack.call("update_item", inventory_id="kitchen", old_name="Bread", name="čokolada")
    assert_translated_error(
        err.value, "name_is_alias", name="čokolada", item="Chocolate", inventory="Kitchen"
    )


async def test_non_ascii_alias_matching_another_items_name_or_alias_is_rejected(
    stack: TodoStack,
) -> None:
    await stack.call("add_item", inventory_id="kitchen", name="Čaj", aliases="Šipek")

    with pytest.raises(ServiceValidationError) as err:
        await stack.call("add_item", inventory_id="kitchen", name="Tea", aliases="čaj")
    assert_translated_error(err.value, "alias_is_item_name", aliases="čaj", inventory="Kitchen")
    with pytest.raises(ServiceValidationError) as err:
        await stack.call(
            "update_item", inventory_id="kitchen", old_name="Bread", name="Bread", aliases="ŠIPEK"
        )
    assert_translated_error(err.value, "alias_conflict", aliases="ŠIPEK")


@pytest.mark.parametrize(
    ("strategy", "added", "updated", "skipped", "quantity"),
    [("skip", 1, 0, 1, 1.0), ("merge_quantities", 1, 1, 0, 3.0), ("overwrite", 1, 1, 0, 2.0)],
)
async def test_import_record_matches_earlier_record_of_same_import(
    stack: TodoStack, strategy: str, added: int, updated: int, skipped: int, quantity: float
) -> None:
    coordinator = stack.coordinators["kitchen"]
    data = {"items": [{"name": "Čokolada", "quantity": 1}, {"name": "čokolada", "quantity": 2}]}

    result = await coordinator.async_import_inventory("kitchen", data, "json", strategy)

    assert (result["added"], result["updated"], result["skipped"]) == (added, updated, skipped)
    assert result["errors"] == []
    items = {i["name"]: i for i in await coordinator.async_list_items("kitchen")}
    assert "čokolada" not in items
    assert items["Čokolada"]["quantity"] == quantity


async def test_import_alias_clashing_with_earlier_record_of_same_import(stack: TodoStack) -> None:
    coordinator = stack.coordinators["kitchen"]
    data = {"items": [{"name": "Tea", "aliases": ["Čaj"]}, {"name": "čaj"}]}

    result = await coordinator.async_import_inventory("kitchen", data, "json")

    assert result["added"] == 1
    assert len(result["errors"]) == 1
    assert result["errors"][0].startswith("Item 2 ('čaj')")


async def test_import_reads_item_identifiers_once(stack: TodoStack) -> None:
    coordinator = stack.coordinators["kitchen"]
    data = {
        "items": [
            {"name": "Rice", "aliases": ["basmati"]},
            {"name": "Pasta"},
            {"name": "milk", "aliases": ["whole milk"]},
            {"name": "Čaj"},
        ]
    }

    with patch.object(
        stack.repo, "list_item_identifiers", wraps=stack.repo.list_item_identifiers
    ) as spy:
        result = await coordinator.async_import_inventory("kitchen", data, "json", "overwrite")

    assert (result["added"], result["updated"], result["errors"]) == (3, 1, [])
    assert spy.await_count == 1


# --- one case-folding rule (str.casefold) for names, aliases, search and todo -------


async def test_casefold_equal_name_resolves(stack: TodoStack) -> None:
    await stack.call("add_item", inventory_id="kitchen", name="Straße", quantity=1)

    await stack.call("increment_item", inventory_id="kitchen", name="strasse", amount=1)
    item = await stack.coordinators["kitchen"].async_get_item("kitchen", "STRASSE")

    assert item is not None
    assert (item["name"], item["quantity"]) == ("Straße", 2.0)


async def test_casefold_equal_name_is_a_duplicate(stack: TodoStack) -> None:
    await stack.call("add_item", inventory_id="kitchen", name="Straße")

    with pytest.raises(ServiceValidationError) as err:
        await stack.call("add_item", inventory_id="kitchen", name="STRASSE")

    assert_translated_error(err.value, "duplicate_item_name", name="Straße", inventory="Kitchen")


async def test_casefold_equal_alias_clashes(stack: TodoStack) -> None:
    await stack.call("add_item", inventory_id="kitchen", name="Street", aliases="Straße")

    with pytest.raises(ServiceValidationError) as err:
        await stack.call("add_item", inventory_id="kitchen", name="Road", aliases="strasse")

    assert_translated_error(err.value, "alias_conflict", aliases="strasse")


@pytest.mark.parametrize("query", ["strasse", "STRASSE", "Straße", "STRAẞE"])
async def test_search_and_services_agree(stack: TodoStack, query: str) -> None:
    await stack.call("add_item", inventory_id="kitchen", name="Straße", quantity=1)
    item = await stack.item("kitchen", "Straße")
    assert item is not None

    found = await stack.repo.search_items(query, ["kitchen"], 50)
    # remove_item accepts only an exact (case-insensitive) name: no fuzzy fallback.
    await stack.call("remove_item", inventory_id="kitchen", name=query)

    assert found == [("kitchen", item["id"], 0)]
    assert await stack.item("kitchen", "Straße") is None


async def test_todo_entry_with_casefold_equal_summary_is_refreshed(stack: TodoStack) -> None:
    stack.todo.seed("todo.grocery", "STRASSE (x9)")
    await stack.call(
        "add_item",
        inventory_id="kitchen",
        name="Straße",
        quantity=1,
        auto_add_enabled=True,
        auto_add_to_list_quantity=2,
        todo_list="todo.grocery",
    )

    assert stack.todo.summaries("todo.grocery") == ["Straße (x2)"]
