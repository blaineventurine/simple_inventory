"""Spoken sentences: language choice, plural forms, numbers and lists per language."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.simple_inventory.const import DOMAIN
from custom_components.simple_inventory.speech import (
    Speech,
    plural_category,
    speech_language,
)

Loader = Callable[[str], Awaitable[Speech]]


@pytest.fixture
async def load(
    hass: HomeAssistant, enable_custom_integrations: None
) -> Callable[[str], Awaitable[Speech]]:
    async def _load(language: str) -> Speech:
        return await Speech.async_load(hass, language)

    return _load


@pytest.mark.parametrize(
    ("requested", "expected"),
    [("en", "en"), ("sl", "sl"), ("fr-CA", "fr"), ("es-MX", "es"), ("de", "en"), ("", "en")],
)
def test_speech_language_picks_closest_supported(requested: str, expected: str) -> None:
    assert speech_language(requested) == expected


@pytest.mark.parametrize(
    ("language", "counts"),
    [
        ("en", {0: "other", 1: "one", 2: "other", 21: "other"}),
        ("es", {0: "other", 1: "one", 2: "other"}),
        ("fr", {0: "one", 1: "one", 2: "other"}),
        (
            "sl",
            {
                0: "other",
                1: "one",
                2: "two",
                3: "few",
                4: "few",
                5: "other",
                101: "one",
                102: "two",
                104: "few",
                111: "other",
            },
        ),
    ],
)
def test_plural_category(language: str, counts: dict[int, str]) -> None:
    assert {count: plural_category(language, count) for count in counts} == counts


async def test_slovenian_counts_use_all_four_forms(load: Loader) -> None:
    speech = await load("sl")
    assert [speech.count("speech_count_low_stock", n) for n in (1, 2, 3, 5)] == [
        "1 artikel ima nizko zalogo",
        "2 artikla imata nizko zalogo",
        "3 artikli imajo nizko zalogo",
        "5 artiklov ima nizko zalogo",
    ]


async def test_count_falls_back_to_other_when_a_language_has_no_form(load: Loader) -> None:
    english, french = await load("en"), await load("fr")
    assert english.count("speech_more", 1) == "1 more"
    assert french.count("speech_more", 1) == "1 autre"
    assert french.count("speech_more", 3) == "3 autres"


async def test_amounts_drop_float_drift_and_use_the_decimal_comma(load: Loader) -> None:
    english, slovenian = await load("en"), await load("sl")
    assert [english.amount(v) for v in (0.7000000000000001, 2.0, 2.5, -0.0)] == [
        "0.7",
        "2",
        "2.5",
        "0",
    ]
    assert slovenian.amount(1.5) == "1,5"
    assert slovenian.amount(3.0) == "3"


async def test_lists_join_in_each_language(load: Loader) -> None:
    english, spanish = await load("en"), await load("es")
    assert english.and_list(["A"]) == "A"
    assert english.and_list(["A", "B"]) == "A and B"
    assert english.and_list(["A", "B", "C"]) == "A, B, and C"
    assert english.or_list(["A", "B", "C"]) == "A, B or C"
    assert spanish.and_list(["A", "B", "C"]) == "A, B y C"
    assert spanish.or_list(["A", "B"]) == "A o B"


async def test_errors_render_in_the_speech_language(load: Loader) -> None:
    spanish = await load("es")
    err = ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="item_not_found",
        translation_placeholders={"name": "leche", "inventory": "Cocina"},
    )
    assert spanish.error(err) == (
        'No se encontró ningún artículo llamado "leche" en el inventario "Cocina"'
    )
    assert spanish.error(HomeAssistantError("plain failure")) == "plain failure"
