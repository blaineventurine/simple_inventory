"""Tests for the voice-sentence auto-install helper."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryDisabler
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.util.yaml import load_yaml_dict
from pytest_homeassistant_custom_component.common import (  # type: ignore[import-untyped]
    MockConfigEntry,
)

from custom_components.simple_inventory.const import DOMAIN
from custom_components.simple_inventory.repairs import ISSUE_VOICE_SENTENCES_OUTDATED
from custom_components.simple_inventory.voice_sentences import (
    _BUNDLED_ROOT,
    async_install_voice_sentences,
    async_sync_voice_sentences,
    can_offer_voice_sentences,
)

from .harness import add_entry, integration_env, setup_entry

_RELEASED_0_6_0_EN = Path(__file__).parent / "fixtures" / "custom_sentences_en_0.6.0.yaml"


def _sentences_dir(hass: HomeAssistant, language: str = "en") -> Path:
    return Path(hass.config.path("custom_sentences", language))


def _install_template(hass: HomeAssistant, content: bytes | None = None) -> Path:
    target = _sentences_dir(hass) / "simple_inventory.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(
        content if content is not None else (_BUNDLED_ROOT / "en" / target.name).read_bytes()
    )
    return target


def _spoken_names(hass: HomeAssistant, language: str = "en") -> dict[str, str]:
    """``{spoken form: stored name}`` from the generated names file."""
    data = load_yaml_dict(_sentences_dir(hass, language) / "simple_inventory_names.yaml")
    return {value["in"]: value["out"] for value in data["lists"]["simple_inventory_name"]["values"]}


def _capture_reloads(hass: HomeAssistant) -> list[dict]:
    calls: list[dict] = []

    async def _reload(call: ServiceCall) -> None:
        calls.append(dict(call.data))

    hass.services.async_register("conversation", "reload", _reload)
    return calls


def _add(hass: HomeAssistant, name: str, **kwargs: object) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, title=name, data={"name": name}, **kwargs)
    entry.add_to_hass(hass)
    return entry


async def test_sync_lists_enabled_inventories_and_reloads_once(
    hass_with_tmp_config: HomeAssistant,
) -> None:
    hass = hass_with_tmp_config
    _install_template(hass)
    _add(hass, "Freezer")
    _add(hass, "Dry Storage")
    _add(hass, "Old Shed", disabled_by=ConfigEntryDisabler.USER)
    MockConfigEntry(
        domain=DOMAIN, title="All", data={"name": "All", "entry_type": "global"}
    ).add_to_hass(hass)
    reloads = _capture_reloads(hass)

    await async_sync_voice_sentences(hass)
    await async_sync_voice_sentences(hass)

    assert _spoken_names(hass) == {"Dry Storage": "Dry Storage", "Freezer": "Freezer"}
    assert reloads == [{"language": "en"}]


async def test_sync_writes_nothing_where_the_template_is_not_installed(
    hass_with_tmp_config: HomeAssistant,
) -> None:
    hass = hass_with_tmp_config
    _add(hass, "Freezer")
    reloads = _capture_reloads(hass)

    await async_sync_voice_sentences(hass)

    assert not Path(hass.config.path("custom_sentences")).exists()
    assert reloads == []


async def test_sync_drops_template_syntax_from_spoken_names(
    hass_with_tmp_config: HomeAssistant,
) -> None:
    hass = hass_with_tmp_config
    _install_template(hass)
    _add(hass, "Pantry (old) [B] {x} <y> | z")
    _capture_reloads(hass)

    await async_sync_voice_sentences(hass)

    assert _spoken_names(hass) == {"Pantry old B x y z": "Pantry (old) [B] {x} <y> | z"}


async def test_sync_replaces_an_unedited_released_template(
    hass_with_tmp_config: HomeAssistant,
) -> None:
    hass = hass_with_tmp_config
    target = _install_template(hass, _RELEASED_0_6_0_EN.read_bytes())
    reloads = _capture_reloads(hass)

    await async_sync_voice_sentences(hass)

    assert target.read_bytes() == (_BUNDLED_ROOT / "en" / target.name).read_bytes()
    assert reloads == [{"language": "en"}]
    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_VOICE_SENTENCES_OUTDATED) is None


async def test_sync_keeps_an_edited_old_template_and_raises_an_issue(
    hass_with_tmp_config: HomeAssistant,
) -> None:
    hass = hass_with_tmp_config
    edited = _RELEASED_0_6_0_EN.read_bytes() + b"# my own sentences\n"
    target = _install_template(hass, edited)
    _capture_reloads(hass)

    await async_sync_voice_sentences(hass)

    assert target.read_bytes() == edited
    issue = ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_VOICE_SENTENCES_OUTDATED)
    assert issue is not None
    assert issue.translation_placeholders == {"paths": str(target)}

    _install_template(hass)
    await async_sync_voice_sentences(hass)

    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_VOICE_SENTENCES_OUTDATED) is None


async def test_sync_survives_reload_failure(hass_with_tmp_config: HomeAssistant) -> None:
    hass = hass_with_tmp_config
    _install_template(hass)
    _add(hass, "Freezer")

    async def _broken(call: ServiceCall) -> None:
        raise HomeAssistantError("boom")

    hass.services.async_register("conversation", "reload", _broken)

    await async_sync_voice_sentences(hass)

    assert _spoken_names(hass) == {"Freezer": "Freezer"}


@pytest.fixture
def _custom_integrations(enable_custom_integrations: None) -> None:
    """Lifecycle tests set the integration up for real."""


@pytest.mark.usefixtures("_custom_integrations")
async def test_names_follow_inventories_being_added_renamed_and_removed(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    async with integration_env(hass, tmp_path):
        _install_template(hass)
        freezer = add_entry(hass, "freezer_id", "Freezer")
        await setup_entry(hass, freezer)
        assert set(_spoken_names(hass).values()) == {"Freezer"}

        pantry = add_entry(hass, "pantry_id", "Pantry")
        await setup_entry(hass, pantry)
        assert set(_spoken_names(hass).values()) == {"Freezer", "Pantry"}

        hass.config_entries.async_update_entry(
            pantry, data={**pantry.data, "name": "Larder"}, title="Larder"
        )
        await hass.async_block_till_done()
        assert set(_spoken_names(hass).values()) == {"Freezer", "Larder"}

        await hass.config_entries.async_remove(freezer.entry_id)
        await hass.async_block_till_done()
        assert set(_spoken_names(hass).values()) == {"Larder"}


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
    assert (target.parent / "simple_inventory_names.yaml").is_file()
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
