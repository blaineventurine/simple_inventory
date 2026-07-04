"""Tests for the voice-sentence auto-install helper."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError

from custom_components.simple_inventory.voice_sentences import (
    async_install_voice_sentences,
    can_offer_voice_sentences,
)


@pytest.fixture
def hass_with_tmp_config(hass: HomeAssistant, tmp_path: Path) -> HomeAssistant:
    hass.config.config_dir = str(tmp_path)

    def _path(*parts: str) -> str:
        return str(tmp_path.joinpath(*parts))

    hass.config.path = _path  # type: ignore[method-assign]
    return hass


def test_can_offer_voice_sentences_true_for_english(hass: HomeAssistant) -> None:
    hass.config.language = "en"
    assert can_offer_voice_sentences(hass) is True


def test_can_offer_voice_sentences_false_for_unbundled_language(hass: HomeAssistant) -> None:
    hass.config.language = "xx"
    assert can_offer_voice_sentences(hass) is False


@pytest.mark.asyncio
async def test_install_writes_file_and_reloads(hass_with_tmp_config: HomeAssistant) -> None:
    hass_with_tmp_config.config.language = "en"
    reload_calls: list[dict] = []

    async def _reload(call: ServiceCall) -> None:
        reload_calls.append(dict(call.data))

    hass_with_tmp_config.services.async_register("conversation", "reload", _reload)

    result = await async_install_voice_sentences(hass_with_tmp_config)

    assert result is True
    target = Path(
        hass_with_tmp_config.config.path("custom_sentences", "en", "simple_inventory.yaml")
    )
    assert target.is_file()
    assert "SimpleInventoryRemoveItem" in target.read_text()
    assert reload_calls == [{"language": "en"}]


@pytest.mark.asyncio
async def test_install_never_overwrites_existing_file(hass_with_tmp_config: HomeAssistant) -> None:
    hass_with_tmp_config.config.language = "en"
    reload_calls: list[dict] = []

    async def _reload(call: ServiceCall) -> None:
        reload_calls.append(dict(call.data))

    hass_with_tmp_config.services.async_register("conversation", "reload", _reload)

    target = Path(
        hass_with_tmp_config.config.path("custom_sentences", "en", "simple_inventory.yaml")
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("language: en\n# my own custom content\n")

    result = await async_install_voice_sentences(hass_with_tmp_config)

    assert result is True
    assert target.read_text() == "language: en\n# my own custom content\n"
    assert reload_calls == []


@pytest.mark.asyncio
async def test_install_returns_false_for_unbundled_language(
    hass_with_tmp_config: HomeAssistant,
) -> None:
    hass_with_tmp_config.config.language = "xx"

    result = await async_install_voice_sentences(hass_with_tmp_config)

    assert result is False


@pytest.mark.asyncio
async def test_install_handles_write_failure_gracefully(
    hass_with_tmp_config: HomeAssistant,
) -> None:
    """On a write failure, the function must return False and leave no file
    behind. The `_copy_template` failure happens before the reload call is
    ever reached, so this also implicitly guards against a reload attempt on
    a failed install (the code path that would call it never executes)."""
    hass_with_tmp_config.config.language = "en"

    with patch(
        "custom_components.simple_inventory.voice_sentences._copy_template",
        side_effect=OSError("disk full"),
    ):
        result = await async_install_voice_sentences(hass_with_tmp_config)

    assert result is False
    target = Path(
        hass_with_tmp_config.config.path("custom_sentences", "en", "simple_inventory.yaml")
    )
    assert not target.is_file()


@pytest.mark.asyncio
async def test_install_survives_reload_service_failure(
    hass_with_tmp_config: HomeAssistant,
) -> None:
    """The file is written and the function still reports success even if the
    conversation.reload call itself fails (it'll take effect on next restart)."""
    hass_with_tmp_config.config.language = "en"

    async def _reload(call: ServiceCall) -> None:
        raise HomeAssistantError("conversation not ready")

    hass_with_tmp_config.services.async_register("conversation", "reload", _reload)

    result = await async_install_voice_sentences(hass_with_tmp_config)

    assert result is True
    target = Path(
        hass_with_tmp_config.config.path("custom_sentences", "en", "simple_inventory.yaml")
    )
    assert target.is_file()


def test_can_offer_voice_sentences_true_for_en_gb_variant(hass: HomeAssistant) -> None:
    hass.config.language = "en-GB"
    assert can_offer_voice_sentences(hass) is True


@pytest.mark.asyncio
async def test_install_writes_to_matched_base_language_for_variant(
    hass_with_tmp_config: HomeAssistant,
) -> None:
    """An 'en-US' instance must get the file at custom_sentences/en/ (where HA's
    own loader will actually look), not custom_sentences/en-US/."""
    hass_with_tmp_config.config.language = "en-US"
    reload_calls: list[dict] = []

    async def _reload(call: ServiceCall) -> None:
        reload_calls.append(dict(call.data))

    hass_with_tmp_config.services.async_register("conversation", "reload", _reload)

    result = await async_install_voice_sentences(hass_with_tmp_config)

    assert result is True
    target = Path(
        hass_with_tmp_config.config.path("custom_sentences", "en", "simple_inventory.yaml")
    )
    assert target.is_file()
    variant_target = Path(
        hass_with_tmp_config.config.path("custom_sentences", "en-US", "simple_inventory.yaml")
    )
    assert not variant_target.exists()
    assert reload_calls == [{"language": "en"}]


@pytest.mark.asyncio
async def test_install_toctou_race_treated_as_already_present(
    hass_with_tmp_config: HomeAssistant,
) -> None:
    """If the target gets created between our is_file() check and the copy
    attempt, the resulting FileExistsError must be treated as success
    (already installed), not a failure, and must not trigger a reload."""
    hass_with_tmp_config.config.language = "en"
    reload_calls: list[dict] = []

    async def _reload(call: ServiceCall) -> None:
        reload_calls.append(dict(call.data))

    hass_with_tmp_config.services.async_register("conversation", "reload", _reload)

    with patch(
        "custom_components.simple_inventory.voice_sentences._copy_template",
        side_effect=FileExistsError(),
    ):
        result = await async_install_voice_sentences(hass_with_tmp_config)

    assert result is True
    assert reload_calls == []


def test_copy_template_raises_file_exists_error_without_touching_content(
    tmp_path: Path,
) -> None:
    from custom_components.simple_inventory.voice_sentences import _BUNDLED_ROOT, _copy_template

    source = _BUNDLED_ROOT / "en" / "simple_inventory.yaml"
    target = tmp_path / "simple_inventory.yaml"
    target.write_text("already here, must survive")

    with pytest.raises(FileExistsError):
        _copy_template(source, target)

    assert target.read_text() == "already here, must survive"
