"""LLM tools for Simple Inventory's native intents.

Home Assistant's LLM tool aggregator (homeassistant.components.llm) only
includes tools that an integration explicitly contributes via its own
llm.py platform.

Registering an IntentHandler via intent.async_register() does not, by
itself, expose it to LLM-backed conversation agents; this module is what
does that for every intent in INTENT_TYPES.

Unlike built-in device-control intents (HassTurnOn and friends), these
intents operate on inventory data resolved by name (see
services/resolvers.py), not on Home Assistant entities, so there is no
entity for the user to expose or hide via Assist's exposure settings,
these tools are offered unconditionally whenever an LLM API is requested.
"""

from __future__ import annotations

from homeassistant.components.llm import LLMTools
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import intent
from homeassistant.helpers.llm import LLM_API_ASSIST, IntentTool, LLMContext, Tool

from .entries import enabled_inventory_entries, entry_display_name
from .intents import INTENT_TYPES


@callback
def async_get_tools(hass: HomeAssistant, llm_context: LLMContext, api_id: str) -> LLMTools | None:
    """Return an LLM tool for each of Simple Inventory's registered intents.

    Tools are built per request, so each description ends with the current inventory
    names: the agent can fill the inventory parameter with a real name instead of guessing.
    """
    if api_id != LLM_API_ASSIST:
        return None

    tools: list[Tool] = [
        IntentTool(handler.intent_type, handler)
        for handler in intent.async_get(hass)
        if handler.intent_type in INTENT_TYPES
    ]
    if not tools:
        return None

    names = sorted(
        (entry_display_name(entry) for entry in enabled_inventory_entries(hass)), key=str.casefold
    )
    if names:
        for tool in tools:
            tool.description = f"{tool.description} Inventories: {', '.join(names)}."
    return LLMTools(tools=tools)
