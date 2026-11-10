"""The opt-in full-page sidebar panel, served from the Simple Inventory card's folder."""

from __future__ import annotations

import logging
from pathlib import Path

from aiohttp import web
from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import KEY_HASS, HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .const import CONF_PANEL_ADMIN_ONLY, CONF_SHOW_PANEL
from .repairs import (
    async_create_panel_bundle_missing_issue,
    async_delete_panel_bundle_missing_issue,
)

_LOGGER = logging.getLogger(__name__)

PANEL_URL_PATH = "simple-inventory"
PANEL_ELEMENT = "simple-inventory-panel"
PANEL_TITLE = "Inventory"
PANEL_ICON = "mdi:package-variant-closed"
# HACS installs the card (and every file next to it) into www/community/<repository>/;
# /local serves www/, so the URL also works for a card copied there by hand.
_BUNDLE_PARTS = ("www", "community", "simple-inventory-card", "simple-inventory-panel.js")
_BUNDLE_URL = "/local/community/simple-inventory-card/simple-inventory-panel.js"
# /local responses are cached for 31 days, so the panel loads this never-cached module, which
# imports the bundle stamped with its current mtime: a card update needs no HA restart.
LOADER_URL = "/api/simple_inventory/panel-loader.js"


def _bundle_path(hass: HomeAssistant) -> Path:
    return Path(hass.config.path(*_BUNDLE_PARTS))


def _bundle_mtime(path: Path) -> int | None:
    """The bundle's modification time, or None when it is missing or unreadable."""
    try:
        return int(path.stat().st_mtime)
    except OSError:
        return None


class PanelLoaderView(HomeAssistantView):
    """The panel's module: imports the bundle under a cache-busting ``?v=<mtime>``."""

    url = LOADER_URL
    name = "api:simple_inventory:panel_loader"
    # Module scripts load without auth headers; the response reveals only the bundle's mtime.
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app[KEY_HASS]
        mtime = await hass.async_add_executor_job(_bundle_mtime, _bundle_path(hass))
        return web.Response(
            text=f'import "{_BUNDLE_URL}?v={mtime or 0}";\n',
            content_type="text/javascript",
            headers={"Cache-Control": "no-cache"},
        )


@callback
def async_register_panel_loader_view(hass: HomeAssistant) -> None:
    """Register the loader (once per Home Assistant run; views cannot be unregistered)."""
    hass.http.register_view(PanelLoaderView())


@callback
def async_remove_panel(hass: HomeAssistant) -> None:
    """Remove our panel; a foreign panel on the same path is left alone."""
    panel = hass.data.get(frontend.DATA_PANELS, {}).get(PANEL_URL_PATH)
    if panel is None:
        return
    custom = (panel.config or {}).get("_panel_custom", {})
    if panel.component_name == "custom" and custom.get("name") == PANEL_ELEMENT:
        frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)


async def async_sync_panel(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register or remove the panel to match the global entry's options."""
    async_remove_panel(hass)
    if not entry.options.get(CONF_SHOW_PANEL, False):
        async_delete_panel_bundle_missing_issue(hass)
        return

    bundle = _bundle_path(hass)
    if await hass.async_add_executor_job(_bundle_mtime, bundle) is None:
        async_create_panel_bundle_missing_issue(hass, str(bundle))
    else:
        async_delete_panel_bundle_missing_issue(hass)

    try:
        await panel_custom.async_register_panel(
            hass,
            frontend_url_path=PANEL_URL_PATH,
            webcomponent_name=PANEL_ELEMENT,
            sidebar_title=PANEL_TITLE,
            sidebar_icon=PANEL_ICON,
            module_url=LOADER_URL,
            require_admin=bool(entry.options.get(CONF_PANEL_ADMIN_ONLY, False)),
            config={},
        )
    except ValueError as err:  # the URL path is taken by another panel
        _LOGGER.error("Could not register the Simple Inventory panel: %s", err)


@callback
def async_unload_panel(hass: HomeAssistant) -> None:
    """The global entry unloads: no panel and no bundle issue without it."""
    async_remove_panel(hass)
    async_delete_panel_bundle_missing_issue(hass)
