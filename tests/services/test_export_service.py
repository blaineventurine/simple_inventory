"""The export service, mirroring the ws_export WebSocket command."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from custom_components.simple_inventory.const import DOMAIN

from ..harness import add_entry, integration_env, setup_entry

KITCHEN = "kitchen_entry"


async def test_export_returns_json_by_default(
    hass: HomeAssistant, tmp_path: Path, enable_custom_integrations: None
) -> None:
    async with integration_env(hass, tmp_path) as env:
        entry = add_entry(env, KITCHEN, "Kitchen")
        await setup_entry(env, entry)
        await env.services.async_call(
            DOMAIN,
            "add_item",
            {"inventory_id": KITCHEN, "name": "Milk", "quantity": 2},
            blocking=True,
        )

        result = await env.services.async_call(
            DOMAIN, "export", {"inventory_id": KITCHEN}, blocking=True, return_response=True
        )

        assert result is not None
        assert result["format"] == "json"
        data = cast(dict[str, Any], result["data"])
        assert data["items"][0]["name"] == "Milk"


async def test_export_supports_csv(
    hass: HomeAssistant, tmp_path: Path, enable_custom_integrations: None
) -> None:
    async with integration_env(hass, tmp_path) as env:
        entry = add_entry(env, KITCHEN, "Kitchen")
        await setup_entry(env, entry)
        await env.services.async_call(
            DOMAIN,
            "add_item",
            {"inventory_id": KITCHEN, "name": "Milk", "quantity": 2},
            blocking=True,
        )

        result = await env.services.async_call(
            DOMAIN,
            "export",
            {"inventory_id": KITCHEN, "format": "csv"},
            blocking=True,
            return_response=True,
        )

        assert result is not None
        assert result["format"] == "csv"
        assert "Milk" in cast(str, result["data"])


async def test_export_with_unloaded_inventory_raises(
    hass: HomeAssistant, tmp_path: Path, enable_custom_integrations: None
) -> None:
    async with integration_env(hass, tmp_path) as env:
        entry = add_entry(env, KITCHEN, "Kitchen")
        await setup_entry(env, entry)

        with pytest.raises(ServiceValidationError):
            await env.services.async_call(
                DOMAIN,
                "export",
                {"inventory_id": "nonexistent"},
                blocking=True,
                return_response=True,
            )
