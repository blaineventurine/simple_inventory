"""End-to-end recognition tests for the bundled example sentence file."""

from __future__ import annotations

from pathlib import Path

import pytest
from hassil.intents import Intents
from hassil.recognize import RecognizeResult, recognize_best
from hassil.util import merge_dict
from homeassistant.util.yaml import parse_yaml

from custom_components.simple_inventory.voice_sentences import names_yaml

_YAML_PATH = (
    Path(__file__).parent.parent
    / "custom_components"
    / "simple_inventory"
    / "data"
    / "custom_sentences"
    / "en"
    / "simple_inventory.yaml"
)

# The inventories these tests talk to, as the generated names file would list them.
_INVENTORIES = ["kitchen", "freezer", "dry goods", "disposable goods", "pantry", "garage"]


def _load(*documents: str) -> Intents:
    """Merge sentence files the way Home Assistant does (dicts merged, lists concatenated)."""
    merged: dict = {}
    for document in documents:
        parsed = parse_yaml(document)
        assert isinstance(parsed, dict)
        merge_dict(merged, parsed)
    return Intents.from_dict(merged)


@pytest.fixture(scope="module")
def intents_obj() -> Intents:
    return _load(_YAML_PATH.read_text(encoding="utf-8"), names_yaml("en", _INVENTORIES))


def _recognize(intents_obj: Intents, text: str) -> RecognizeResult | None:
    return recognize_best(
        text,
        intents_obj,
        best_metadata_key="hass_custom_sentence",
        best_slot_name="name",
    )


@pytest.mark.parametrize(
    "utterance",
    [
        "add drill to my bring list",
        "add milk to the shopping list",
        "remove eggs from my shopping list",
        "add 5 minutes to my timer",
        "set the living room fan to 50 percent",
        "how many people are in the kitchen zone",
    ],
)
def test_sentences_naming_no_inventory_are_left_to_home_assistant(
    intents_obj: Intents, utterance: str
) -> None:
    """Custom sentences win over HA's built-in ones, so they must not claim these."""
    assert _recognize(intents_obj, utterance) is None


def test_names_file_merges_in_either_order() -> None:
    """HA reads custom sentence files in directory order, which is unspecified."""
    template = _YAML_PATH.read_text(encoding="utf-8")
    names = names_yaml("en", ["freezer"])
    for intents in (_load(template, names), _load(names, template)):
        result = _recognize(intents, "add 2 peas to the freezer")
        assert result is not None
        assert result.entities["inventory"].value == "freezer"


def test_without_a_names_file_no_inventory_sentence_matches() -> None:
    """A template left behind (integration removed) matches nothing instead of erroring."""
    intents = _load(_YAML_PATH.read_text(encoding="utf-8"))
    assert _recognize(intents, "add 2 peas to the freezer") is None
    assert _recognize(intents, "do we have peas") is not None


@pytest.mark.parametrize(
    "utterance,expected_status,expected_inventory",
    [
        ("how many expired items in dry goods inventory", "expired", "dry goods"),
        (
            "how many expired items are there in dry goods inventory",
            "expired",
            "dry goods",
        ),
        ("how many items are expired in dry goods inventory", "expired", "dry goods"),
        (
            "how many items are expiring soon in dry goods",
            "expiring_soon",
            "dry goods",
        ),
        (
            "how many items are about to expire in the freezer",
            "expiring_soon",
            "freezer",
        ),
    ],
)
def test_expiry_phrases_route_to_expiry_count_query(
    intents_obj: Intents, utterance: str, expected_status: str, expected_inventory: str
) -> None:
    result = _recognize(intents_obj, utterance)
    assert result is not None, f"no match for {utterance!r}"
    assert result.intent.name == "SimpleInventoryExpiryCountQuery"
    assert result.entities["status"].value == expected_status
    assert result.entities["inventory"].value == expected_inventory


