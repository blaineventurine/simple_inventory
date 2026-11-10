"""Translation strings must render the same in HA's frontend (ICU) and in Python."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

TRANSLATIONS = Path(__file__).parents[1] / "custom_components" / "simple_inventory" / "translations"
LOCALES = ("en", "es", "fr", "sl", "en-GB")

# HA's frontend formats translations as ICU MessageFormat: an apostrophe right before a
# brace starts a quoted literal (so "'{name}'" shows the raw "{name}") and "''" becomes
# one apostrophe. Python's str.format treats both literally. Quote placeholders with
# escaped double quotes instead, like HA core: "\"{name}\"".
_ICU_UNSAFE = re.compile(r"'[{}]|\}'|''")


def _strings(node: Any, path: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(value, f"{path}.{key}" if path else key)
    elif isinstance(node, str):
        yield path, node


@pytest.mark.parametrize("locale", LOCALES)
def test_no_icu_unsafe_apostrophes(locale: str) -> None:
    data = json.loads((TRANSLATIONS / f"{locale}.json").read_text(encoding="utf-8"))
    offending = [f"{path}: {text}" for path, text in _strings(data) if _ICU_UNSAFE.search(text)]
    assert offending == []
