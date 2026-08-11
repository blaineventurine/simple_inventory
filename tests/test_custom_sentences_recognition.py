"""End-to-end recognition tests for the bundled example sentence file."""

from __future__ import annotations

from pathlib import Path

import pytest
from hassil.intents import Intents
from hassil.recognize import RecognizeResult, recognize_best

_YAML_PATH = (
    Path(__file__).parent.parent
    / "custom_components"
    / "simple_inventory"
    / "data"
    / "custom_sentences"
    / "en"
    / "simple_inventory.yaml"
)


@pytest.fixture(scope="module")
def intents_obj() -> Intents:
    with _YAML_PATH.open(encoding="utf-8") as yaml_file:
        return Intents.from_yaml(yaml_file)


def _recognize(intents_obj: Intents, text: str) -> RecognizeResult | None:
    return recognize_best(
        text,
        intents_obj,
        best_metadata_key="hass_custom_sentence",
        best_slot_name="name",
    )


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