@pytest.mark.parametrize(
    "utterance,expected_status",
    [
        ("how many expired items", "expired"),
        ("how many items are expiring soon", "expiring_soon"),
    ],
)
def test_unscoped_expiry_phrases_route_to_expiry_count_query(
    intents_obj: Intents, utterance: str, expected_status: str
) -> None:
    result = _recognize(intents_obj, utterance)
    assert result is not None, f"no match for {utterance!r}"
    assert result.intent.name == "SimpleInventoryExpiryCountQuery"
    assert result.entities["status"].value == expected_status
    assert "inventory" not in result.entities


def test_genuine_item_quantity_query_still_routes_to_query_item(
    intents_obj: Intents,
) -> None:
    """Regression guard: the fix must not break real item-quantity lookups."""
    result = _recognize(intents_obj, "how many aluminum foil are there in freezer")
    assert result is not None
    assert result.intent.name == "SimpleInventoryQueryItem"
    assert result.entities["item"].value == "aluminum foil"
    assert result.entities["inventory"].value == "freezer"


@pytest.mark.parametrize(
    ("utterance", "item", "inventory"),
    [
        ("how many apples are in dry goods", "apples", "dry goods"),
        ("how many apples are in the dry goods inventory", "apples", "dry goods"),
        ("how many apples are there in dry goods", "apples", "dry goods"),
        ("how many apples do we have in the dry goods", "apples", "dry goods"),
        ("how many apples in dry goods", "apples", "dry goods"),
        ("are we out of apples in dry goods", "apples", "dry goods"),
    ],
)
def test_item_quantity_query_phrasings_capture_only_the_item(
    intents_obj: Intents, utterance: str, item: str, inventory: str
) -> None:
    result = _recognize(intents_obj, utterance)
    assert result is not None
    assert result.intent.name == "SimpleInventoryQueryItem"
    assert {name: entity.value for name, entity in result.entities.items()} == {
        "item": item,
        "inventory": inventory,
    }


def test_remove_item_sentence_still_recognized(intents_obj: Intents) -> None:
    """Regression guard against the fix accidentally affecting unrelated intents."""
    result = _recognize(intents_obj, "remove 2 aluminum foil from disposable goods")
    assert result is not None
    assert result.intent.name == "SimpleInventoryRemoveItem"


@pytest.mark.parametrize(
    "utterance,expected_inventory",
    [
        ("how many items are low on stock in the pantry", "pantry"),
        ("how many items are running low in the freezer", "freezer"),
    ],
)
def test_low_stock_phrases_route_to_low_stock_count_query(
    intents_obj: Intents, utterance: str, expected_inventory: str
) -> None:
    result = _recognize(intents_obj, utterance)
    assert result is not None, f"no match for {utterance!r}"
    assert result.intent.name == "SimpleInventoryLowStockCountQuery"
    assert result.entities["inventory"].value == expected_inventory


def test_unscoped_low_stock_phrase_routes_to_low_stock_count_query(
    intents_obj: Intents,
) -> None:
    result = _recognize(intents_obj, "how many items are running low")
    assert result is not None
    assert result.intent.name == "SimpleInventoryLowStockCountQuery"
    assert "inventory" not in result.entities


@pytest.mark.parametrize(
    "utterance,expected_status,expected_inventory",
    [
        ("which items are expired in dry goods inventory", "expired", "dry goods"),
        ("what items are expiring soon in the freezer", "expiring_soon", "freezer"),
        ("list the expired items in dry goods", "expired", "dry goods"),
    ],
)
def test_expiry_list_phrases_route_to_expiry_list_query(
    intents_obj: Intents, utterance: str, expected_status: str, expected_inventory: str
) -> None:
    result = _recognize(intents_obj, utterance)
    assert result is not None, f"no match for {utterance!r}"
    assert result.intent.name == "SimpleInventoryExpiryListQuery"
    assert result.entities["status"].value == expected_status
    assert result.entities["inventory"].value == expected_inventory


