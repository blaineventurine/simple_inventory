"""LLM tools for Simple Inventory's native intents.

Home Assistant's LLM tool aggregator (homeassistant.components.llm) only
includes tools that an integration explicitly contributes via its own
llm.py platform.

Registering an IntentHandler via intent.async_register() does not, by
itself, expose it to LLM-backed conversation agents; this module is what
does that for SimpleInventoryRemoveItem/AddItem/QueryItem.

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

from .intents import INTENT_TYPES


@callback
def async_get_tools(hass: HomeAssistant, llm_context: LLMContext, api_id: str) -> LLMTools | None:
    """Return an LLM tool for each of Simple Inventory's registered intents."""
    if api_id != LLM_API_ASSIST:
        return None

    tools: list[Tool] = [
        IntentTool(handler.intent_type, handler)
        for handler in intent.async_get(hass)
        if handler.intent_type in INTENT_TYPES
    ]
    if not tools:
        return None

    return LLMTools(tools=tools)
