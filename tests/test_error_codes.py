"""Structured error codes: translation keys on raised errors, over WS, and in locales."""

from __future__ import annotations

import ast
import json
import re
import string
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import intent, translation
from pytest_homeassistant_custom_component.typing import (  # type: ignore[import-untyped]
    WebSocketGenerator,
)

from custom_components.simple_inventory.const import DOMAIN
from custom_components.simple_inventory.data import SimpleInventoryData
from custom_components.simple_inventory.intents import INTENT_QUERY_ITEM, QueryItemIntent
from custom_components.simple_inventory.services import ServiceHandler
from custom_components.simple_inventory.websocket_api import async_register_websocket_commands

PACKAGE_DIR = Path(__file__).parent.parent / "custom_components" / DOMAIN
TRANSLATIONS_DIR = PACKAGE_DIR / "translations"
LOCALES = ("en", "es", "fr", "sl")


def _exception_messages(locale: str) -> dict[str, str]:
    data = json.loads((TRANSLATIONS_DIR / f"{locale}.json").read_text(encoding="utf-8"))
    return {key: value["message"] for key, value in data.get("exceptions", {}).items()}


def _error_messages(locale: str) -> dict[str, str]:
    """Exception messages minus the intents' spoken sentences (``speech_*``)."""
    return {
        key: message
        for key, message in _exception_messages(locale).items()
        if not key.startswith("speech_")
    }


def _placeholders(message: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(message) if name}


def _raised_translation_keys() -> dict[str, set[str]]:
    """Map every literal translation_key passed to an *Error(...) call to its placeholders."""
    found: dict[str, set[str]] = {}
    for path in PACKAGE_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if not name.endswith("Error"):
                continue
            kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
            key = kwargs.get("translation_key")
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                continue
            placeholders = kwargs.get("translation_placeholders")
            names: set[str] = set()
            if isinstance(placeholders, ast.Dict):
                names = {str(k.value) for k in placeholders.keys if isinstance(k, ast.Constant)}
            found.setdefault(key.value, set()).update(names)
    return found


# ---------------------------------------------------------------------------
# Structural: every raised key exists in all 4 locales with matching placeholders
# ---------------------------------------------------------------------------


def test_source_raises_translated_errors() -> None:
    assert len(_raised_translation_keys()) >= 11


@pytest.mark.parametrize("locale", LOCALES)
def test_every_raised_translation_key_exists_in_locale(locale: str) -> None:
    messages = _exception_messages(locale)
    missing = sorted(set(_raised_translation_keys()) - set(messages))
    assert not missing, f"{locale}.json exceptions missing: {missing}"


@pytest.mark.parametrize("locale", LOCALES)
def test_locale_placeholders_match_raised_placeholders(locale: str) -> None:
    messages = _exception_messages(locale)
    for key, names in _raised_translation_keys().items():
        assert _placeholders(messages[key]) == names, f"{locale}:{key}"


def test_locales_have_identical_exception_keys() -> None:
    en = set(_exception_messages("en"))
    for locale in LOCALES[1:]:
        assert set(_exception_messages(locale)) == en, locale


@pytest.mark.parametrize("locale", LOCALES[1:])
def test_locale_speech_placeholders_match_english(locale: str) -> None:
    en = _exception_messages("en")
    for key, message in _exception_messages(locale).items():
        if key.startswith("speech_"):
            assert _placeholders(message) == _placeholders(en[key]), f"{locale}:{key}"


def test_no_unused_error_translations() -> None:
    assert set(_error_messages("en")) == set(_raised_translation_keys())


def test_exception_keys_are_snake_case() -> None:
    for key in _exception_messages("en"):
        assert re.fullmatch(r"[a-z][a-z0-9_]*", key), key


# ---------------------------------------------------------------------------
# Over the wire: HA's WS layer forwards translation_key for service calls
# ---------------------------------------------------------------------------


@pytest.fixture
async def loaded_translations(hass: HomeAssistant, enable_custom_integrations: None) -> None:
    """Cache the integration's translations and mark it set up, as HA does at setup.

    str(exc) renders English from the cache of *set-up* components only.
    """
    await translation.async_load_integrations(hass, {DOMAIN})
    hass.config.components.add(DOMAIN)


async def test_service_call_error_carries_translation_key_over_ws(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, loaded_translations: None
) -> None:
    handler = ServiceHandler(hass, MagicMock())
    hass.data[DOMAIN] = SimpleInventoryData()
    hass.services.async_register(DOMAIN, "increment_item", handler.async_increment_item)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {
            "type": "call_service",
            "domain": DOMAIN,
            "service": "increment_item",
            "service_data": {"inventory_id": "ghost", "name": "Milk"},
        }
    )
    msg: dict[str, Any] = await client.receive_json()

    assert msg["success"] is False
    assert msg["error"] == {
        "code": "service_validation_error",
        "message": 'Validation error: Inventory "ghost" is not currently loaded',
        "translation_key": "inventory_not_loaded",
        "translation_domain": DOMAIN,
        "translation_placeholders": {"inventory": "ghost"},
    }


async def test_ws_scan_barcode_error_carries_translation_key(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, loaded_translations: None
) -> None:
    handler = ServiceHandler(hass, MagicMock())
    hass.data[DOMAIN] = SimpleInventoryData(service_handler=handler)
    async_register_websocket_commands(hass)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {"type": f"{DOMAIN}/scan_barcode", "barcode": "123", "action": "lookup"}
    )
    msg: dict[str, Any] = await client.receive_json()

    assert msg["success"] is False
    assert msg["error"]["code"] == "scan_failed"
    assert msg["error"]["message"] == "No inventories configured"
    assert msg["error"]["translation_key"] == "no_inventories_configured"
    assert msg["error"]["translation_domain"] == DOMAIN


# ---------------------------------------------------------------------------
# Voice: translation-only errors still render readable speech
# ---------------------------------------------------------------------------


async def test_intent_speaks_rendered_message_for_translated_error(
    hass: HomeAssistant, loaded_translations: None
) -> None:
    entry = MagicMock()
    entry.entry_id = "inv_1"
    entry.data = {"name": "Disposable Goods", "entry_type": "inventory"}
    hass.data[DOMAIN] = SimpleInventoryData()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(hass.config_entries, "async_entries", lambda *_a, **_k: [entry])
        intent_obj = intent.Intent(
            hass,
            platform="test",
            intent_type=INTENT_QUERY_ITEM,
            slots={"item": {"value": "Foil"}, "inventory": {"value": "Disposable Goods"}},
            text_input="test input",
            context=Context(),
            language="en",
        )
        response = await QueryItemIntent().async_handle(intent_obj)

    assert response.response_type is intent.IntentResponseType.ERROR
    assert response.speech["plain"]["speech"] == (
        'Inventory "Disposable Goods" is not currently loaded'
    )
