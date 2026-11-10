"""Tests for the llm.py platform that exposes Simple Inventory's intents as
LLM tools to LLM-backed conversation agents (OpenAI, Google Generative AI,
a local model via Ollama, etc.) using Home Assistant's Assist API.
"""

from __future__ import annotations

from typing import Any

import probatio
import pytest
from homeassistant.config_entries import ConfigEntryDisabler
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent, llm, translation
from homeassistant.helpers.llm import (
    LLM_API_ASSIST,
    IntentTool,
    LLMContext,
    ToolInput,
    ToolResult,
)
from pytest_homeassistant_custom_component.common import (  # type: ignore[import-untyped]
    MockConfigEntry,
)

from custom_components.simple_inventory.const import DOMAIN
from custom_components.simple_inventory.intents import (
    INTENT_ADD_ITEM,
    INTENT_LOW_STOCK_COUNT_QUERY,
    INTENT_REMOVE_ITEM,
    INTENT_TRANSFER_ITEM,
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


def _openapi(parameters: object) -> dict[str, Any]:
    """A tool's parameters as conversation agents send them to the model."""
    schema: dict[str, Any] = probatio.to_openapi(
        parameters, custom_serializer=llm.selector_serializer
    )
    return schema


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
        assert len(result.tools) == len(INTENT_TYPES)
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
    nothing to expose or hide. All 8 must be returned regardless of `assistant`."""
    async_register_intents(hass)
    try:
        result = async_get_tools(hass, _llm_context(assistant), LLM_API_ASSIST)
        assert result is not None
        assert len(result.tools) == len(INTENT_TYPES)
    finally:
        async_unregister_intents(hass)


def test_quantity_tools_describe_optional_location(hass: HomeAssistant) -> None:
    """LLM agents see the location parameter and what it means (HA converts slot_schema)."""
    async_register_intents(hass)
    try:
        result = async_get_tools(hass, _llm_context(), LLM_API_ASSIST)
        assert result is not None
        tools = {tool.name: tool for tool in result.tools}
        for name in (INTENT_ADD_ITEM, INTENT_REMOVE_ITEM):
            schema = _openapi(tools[name].parameters)
            assert "location" not in schema.get("required", [])
            assert schema["properties"]["location"]["description"] == (
                "Storage spot inside the inventory (e.g. Fridge, Garage). "
                "Only set it when the user names where the stock is."
            )
            assert str(tools[name].description).endswith(
                "An optional location names the storage spot inside the inventory."
            )
    finally:
        async_unregister_intents(hass)


def test_transfer_tool_requires_a_destination_and_describes_locations(
    hass: HomeAssistant,
) -> None:
    async_register_intents(hass)
    try:
        result = async_get_tools(hass, _llm_context(), LLM_API_ASSIST)
        assert result is not None
        tools = {tool.name: tool for tool in result.tools}
        schema = _openapi(tools[INTENT_TRANSFER_ITEM].parameters)
        assert set(schema["required"]) == {"item", "inventory", "to_location"}
        assert schema["properties"]["to_location"]["description"] == (
            "Existing storage spot inside the inventory to move the stock to (e.g. Garage)."
        )
        assert schema["properties"]["from_location"]["description"] == (
            "Existing storage spot the stock is taken from. "
            "Only set it when the user names where the stock is now."
        )
    finally:
        async_unregister_intents(hass)


async def test_refusal_reaches_the_llm_as_tool_output(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """A refusal is a spoken error response, so the tool result carries its message."""
    # Intents register on entry setup, which caches the integration's translations.
    await translation.async_load_integrations(hass, {DOMAIN})
    hass.config.components.add(DOMAIN)
    async_register_intents(hass)
    try:
        tools = async_get_tools(hass, _llm_context(), LLM_API_ASSIST)
        assert tools is not None
        [tool] = [tool for tool in tools.tools if tool.name == INTENT_LOW_STOCK_COUNT_QUERY]

        result = await tool.async_call(
            hass, ToolInput(tool_name=tool.name, tool_args={}), _llm_context()
        )
    finally:
        async_unregister_intents(hass)

    assert isinstance(result, ToolResult)
    assert result.data["response_type"] == "error"
    assert result.data["data"] == {"code": "failed_to_handle"}
    assert result.data["speech"] == {
        "plain": {"speech": "No inventories configured", "extra_data": None}
    }


def test_tools_with_an_inventory_slot_name_the_current_inventories(hass: HomeAssistant) -> None:
    """The agent picks a real inventory name instead of guessing one."""
    for entry_id, name in (("k", "Kitchen"), ("g", "Garage")):
        MockConfigEntry(
            domain=DOMAIN, entry_id=entry_id, data={"name": name, "entry_type": "inventory"}
        ).add_to_hass(hass)
    MockConfigEntry(
        domain=DOMAIN,
        entry_id="off",
        data={"name": "Attic", "entry_type": "inventory"},
        disabled_by=ConfigEntryDisabler.USER,
    ).add_to_hass(hass)
    async_register_intents(hass)
    try:
        tools = async_get_tools(hass, _llm_context(), LLM_API_ASSIST)
        assert tools is not None
        by_name = {tool.name: tool.description for tool in tools.tools}
        for name, description in by_name.items():
            assert description is not None, name
            assert description.endswith("Inventories: Garage, Kitchen."), name
    finally:
        async_unregister_intents(hass)


def test_tools_name_no_inventories_when_there_are_none(hass: HomeAssistant) -> None:
    async_register_intents(hass)
    try:
        tools = async_get_tools(hass, _llm_context(), LLM_API_ASSIST)
        assert tools is not None
        assert all("Inventories:" not in (tool.description or "") for tool in tools.tools)
    finally:
        async_unregister_intents(hass)