def test_set_item_quantity_phrase_routes_correctly(intents_obj: Intents) -> None:
    result = _recognize(intents_obj, "set aluminum foil to 5 in the freezer")
    assert result is not None
    assert result.intent.name == "SimpleInventorySetItemQuantity"
    assert result.entities["item"].value == "aluminum foil"
    assert result.entities["quantity"].value == 5.0
    assert result.entities["inventory"].value == "freezer"


def test_set_item_quantity_without_inventory_does_not_match(intents_obj: Intents) -> None:
    result = _recognize(intents_obj, "set aluminum foil to 5")
    assert result is None


@pytest.mark.parametrize(
    ("utterance", "expected"),
    [
        (
            "move 2 milk from the fridge to the garage fridge in the kitchen",
            {
                "quantity": 2.0,
                "item": "milk",
                "from_location": "fridge",
                "to_location": "garage fridge",
                "inventory": "kitchen",
            },
        ),
        (
            "move aluminum foil from the top shelf to the bottom shelf in disposable goods inventory",
            {
                "item": "aluminum foil",
                "from_location": "top shelf",
                "to_location": "bottom shelf",
                "inventory": "disposable goods",
            },
        ),
    ],
)
def test_move_phrases_route_to_transfer_item(
    intents_obj: Intents, utterance: str, expected: dict[str, object]
) -> None:
    result = _recognize(intents_obj, utterance)
    assert result is not None
    assert result.intent.name == "SimpleInventoryTransferItem"
    assert {name: entity.value for name, entity in result.entities.items()} == expected


def test_move_without_inventory_does_not_match(intents_obj: Intents) -> None:
    assert _recognize(intents_obj, "move 2 milk from the fridge to the garage") is None


@pytest.mark.parametrize(
    ("utterance", "intent_name", "expected"),
    [
        (
            "remove 2 milk from the fridge in the kitchen",
            "SimpleInventoryRemoveItem",
            {"quantity": 2, "item": "milk", "location": "fridge", "inventory": "kitchen"},
        ),
        (
            "remove aluminum foil from top shelf in disposable goods inventory",
            "SimpleInventoryRemoveItem",
            {"item": "aluminum foil", "location": "top shelf", "inventory": "disposable goods"},
        ),
        (
            "take 3 eggs out of the garage fridge in the kitchen",
            "SimpleInventoryRemoveItem",
            {"quantity": 3, "item": "eggs", "location": "garage fridge", "inventory": "kitchen"},
        ),
        (
            "we used up 2 milk from the fridge in the kitchen",
            "SimpleInventoryRemoveItem",
            {"quantity": 2, "item": "milk", "location": "fridge", "inventory": "kitchen"},
        ),
        (
            "add 2 milk to the fridge in the kitchen",
            "SimpleInventoryAddItem",
            {"quantity": 2, "item": "milk", "location": "fridge", "inventory": "kitchen"},
        ),
        (
            "add aluminum foil to the top shelf in the disposable goods inventory",
            "SimpleInventoryAddItem",
            {"item": "aluminum foil", "location": "top shelf", "inventory": "disposable goods"},
        ),
    ],
)
def test_location_phrases_fill_the_location_slot(
    intents_obj: Intents, utterance: str, intent_name: str, expected: dict[str, object]
) -> None:
    """With only real inventory names in the inventory slot, "<location> in [the]
    <inventory>" needs its own sentences; the add/remove handlers take a `location` slot."""
    result = _recognize(intents_obj, utterance)
    assert result is not None
    assert result.intent.name == intent_name
    assert {name: entity.value for name, entity in result.entities.items()} == expected


