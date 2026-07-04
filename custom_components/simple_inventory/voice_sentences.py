"""Install the bundled example custom_sentences template for local Assist.

Writes a copy of the bundled sentence template (data/custom_sentences/) into
the user's Home Assistant config directory, if a template exists for the
active language and nothing already exists at the target path."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import language as language_util

_LOGGER = logging.getLogger(__name__)

_BUNDLED_ROOT = Path(__file__).parent / "data" / "custom_sentences"
_FILENAME = "simple_inventory.yaml"


def _discover_bundled_languages() -> frozenset[str]:
    """Return the set of languages this package ships a sentence template for."""
    if not _BUNDLED_ROOT.is_dir():
        return frozenset()
    return frozenset(
        child.name
        for child in _BUNDLED_ROOT.iterdir()
        if child.is_dir() and (child / _FILENAME).is_file()
    )


_BUNDLED_LANGUAGES = _discover_bundled_languages()


def _matched_bundled_language(language: str) -> str | None:
    """Resolve `language` to a bundled language key."""
    matches = language_util.matches(language, _BUNDLED_LANGUAGES)
    return matches[0] if matches else None


def can_offer_voice_sentences(hass: HomeAssistant) -> bool:
    """Return True if a bundled sentence template matches hass.config.language."""
    return _matched_bundled_language(hass.config.language) is not None


def _copy_template(source: Path, target: Path) -> None:
    """Blocking, exclusive-create file copy; must only be called via the executor."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "xb") as dest, open(source, "rb") as src:
        shutil.copyfileobj(src, dest)


async def async_install_voice_sentences(hass: HomeAssistant) -> bool:
    """Install the bundled sentence template matching hass.config.language."""
    language = hass.config.language
    matched_language = _matched_bundled_language(language)
    if matched_language is None:
        return False

    source = _BUNDLED_ROOT / matched_language / _FILENAME
    target = Path(hass.config.path("custom_sentences", matched_language, _FILENAME))

    if await hass.async_add_executor_job(target.is_file):
        return True

    try:
        await hass.async_add_executor_job(_copy_template, source, target)
    except FileExistsError:
        return True
    except OSError as err:
        _LOGGER.warning("Could not install example voice sentences: %s", err)
        return False

    try:
        await hass.services.async_call(
            "conversation",
            "reload",
            {"language": matched_language},
            blocking=True,
        )
    except HomeAssistantError as err:
        _LOGGER.warning(
            "Installed example voice sentences but failed to reload custom "
            "sentences (they will take effect on next restart): %s",
            err,
        )

    return True
