"""The sidebar panel follows the global entry's options."""

import os
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient
from homeassistant.components import frontend
from homeassistant.components.frontend import DATA_PANELS, Panel
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import (  # type: ignore[import-untyped]
    MockConfigEntry,
)
from pytest_homeassistant_custom_component.typing import (  # type: ignore[import-untyped]
    ClientSessionGenerator,
)

from custom_components.simple_inventory.const import DOMAIN
from custom_components.simple_inventory.panel import PANEL_URL_PATH, async_sync_panel
from custom_components.simple_inventory.repairs import ISSUE_PANEL_BUNDLE_MISSING

from .harness import add_entry, integration_env, setup_entry


@pytest.fixture(autouse=True)
def _custom_integrations(enable_custom_integrations: None) -> None:
    """Every test sets the integration up for real."""


BUNDLE = Path("www/community/simple-inventory-card/simple-inventory-panel.js")
BUNDLE_URL = "/local/community/simple-inventory-card/simple-inventory-panel.js"
LOADER_URL = "/api/simple_inventory/panel-loader.js"


def _write_bundle(config_dir: Path, mtime: int = 1_700_000_000) -> None:
    path = config_dir / BUNDLE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("export {};")
    os.utime(path, (mtime, mtime))


def _panel(hass: HomeAssistant) -> Panel | None:
    return hass.data.get(DATA_PANELS, {}).get(PANEL_URL_PATH)


def _registered_panel(hass: HomeAssistant) -> Panel:
    panel = _panel(hass)
    assert panel is not None
    return panel


def _bundle_issue(hass: HomeAssistant) -> ir.IssueEntry | None:
    return ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_PANEL_BUNDLE_MISSING)


async def _global_entry(hass: HomeAssistant, **options: bool) -> MockConfigEntry:
    entry = add_entry(hass, "global_entry", "All Items Expiring Soon", entry_type="global")
    hass.config_entries.async_update_entry(entry, options=options)
    await setup_entry(hass, entry)
    return entry


async def test_panel_registered_when_enabled(hass: HomeAssistant, tmp_path: Path) -> None:
    async with integration_env(hass, tmp_path):
        _write_bundle(tmp_path)
        await _global_entry(hass, show_panel=True)

        panel = _registered_panel(hass)
        assert panel.sidebar_title == "Inventory"
        assert panel.sidebar_icon == "mdi:package-variant-closed"
        assert panel.require_admin is False
        assert panel.config is not None
        # Newer Home Assistant versions add their own defaults (e.g. handle_safe_area).
        assert (
            panel.config["_panel_custom"].items()
            >= {
                "name": "simple-inventory-panel",
                "embed_iframe": False,
                "trust_external": False,
                "module_url": "/api/simple_inventory/panel-loader.js",
            }.items()
        )
        assert _bundle_issue(hass) is None


async def test_panel_admin_only(hass: HomeAssistant, tmp_path: Path) -> None:
    async with integration_env(hass, tmp_path):
        _write_bundle(tmp_path)
        await _global_entry(hass, show_panel=True, panel_admin_only=True)
        assert _registered_panel(hass).require_admin is True


async def test_no_panel_by_default(hass: HomeAssistant, tmp_path: Path) -> None:
    async with integration_env(hass, tmp_path):
        _write_bundle(tmp_path)
        await _global_entry(hass)
        assert _panel(hass) is None


async def test_unloading_global_entry_removes_panel(hass: HomeAssistant, tmp_path: Path) -> None:
    async with integration_env(hass, tmp_path):
        _write_bundle(tmp_path)
        entry = await _global_entry(hass, show_panel=True)

        assert await hass.config_entries.async_unload(entry.entry_id)

        assert _panel(hass) is None


