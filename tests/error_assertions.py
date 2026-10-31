"""Shared assertion for translation-keyed (structured) service errors."""

from __future__ import annotations

from homeassistant.exceptions import ServiceValidationError

from custom_components.simple_inventory.const import DOMAIN


def assert_translated_error(err: BaseException, key: str, **placeholders: str) -> None:
    """Assert ``err`` is a ServiceValidationError carrying ``key`` and exactly ``placeholders``."""
    assert isinstance(err, ServiceValidationError), repr(err)
    assert err.translation_domain == DOMAIN
    assert err.translation_key == key
    assert (err.translation_placeholders or {}) == placeholders