@pytest.mark.parametrize(
    ("utterance", "intent_name", "expected"),
    [
        (
            "remove 2 milk from kitchen",
            "SimpleInventoryRemoveItem",
            {"quantity": 2, "item": "milk", "inventory": "kitchen"},
        ),
        (
            "remove aluminum foil from the disposable goods inventory",
            "SimpleInventoryRemoveItem",
            {"item": "aluminum foil", "inventory": "disposable goods"},
        ),
        (
            "take 3 eggs out of the kitchen",
            "SimpleInventoryRemoveItem",
            {"quantity": 3, "item": "eggs", "inventory": "kitchen"},
        ),
        (
            "we used up 2 milk from the kitchen",
            "SimpleInventoryRemoveItem",
            {"quantity": 2, "item": "milk", "inventory": "kitchen"},
        ),
        (
            "add 2 milk to kitchen",
            "SimpleInventoryAddItem",
            {"quantity": 2, "item": "milk", "inventory": "kitchen"},
        ),
        (
            "add aluminum foil to the disposable goods inventory",
            "SimpleInventoryAddItem",
            {"item": "aluminum foil", "inventory": "disposable goods"},
        ),
        (
            "restock 4 eggs in the kitchen",
            "SimpleInventoryAddItem",
            {"quantity": 4, "item": "eggs", "inventory": "kitchen"},
        ),
    ],
)
def test_add_remove_without_location_parse_as_before(
    intents_obj: Intents, utterance: str, intent_name: str, expected: dict[str, object]
) -> None:
    result = _recognize(intents_obj, utterance)
    assert result is not None
    assert result.intent.name == intent_name
    assert {name: entity.value for name, entity in result.entities.items()} == expected


@pytest.mark.parametrize(
    ("utterance", "item"),
    [
        ("how many batteries do we have", "batteries"),
        ("how much butter do we have", "butter"),
        ("do we have any butter", "butter"),
        ("do we have coffee", "coffee"),
        ("where are the batteries", "batteries"),
        ("where is the flour", "flour"),
        ("where can I find the duct tape", "duct tape"),
    ],
)
def test_unscoped_item_questions_route_to_find_item(
    intents_obj: Intents, utterance: str, item: str
) -> None:
    result = _recognize(intents_obj, utterance)
    assert result is not None, f"no match for {utterance!r}"
    assert result.intent.name == "SimpleInventoryFindItem"
    assert {name: entity.value for name, entity in result.entities.items()} == {"item": item}


@pytest.mark.parametrize(
    ("utterance", "intent_name"),
    [
        ("how many items are expired", "SimpleInventoryExpiryCountQuery"),
        ("how many items are low on stock", "SimpleInventoryLowStockCountQuery"),
        ("how many apples do we have in the dry goods", "SimpleInventoryQueryItem"),
    ],
)
def test_find_item_does_not_capture_other_questions(
    intents_obj: Intents, utterance: str, intent_name: str
) -> None:
    result = _recognize(intents_obj, utterance)
    assert result is not None
    assert result.intent.name == intent_name


@pytest.mark.parametrize(
    ("utterance", "inventory"),
    [
        ("what's running low", None),
        ("what is running low in the pantry", "pantry"),
        ("what are we low on", None),
        ("what are we running low on in the freezer", "freezer"),
        ("which items are low on stock", None),
        ("which items are running low in the pantry", "pantry"),
        ("list the low stock items", None),
        ("list low stock items in the freezer inventory", "freezer"),
    ],
)
def test_low_stock_list_phrases_route_to_low_stock_list_query(
    intents_obj: Intents, utterance: str, inventory: str | None
) -> None:
    result = _recognize(intents_obj, utterance)
    assert result is not None, f"no match for {utterance!r}"
    assert result.intent.name == "SimpleInventoryLowStockListQuery"
    expected = {} if inventory is None else {"inventory": inventory}
    assert {name: entity.value for name, entity in result.entities.items()} == expected


@pytest.mark.parametrize(
    ("utterance", "intent_name"),
    [
        ("how many items are running low", "SimpleInventoryLowStockCountQuery"),
        ("which items are expired", "SimpleInventoryExpiryListQuery"),
        ("list the expiring soon items", "SimpleInventoryExpiryListQuery"),
    ],
)
def test_low_stock_list_does_not_capture_other_questions(
    intents_obj: Intents, utterance: str, intent_name: str
) -> None:
    result = _recognize(intents_obj, utterance)
    assert result is not None
    assert result.intent.name == intent_name
