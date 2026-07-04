"""Tests for the llm.py platform that exposes Simple Inventory's intents as
LLM tools to LLM-backed conversation agents (OpenAI, Google Generative AI,
a local model via Ollama, etc.) using Home Assistant's Assist API.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent
from homeassistant.helpers.llm import LLM_API_ASSIST, IntentTool, LLMContext

from custom_components.simple_inventory.intents import (
    INTENT_TYPES,
    async_register_intents,
    async_unregister_intents,
)
from custom_components.simple_inventory.llm import async_get_tools


def _llm_context(assistant: str = "conversation") -> LLMContext:
    return LLMContext(
        platform="conversation",
        context=None,
        language="en",
        assistant=assistant,
        device_id=None,
    )


def test_async_get_tools_returns_none_for_a_different_api(hass: HomeAssistant) -> None:
    async_register_intents(hass)
    try:
        assert async_get_tools(hass, _llm_context(), "some_other_api") is None
    finally:
        async_unregister_intents(hass)


def test_async_get_tools_returns_none_when_no_intents_registered(hass: HomeAssistant) -> None:
    """No Simple Inventory intents registered -> no tools, not an empty-list LLMTools."""
    assert async_get_tools(hass, _llm_context(), LLM_API_ASSIST) is None


def test_async_get_tools_wraps_all_registered_intents(hass: HomeAssistant) -> None:
    async_register_intents(hass)
    try:
        result = async_get_tools(hass, _llm_context(), LLM_API_ASSIST)
        assert result is not None
        assert len(result.tools) == 7
        assert all(isinstance(tool, IntentTool) for tool in result.tools)
        assert {tool.name for tool in result.tools} == set(INTENT_TYPES)
        assert result.prompt is None
    finally:
        async_unregister_intents(hass)


def test_async_get_tools_ignores_unrelated_registered_intents(hass: HomeAssistant) -> None:
    """Only Simple Inventory's own intents become tools, even with others registered."""

    class _OtherIntent(intent.IntentHandler):
        intent_type = "SomeOtherIntegrationIntent"

        async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
            return intent_obj.create_response()

    intent.async_register(hass, _OtherIntent())
    async_register_intents(hass)
    try:
        result = async_get_tools(hass, _llm_context(), LLM_API_ASSIST)
        assert result is not None
        tool_names = {tool.name for tool in result.tools}
        assert tool_names == set(INTENT_TYPES)
        assert "SomeOtherIntegrationIntent" not in tool_names
    finally:
        async_unregister_intents(hass)
        intent.async_remove(hass, "SomeOtherIntegrationIntent")


@pytest.mark.parametrize("assistant", ["conversation", "nonexistent_assistant_id"])
def test_async_get_tools_not_filtered_by_assist_exposure(
    hass: HomeAssistant, assistant: str
) -> None:
    """Unlike entity-domain-scoped intents, these never filter by Assist exposure --
    they resolve inventories/items by name, not by Home Assistant entity, so there's
    nothing to expose or hide. All 7 must be returned regardless of `assistant`."""
    async_register_intents(hass)
    try:
        result = async_get_tools(hass, _llm_context(assistant), LLM_API_ASSIST)
        assert result is not None
        assert len(result.tools) == 7
    finally:
        async_unregister_intents(hass)