async def test_unloading_global_entry_deletes_bundle_issue(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    async with integration_env(hass, tmp_path):
        entry = await _global_entry(hass, show_panel=True)
        assert _bundle_issue(hass) is not None

        assert await hass.config_entries.async_unload(entry.entry_id)

        assert _bundle_issue(hass) is None


async def test_changing_options_reregisters_panel(hass: HomeAssistant, tmp_path: Path) -> None:
    async with integration_env(hass, tmp_path):
        _write_bundle(tmp_path)
        entry = await _global_entry(hass, show_panel=True)

        hass.config_entries.async_update_entry(
            entry, options={"show_panel": True, "panel_admin_only": True}
        )
        await hass.async_block_till_done()  # the update listener reloads the entry
        assert _registered_panel(hass).require_admin is True

        hass.config_entries.async_update_entry(entry, options={"show_panel": False})
        await hass.async_block_till_done()
        assert _panel(hass) is None


async def test_missing_bundle_registers_panel_and_raises_issue(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    async with integration_env(hass, tmp_path):
        entry = await _global_entry(hass, show_panel=True)

        assert _registered_panel(hass).config is not None
        issue = _bundle_issue(hass)
        assert issue is not None
        assert issue.severity == ir.IssueSeverity.WARNING
        assert issue.is_fixable is False
        assert issue.translation_placeholders == {"path": str(tmp_path / BUNDLE)}

        _write_bundle(tmp_path)
        await async_sync_panel(hass, entry)
        assert _bundle_issue(hass) is None


async def test_disabled_panel_clears_issue(hass: HomeAssistant, tmp_path: Path) -> None:
    async with integration_env(hass, tmp_path):
        entry = await _global_entry(hass, show_panel=True)
        assert _bundle_issue(hass) is not None

        hass.config_entries.async_update_entry(entry, options={"show_panel": False})
        await hass.async_block_till_done()
        assert _bundle_issue(hass) is None


async def test_taken_url_path_logs_and_setup_continues(
    hass: HomeAssistant, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """HA raises ValueError for a taken URL path; the foreign panel is left alone."""
    async with integration_env(hass, tmp_path):
        _write_bundle(tmp_path)
        frontend.async_register_built_in_panel(hass, "iframe", frontend_url_path=PANEL_URL_PATH)
        entry = await _global_entry(hass, show_panel=True)

        assert entry.state is ConfigEntryState.LOADED
        assert "Could not register the Simple Inventory panel" in caplog.text
        assert _registered_panel(hass).component_name == "iframe"

        assert await hass.config_entries.async_unload(entry.entry_id)
        assert _registered_panel(hass).component_name == "iframe"


async def test_inventory_entries_do_not_register_panel(hass: HomeAssistant, tmp_path: Path) -> None:
    async with integration_env(hass, tmp_path):
        _write_bundle(tmp_path)
        entry = add_entry(hass, "kitchen", "Kitchen")
        hass.config_entries.async_update_entry(entry, options={"show_panel": True})
        await setup_entry(hass, entry)
        assert _panel(hass) is None


async def test_saving_unchanged_options_resyncs_panel(hass: HomeAssistant, tmp_path: Path) -> None:
    """Saving the same options fires no update listener, so the flow re-syncs itself."""
    async with integration_env(hass, tmp_path):
        await _global_entry(hass, show_panel=True, panel_admin_only=False)
        assert _bundle_issue(hass) is not None

        _write_bundle(tmp_path)
        flow = await hass.config_entries.options.async_init("global_entry")
        result = await hass.config_entries.options.async_configure(
            flow["flow_id"], {"show_panel": True, "panel_admin_only": False}
        )
        await hass.async_block_till_done()

        assert result["type"] == "create_entry"
        assert _bundle_issue(hass) is None
        assert _registered_panel(hass).require_admin is False


async def test_unreadable_bundle_path_raises_issue(hass: HomeAssistant, tmp_path: Path) -> None:
    """A regular file where the card folder belongs is a missing bundle, not a setup failure."""
    async with integration_env(hass, tmp_path):
        card_dir = tmp_path / BUNDLE.parent
        card_dir.parent.mkdir(parents=True)
        card_dir.write_text("not a folder")

        entry = await _global_entry(hass, show_panel=True)

        assert entry.state is ConfigEntryState.LOADED
        assert _bundle_issue(hass) is not None
        assert _registered_panel(hass).config is not None


async def _loader_body(client: TestClient) -> str:
    response = await client.get(LOADER_URL)
    assert response.status == 200
    assert response.headers["Content-Type"].startswith("text/javascript")
    assert response.headers["Cache-Control"] == "no-cache"
    return await response.text()


async def test_loader_imports_the_current_bundle_without_auth(
    hass: HomeAssistant, tmp_path: Path, hass_client_no_auth: ClientSessionGenerator
) -> None:
    """The loader is never cached, so a card update reaches browsers without a restart."""
    async with integration_env(hass, tmp_path):
        _write_bundle(tmp_path)
        await _global_entry(hass, show_panel=True)
        panel = _registered_panel(hass)
        client = await hass_client_no_auth()

        assert await _loader_body(client) == f'import "{BUNDLE_URL}?v=1700000000";\n'

        _write_bundle(tmp_path, mtime=1_800_000_000)
        assert await _loader_body(client) == f'import "{BUNDLE_URL}?v=1800000000";\n'
        assert _registered_panel(hass) is panel  # no re-registration needed


async def test_loader_without_bundle_imports_version_zero(
    hass: HomeAssistant, tmp_path: Path, hass_client_no_auth: ClientSessionGenerator
) -> None:
    async with integration_env(hass, tmp_path):
        await _global_entry(hass, show_panel=True)
        client = await hass_client_no_auth()

        assert await _loader_body(client) == f'import "{BUNDLE_URL}?v=0";\n'
