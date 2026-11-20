"""Spoken answers for the voice/LLM intents, in the conversation's language.

The sentences live in the translation files under ``exceptions.speech_*.message`` (the
only place hassfest allows free-form strings). Placeholders use ``str.format`` syntax.
Counted sentences have one key per CLDR plural category (``_one``, ``_two``, ``_few``,
``_other``). Every locale lists the same keys (``scripts/check_translations.py``): a
language repeats ``_other`` for the categories it doesn't distinguish, and a category no
language needs for a sentence is absent everywhere, falling back to ``_other``.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import translation
from homeassistant.util import language as language_util

from .const import DOMAIN

_TRANSLATIONS = Path(__file__).parent / "translations"
FALLBACK_LANGUAGE = "en"


def _discover_languages() -> frozenset[str]:
    """Languages this package ships translations (and so speech) for."""
    return frozenset(path.stem for path in _TRANSLATIONS.glob("*.json"))


SPEECH_LANGUAGES = _discover_languages()

# Languages writing decimals with a comma ("1,5"); the rest use a point.
_DECIMAL_COMMA = frozenset({"es", "fr", "sl"})


def plural_category(language: str, count: int) -> str:
    """CLDR plural category of a whole number in one of the supported languages."""
    if language == "sl":
        return {1: "one", 2: "two", 3: "few", 4: "few"}.get(count % 100, "other")
    if language == "fr":
        return "one" if count in (0, 1) else "other"
    return "one" if count == 1 else "other"


def speech_language(requested: str) -> str:
    """The supported language closest to *requested* ('fr-CA' -> 'fr'), else English."""
    matches = language_util.matches(requested, SPEECH_LANGUAGES)
    return matches[0] if matches else FALLBACK_LANGUAGE


class Speech:
    """Renders the intents' sentences in one language."""

    def __init__(self, language: str, strings: Mapping[str, str]) -> None:
        self.language = language
        self._strings = strings

    @classmethod
    async def async_load(cls, hass: HomeAssistant, requested: str) -> Speech:
        language = speech_language(requested)
        strings = await translation.async_get_translations(hass, language, "exceptions", {DOMAIN})
        return cls(language, strings)

    def _template(self, key: str) -> str | None:
        return self._strings.get(f"component.{DOMAIN}.exceptions.{key}.message")

    def __call__(self, key: str, /, **placeholders: object) -> str:
        template = self._template(key)
        if template is None:
            raise KeyError(f"No speech for {key!r}")
        return template.format(**placeholders)

    def count(self, key: str, count: int, /, **placeholders: object) -> str:
        """The ``key_<plural category>`` sentence for *count* (``key_other`` if absent)."""
        category = f"{key}_{plural_category(self.language, count)}"
        resolved = category if self._template(category) is not None else f"{key}_other"
        return self(resolved, count=count, **placeholders)

    def error(self, err: HomeAssistantError) -> str:
        """An error's message, rendered like Home Assistant does but in this language."""
        if err.translation_domain != DOMAIN or not err.translation_key:
            return str(err)
        template = self._template(err.translation_key)
        if template is None:
            return str(err)
        return template.rstrip(".").format(**(err.translation_placeholders or {}))

    def amount(self, value: float) -> str:
        """A quantity: at most 3 decimals, no trailing zeros or float drift."""
        text = f"{value:.3f}".rstrip("0").rstrip(".")
        if text == "-0":
            return "0"
        return text.replace(".", ",") if self.language in _DECIMAL_COMMA else text

    def and_list(self, names: list[str]) -> str:
        """'A' / 'A and B' / 'A, B, and C' in this language."""
        return self._join(names, "speech_list_and_two", "speech_list_and_many")

    def or_list(self, names: list[str]) -> str:
        """'A' / 'A or B' / 'A, B or C' in this language."""
        return self._join(names, "speech_list_or", "speech_list_or")

    def _join(self, names: list[str], two: str, many: str) -> str:
        if len(names) == 1:
            return names[0]
        key = two if len(names) == 2 else many
        return self(key, first=", ".join(names[:-1]), last=names[-1])
