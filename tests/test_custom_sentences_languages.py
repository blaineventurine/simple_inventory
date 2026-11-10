"""The bundled es/fr/sl example sentences route to the right intent with clean slots."""

from __future__ import annotations

from functools import cache
from pathlib import Path

import pytest
from hassil.intents import Intents
from hassil.recognize import recognize_best
from hassil.util import merge_dict
from homeassistant.util.yaml import parse_yaml

from custom_components.simple_inventory.voice_sentences import names_yaml

_SENTENCES = (
    Path(__file__).parents[1] / "custom_components" / "simple_inventory" / "data"
) / "custom_sentences"

# Stored inventory names per language, as the generated names file would list them.
_INVENTORIES = {
    "en": ["kitchen"],
    "es": ["cocina", "congelador", "despensa", "garaje"],
    "fr": ["cuisine", "frigo", "garage"],
    "sl": ["kuhinja", "shramba", "garaža", "hladilnik"],
}


@cache
def _intents(language: str) -> Intents:
    merged: dict = {}
    template = (_SENTENCES / language / "simple_inventory.yaml").read_text(encoding="utf-8")
    for document in (template, names_yaml(language, _INVENTORIES[language])):
        parsed = parse_yaml(document)
        assert isinstance(parsed, dict)
        merge_dict(merged, parsed)
    return Intents.from_dict(merged)


