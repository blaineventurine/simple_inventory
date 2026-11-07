"""Spoken answers through Home Assistant's real default conversation agent.

The bundled example sentences are installed as custom sentences, the intents are
registered and the services run on the real stack, so these assert exactly what a
voice user hears -- including refusals, which must not become HA's generic error.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from homeassistant.components import conversation
from homeassistant.core import Context
from homeassistant.helpers import intent, translation
from homeassistant.setup import async_setup_component

from custom_components.simple_inventory.const import DOMAIN
from custom_components.simple_inventory.intents import async_register_intents
from custom_components.simple_inventory.voice_sentences import names_yaml

from ..harness import TodoStack

_BUNDLED_SENTENCES = (
    Path(__file__).parents[2]
    / "custom_components"
    / "simple_inventory"
    / "data"
    / "custom_sentences"
    / "en"
    / "simple_inventory.yaml"
)


@pytest.fixture
async def voice(todo_stack: TodoStack, enable_custom_integrations: None) -> TodoStack:
    """Kitchen with 2 Milk at Fridge Door; locations Fridge Door and Fridge Drawer."""
    hass = todo_stack.hass
    target = Path(hass.config.path("custom_sentences", "en"))
    target.mkdir(parents=True)
    shutil.copy(_BUNDLED_SENTENCES, target / "simple_inventory.yaml")
    # What the integration writes next to the template; HA merges the two files.
    (target / "simple_inventory_names.yaml").write_text(names_yaml("en", ["Kitchen"]))

    # Translated ServiceValidationErrors render from the cache of set-up components.
    await translation.async_load_integrations(hass, {DOMAIN})
    hass.config.components.add(DOMAIN)

    async_register_intents(hass)
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, "conversation", {})

    await todo_stack.call(
        "add_item",
        inventory_id="kitchen",
        name="Milk",
        quantity=2,
        location="Fridge Door, Fridge Drawer",
    )
    return todo_stack


async def _say(stack: TodoStack, text: str) -> intent.IntentResponse:
    result = await conversation.async_converse(stack.hass, text, None, Context(), language="en")
    return result.response


async def _milk(stack: TodoStack) -> float:
    item = await stack.item("kitchen", "Milk")
    assert item is not None
    return float(item["quantity"])


async def test_success_is_spoken(voice: TodoStack) -> None:
    response = await _say(voice, "remove 1 milk from the kitchen")

    assert response.response_type is intent.IntentResponseType.ACTION_DONE
    assert response.speech["plain"]["speech"] == "Removed 1 milk from Kitchen. 1 left."
    assert await _milk(voice) == 1


async def test_quantity_question_speaks_the_stored_names(voice: TodoStack) -> None:
    # An expiring batch is consumed (and listed) first, which fixes the spoken order.
    await voice.call(
        "increment_item",
        inventory_id="kitchen",
        name="Milk",
        amount=1,
        location="Fridge Drawer",
        expiry_date="2099-01-01",
    )

    response = await _say(voice, "how many milks are in the kitchen")

    assert response.response_type is not intent.IntentResponseType.ERROR
    assert response.speech["plain"]["speech"] == (
        "Kitchen has 3 Milk: 1 in Fridge Drawer, 2 in Fridge Door."
    )


@pytest.mark.parametrize(
    ("text", "speech"),
    [
        (
            "add 1 milk to the fridge in the kitchen",
            "Which location in Kitchen did you mean: Fridge Door, Fridge Drawer?",
        ),
        (
            "remove 1 bananas from the kitchen",
            'No item named "bananas" found in inventory "Kitchen"',
        ),
        (
            "move 5 milk from the fridge door to the fridge drawer in the kitchen",
            "Only 2 of Milk available at Fridge Door; nothing was moved",
        ),
    ],
)
async def test_refusals_are_spoken(voice: TodoStack, text: str, speech: str) -> None:
    response = await _say(voice, text)

    assert response.response_type is intent.IntentResponseType.ERROR
    assert response.error_code is intent.IntentResponseErrorCode.FAILED_TO_HANDLE
    assert response.speech["plain"]["speech"] == speech
    assert await _milk(voice) == 2