_CASES: list[tuple[str, str, str, dict[str, object]]] = [
    # Spanish
    (
        "es",
        "quita 2 leche de la cocina",
        "SimpleInventoryRemoveItem",
        {"quantity": 2, "item": "leche", "inventory": "cocina"},
    ),
    (
        "es",
        "saca huevos del congelador",
        "SimpleInventoryRemoveItem",
        {"item": "huevos", "inventory": "congelador"},
    ),
    (
        "es",
        "añade 3 arroz a la despensa",
        "SimpleInventoryAddItem",
        {"quantity": 3, "item": "arroz", "inventory": "despensa"},
    ),
    (
        "es",
        "cuántas pilas hay en el garaje",
        "SimpleInventoryQueryItem",
        {"item": "pilas", "inventory": "garaje"},
    ),
    ("es", "cuántas pilas tenemos", "SimpleInventoryFindItem", {"item": "pilas"}),
    ("es", "dónde están las pilas", "SimpleInventoryFindItem", {"item": "pilas"}),
    ("es", "tenemos mantequilla", "SimpleInventoryFindItem", {"item": "mantequilla"}),
    (
        "es",
        "cuántos artículos están caducados",
        "SimpleInventoryExpiryCountQuery",
        {"status": "expired"},
    ),
    (
        "es",
        "cuántos productos por caducar hay en la despensa",
        "SimpleInventoryExpiryCountQuery",
        {"status": "expiring_soon", "inventory": "despensa"},
    ),
    ("es", "cuántos artículos tienen poco stock", "SimpleInventoryLowStockCountQuery", {}),
    ("es", "qué se está acabando", "SimpleInventoryLowStockListQuery", {}),
    (
        "es",
        "qué se nos está acabando en la cocina",
        "SimpleInventoryLowStockListQuery",
        {"inventory": "cocina"},
    ),
    (
        "es",
        "qué artículos están a punto de caducar",
        "SimpleInventoryExpiryListQuery",
        {"status": "expiring_soon"},
    ),
    (
        "es",
        "pon leche a 4 en la cocina",
        "SimpleInventorySetItemQuantity",
        {"item": "leche", "quantity": 4, "inventory": "cocina"},
    ),
    (
        "es",
        "mueve 2 leche de la nevera al garaje en la cocina",
        "SimpleInventoryTransferItem",
        {
            "quantity": 2,
            "item": "leche",
            "from_location": "nevera",
            "to_location": "garaje",
            "inventory": "cocina",
        },
    ),
    # French
    (
        "fr",
        "retire 2 lait du frigo",
        "SimpleInventoryRemoveItem",
        {"quantity": 2, "item": "lait", "inventory": "frigo"},
    ),
    (
        "fr",
        "ajoute riz à la cuisine",
        "SimpleInventoryAddItem",
        {"item": "riz", "inventory": "cuisine"},
    ),
    (
        "fr",
        "combien de piles il y a dans le garage",
        "SimpleInventoryQueryItem",
        {"item": "piles", "inventory": "garage"},
    ),
    ("fr", "combien de piles avons-nous", "SimpleInventoryFindItem", {"item": "piles"}),
    ("fr", "où sont les piles", "SimpleInventoryFindItem", {"item": "piles"}),
    ("fr", "est-ce qu'on a du beurre", "SimpleInventoryFindItem", {"item": "beurre"}),
    (
        "fr",
        "combien d'articles sont périmés",
        "SimpleInventoryExpiryCountQuery",
        {"status": "expired"},
    ),
    (
        "fr",
        "combien d'articles sont presque épuisés dans la cuisine",
        "SimpleInventoryLowStockCountQuery",
        {"inventory": "cuisine"},
    ),
    ("fr", "qu'est-ce qui commence à manquer", "SimpleInventoryLowStockListQuery", {}),
    (
        "fr",
        "quels articles sont bientôt périmés",
        "SimpleInventoryExpiryListQuery",
        {"status": "expiring_soon"},
    ),
    (
        "fr",
        "mets lait à 3 dans la cuisine",
        "SimpleInventorySetItemQuantity",
        {"item": "lait", "quantity": 3, "inventory": "cuisine"},
    ),
    (
        "fr",
        "déplace lait du frigo vers le garage dans la cuisine",
        "SimpleInventoryTransferItem",
        {"item": "lait", "from_location": "frigo", "to_location": "garage", "inventory": "cuisine"},
    ),
    # Slovenian
    (
        "sl",
        "odstrani 2 mleko iz inventarja kuhinja",
        "SimpleInventoryRemoveItem",
        {"quantity": 2, "item": "mleko", "inventory": "kuhinja"},
    ),
    (
        "sl",
        "dodaj riž v shrambo",
        "SimpleInventoryAddItem",
        {"item": "riž", "inventory": "shramba"},
    ),
    (
        "sl",
        "koliko baterij imamo v garaži",
        "SimpleInventoryQueryItem",
        {"item": "baterij", "inventory": "garaža"},
    ),
    (
        "sl",
        "koliko baterij imamo v hladilniku",
        "SimpleInventoryQueryItem",
        {"item": "baterij", "inventory": "hladilnik"},
    ),
    ("sl", "koliko baterij imamo", "SimpleInventoryFindItem", {"item": "baterij"}),
    ("sl", "kje so baterije", "SimpleInventoryFindItem", {"item": "baterije"}),
    ("sl", "koliko artiklov je poteklo", "SimpleInventoryExpiryCountQuery", {"status": "expired"}),
    (
        "sl",
        "koliko artiklov bo kmalu poteklo v shrambi",
        "SimpleInventoryExpiryCountQuery",
        {"status": "expiring_soon", "inventory": "shramba"},
    ),
    ("sl", "koliko artiklov ima nizko zalogo", "SimpleInventoryLowStockCountQuery", {}),
    ("sl", "kaj nam zmanjkuje", "SimpleInventoryLowStockListQuery", {}),
    ("sl", "kateri artikli so potekli", "SimpleInventoryExpiryListQuery", {"status": "expired"}),
    (
        "sl",
        "nastavi mleko na 3 v kuhinji",
        "SimpleInventorySetItemQuantity",
        {"item": "mleko", "quantity": 3, "inventory": "kuhinja"},
    ),
    (
        "sl",
        "premakni mleko iz hladilnika v klet v kuhinji",
        "SimpleInventoryTransferItem",
        {
            "item": "mleko",
            "from_location": "hladilnika",
            "to_location": "klet",
            "inventory": "kuhinja",
        },
    ),
]


@pytest.mark.parametrize(("language", "utterance", "intent_name", "slots"), _CASES)
def test_sentence_routes_to_intent(
    language: str, utterance: str, intent_name: str, slots: dict[str, object]
) -> None:
    result = recognize_best(
        utterance,
        _intents(language),
        best_metadata_key="hass_custom_sentence",
        best_slot_name="name",
    )
    assert result is not None, f"no match for {utterance!r}"
    assert result.intent.name == intent_name
    assert {name: entity.value for name, entity in result.entities.items()} == slots


@pytest.mark.parametrize("language", ["es", "fr", "sl"])
def test_every_intent_has_sentences(language: str) -> None:
    english = set(_intents("en").intents)
    assert set(_intents(language).intents) == english
