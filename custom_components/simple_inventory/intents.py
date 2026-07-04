"""Native Home Assistant intents for voice and AI assistant control.

Registering these IntentHandlers serves two purposes simultaneously:

- Local/offline Assist (e.g. Home Assistant Voice's default pipeline)
  matches a spoken sentence against a user-installed custom_sentences YAML
  (see data/custom_sentences/, installable automatically via the config
  flow's "Install example voice commands" checkbox, or copyable by hand)
  to one of these intent types + slots, then calls async_handle.
- Any LLM-backed conversation agent (OpenAI, Google Generative AI, a local
  model via Ollama, etc.) using HA's built-in Assist API gets these wrapped
  as callable tools - that requires the sibling llm.py module in this
  package (Home Assistant's LLM tool aggregator only discovers tools that
  an integration explicitly contributes via its own llm.py platform; a
  registered IntentHandler is not exposed to LLMs on its own). llm.py uses
  slot_schema as each tool's parameter schema and `description` as the
  tool description.
"""

from __future__ import annotations

import voluptuous as vol
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import intent

from .const import (
    DOMAIN,
    SERVICE_DECREMENT_ITEM,
    SERVICE_GET_ITEMS,
    SERVICE_INCREMENT_ITEM,
    SERVICE_UPDATE_ITEM,
)
from .services.domain_data import get_coordinators
from .services.resolvers import resolve_inventory_id, resolve_item_name

INTENT_REMOVE_ITEM = "SimpleInventoryRemoveItem"
INTENT_ADD_ITEM = "SimpleInventoryAddItem"
INTENT_QUERY_ITEM = "SimpleInventoryQueryItem"
INTENT_EXPIRY_COUNT_QUERY = "SimpleInventoryExpiryCountQuery"
INTENT_LOW_STOCK_COUNT_QUERY = "SimpleInventoryLowStockCountQuery"
INTENT_EXPIRY_LIST_QUERY = "SimpleInventoryExpiryListQuery"
INTENT_SET_ITEM_QUANTITY = "SimpleInventorySetItemQuantity"

INTENT_TYPES = (
    INTENT_REMOVE_ITEM,
    INTENT_ADD_ITEM,
    INTENT_QUERY_ITEM,
    INTENT_EXPIRY_COUNT_QUERY,
    INTENT_LOW_STOCK_COUNT_QUERY,
    INTENT_EXPIRY_LIST_QUERY,
    INTENT_SET_ITEM_QUANTITY,
)


def async_register_intents(hass: HomeAssistant) -> None:
    """Register all Simple Inventory intents. Idempotent; call once per hass."""
    intent.async_register(hass, RemoveItemIntent())
    intent.async_register(hass, AddItemIntent())
    intent.async_register(hass, QueryItemIntent())
    intent.async_register(hass, ExpiryCountIntent())
    intent.async_register(hass, LowStockCountIntent())
    intent.async_register(hass, ExpiryListIntent())
    intent.async_register(hass, SetItemQuantityIntent())


def async_unregister_intents(hass: HomeAssistant) -> None:
    """Remove all Simple Inventory intents."""
    for intent_type in INTENT_TYPES:
        intent.async_remove(hass, intent_type)


def _format_amount(value: float) -> str:
    """Render a quantity for speech without a spurious trailing '.0'."""
    if value == int(value):
        return str(int(value))
    return str(value)


def _format_name_list(names: list[str]) -> str:
    """Join names for speech: 'A' / 'A and B' / 'A, B, and C'."""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f", and {names[-1]}"


def _quantity_from_items(items: list[dict], item_name: str) -> float | None:
    """Find item_name's quantity (case-insensitive) in a get_items result list."""
    lowered = item_name.strip().lower()
    for entry in items:
        if str(entry.get("name", "")).strip().lower() == lowered:
            return float(entry.get("quantity", 0))
    return None


async def _async_current_quantity(
    hass: HomeAssistant, inventory: str, item: str, context: Context
) -> float | None:
    """Best-effort post-change quantity lookup."""
    try:
        result = await hass.services.async_call(
            DOMAIN,
            SERVICE_GET_ITEMS,
            {"inventory_name": inventory},
            blocking=True,
            return_response=True,
            context=context,
        )
    except (HomeAssistantError, ValueError):
        return None
    items_raw = (result or {}).get("items", [])
    items = (
        [entry for entry in items_raw if isinstance(entry, dict)]
        if isinstance(items_raw, list)
        else []
    )
    return _quantity_from_items(items, item)


class _BaseQuantityIntent(intent.IntentHandler):
    """Shared slot parsing + service dispatch for add/remove item intents."""

    _service: str

    @property
    def slot_schema(self) -> dict:
        return {
            vol.Required("item"): intent.non_empty_string,
            vol.Required("inventory"): intent.non_empty_string,
            vol.Optional("quantity"): vol.All(vol.Coerce(float), vol.Range(min=0.001)),
        }

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        hass = intent_obj.hass
        slots = self.async_validate_slots(intent_obj.slots)
        item = str(slots["item"]["value"])
        inventory = str(slots["inventory"]["value"])
        amount = float(slots.get("quantity", {}).get("value", 1))

        try:
            await hass.services.async_call(
                DOMAIN,
                self._service,
                {"inventory_name": inventory, "name": item, "amount": amount},
                blocking=True,
                context=intent_obj.context,
            )
        except ServiceValidationError as err:
            raise intent.IntentHandleError(str(err)) from err

        response = intent_obj.create_response()
        response.async_set_speech(
            await self._async_speech(hass, item, inventory, amount, intent_obj.context)
        )
        return response

    async def _async_speech(
        self, hass: HomeAssistant, item: str, inventory: str, amount: float, context: Context
    ) -> str:
        raise NotImplementedError


class RemoveItemIntent(_BaseQuantityIntent):
    """Remove/consume a quantity of an item from an inventory."""

    intent_type = INTENT_REMOVE_ITEM
    description = (
        "Remove or consume a quantity of an item from a household inventory "
        "(e.g. freezer, dry storage, disposable goods). Use this when the "
        "user says they used up, threw away, ran out of, or want to "
        "subtract stock of an item. Requires the item name and the "
        "inventory name; quantity defaults to 1 if not specified."
    )
    _service = SERVICE_DECREMENT_ITEM

    async def _async_speech(
        self, hass: HomeAssistant, item: str, inventory: str, amount: float, context: Context
    ) -> str:
        base = f"Removed {_format_amount(amount)} {item} from {inventory}."
        remaining = await _async_current_quantity(hass, inventory, item, context)
        if remaining is None:
            return base
        if remaining <= 0:
            return f"{base} None left."
        return f"{base} {_format_amount(remaining)} left."


class AddItemIntent(_BaseQuantityIntent):
    """Add/restock a quantity of an item to an inventory."""

    intent_type = INTENT_ADD_ITEM
    description = (
        "Add or restock a quantity of an item to a household inventory "
        "(e.g. freezer, dry storage, disposable goods). Use this when the "
        "user says they bought, restocked, or want to add stock of an item "
        "that is already tracked. Requires the item name and the inventory "
        "name; quantity defaults to 1 if not specified. Does not create new "
        "items -- the item must already exist in the inventory."
    )
    _service = SERVICE_INCREMENT_ITEM

    async def _async_speech(
        self, hass: HomeAssistant, item: str, inventory: str, amount: float, context: Context
    ) -> str:
        base = f"Added {_format_amount(amount)} {item} to {inventory}."
        remaining = await _async_current_quantity(hass, inventory, item, context)
        if remaining is None:
            return base
        return f"{base} Now at {_format_amount(remaining)}."


class QueryItemIntent(intent.IntentHandler):
    """Look up how much of an item is currently stocked."""

    intent_type = INTENT_QUERY_ITEM
    description = (
        "Look up how much of an item is currently stocked in a household "
        "inventory (e.g. freezer, dry storage, disposable goods). Use this "
        "for questions like 'how many X do we have' or 'are we out of X'. "
        "Does not change any quantities."
    )

    @property
    def slot_schema(self) -> dict:
        return {
            vol.Required("item"): intent.non_empty_string,
            vol.Required("inventory"): intent.non_empty_string,
        }

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        hass = intent_obj.hass
        slots = self.async_validate_slots(intent_obj.slots)
        item = str(slots["item"]["value"])
        inventory = str(slots["inventory"]["value"])

        try:
            inventory_id = await resolve_inventory_id(hass, None, inventory)
            coordinator = get_coordinators(hass).get(inventory_id)
            if coordinator is None:
                raise ServiceValidationError(f"Inventory '{inventory}' is not currently loaded")
            resolved_item = await resolve_item_name(coordinator, inventory_id, item)
        except ServiceValidationError as err:
            raise intent.IntentHandleError(str(err)) from err

        item_data = await coordinator.async_get_item(inventory_id, resolved_item)
        quantity = float(item_data.get("quantity", 0)) if item_data else None

        response = intent_obj.create_response()
        if quantity is None:
            response.async_set_speech(f"I couldn't find {item} in {inventory}.")
        else:
            response.async_set_speech(f"{inventory} has {_format_amount(quantity)} {item}.")
        return response


class ExpiryCountIntent(intent.IntentHandler):
    """Count how many items are expired or expiring soon."""

    intent_type = INTENT_EXPIRY_COUNT_QUERY
    description = (
        "Count how many items are expired or expiring soon in a household "
        "inventory (e.g. freezer, dry storage, disposable goods), or across "
        "all inventories if none is named. Use this for questions like 'how "
        "many items are expired' or 'how many items are expiring soon'. "
        "Does not look up a specific item's quantity -- use "
        "SimpleInventoryQueryItem for that."
    )

    @property
    def slot_schema(self) -> dict:
        return {
            vol.Required("status"): vol.In(["expired", "expiring_soon"]),
            vol.Optional("inventory"): intent.non_empty_string,
        }

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        hass = intent_obj.hass
        slots = self.async_validate_slots(intent_obj.slots)
        status = str(slots["status"]["value"])
        inventory = str(slots["inventory"]["value"]) if "inventory" in slots else None

        coordinators = get_coordinators(hass)
        if not coordinators:
            raise intent.IntentHandleError("No inventories configured")

        inventory_id: str | None = None
        if inventory is not None:
            try:
                inventory_id = await resolve_inventory_id(hass, None, inventory)
            except ServiceValidationError as err:
                raise intent.IntentHandleError(str(err)) from err

        coordinator = next(iter(coordinators.values()))
        expiring = await coordinator.async_get_items_expiring_soon(inventory_id)
        if status == "expired":
            count = sum(1 for entry in expiring if entry["days_until_expiry"] < 0)
            status_phrase = "expired"
        else:
            count = sum(1 for entry in expiring if entry["days_until_expiry"] >= 0)
            status_phrase = "expiring soon"

        noun = "item" if count == 1 else "items"
        verb = "is" if count == 1 else "are"
        speech = f"{count} {noun} {verb} {status_phrase}"
        if inventory is not None:
            speech += f" in {inventory}"
        speech += "."

        response = intent_obj.create_response()
        response.async_set_speech(speech)
        return response


class LowStockCountIntent(intent.IntentHandler):
    """Count how many items are low on stock (at or below their restock threshold)."""

    intent_type = INTENT_LOW_STOCK_COUNT_QUERY
    description = (
        "Count how many items are low on stock (at or below their restock "
        "threshold) in a household inventory (e.g. freezer, dry storage, "
        "disposable goods), or across all inventories if none is named. "
        "Use this for questions like 'how many items are low on stock' or "
        "'what's running low'. Does not look up a specific item's quantity "
        "-- use SimpleInventoryQueryItem for that."
    )

    @property
    def slot_schema(self) -> dict:
        return {
            vol.Optional("inventory"): intent.non_empty_string,
        }

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        hass = intent_obj.hass
        slots = self.async_validate_slots(intent_obj.slots)
        inventory = str(slots["inventory"]["value"]) if "inventory" in slots else None

        coordinators = get_coordinators(hass)
        if not coordinators:
            raise intent.IntentHandleError("No inventories configured")

        inventory_id: str | None = None
        if inventory is not None:
            try:
                inventory_id = await resolve_inventory_id(hass, None, inventory)
            except ServiceValidationError as err:
                raise intent.IntentHandleError(str(err)) from err

        coordinator = next(iter(coordinators.values()))
        low_stock = await coordinator.async_get_low_stock_items(inventory_id)
        count = len(low_stock)

        noun = "item" if count == 1 else "items"
        verb = "is" if count == 1 else "are"
        speech = f"{count} {noun} {verb} low on stock"
        if inventory is not None:
            speech += f" in {inventory}"
        speech += "."

        response = intent_obj.create_response()
        response.async_set_speech(speech)
        return response


class ExpiryListIntent(intent.IntentHandler):
    """List which items are expired or expiring soon (not just a count)."""

    intent_type = INTENT_EXPIRY_LIST_QUERY
    description = (
        "List by name which items are expired or expiring soon in a "
        "household inventory (e.g. freezer, dry storage, disposable "
        "goods), or across all inventories if none is named. Use this for "
        "questions like 'which items are expired' or 'what's expiring "
        "soon'. For just a number, use SimpleInventoryExpiryCountQuery "
        "instead."
    )

    _MAX_NAMED_ITEMS = 8

    @property
    def slot_schema(self) -> dict:
        return {
            vol.Required("status"): vol.In(["expired", "expiring_soon"]),
            vol.Optional("inventory"): intent.non_empty_string,
        }

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        hass = intent_obj.hass
        slots = self.async_validate_slots(intent_obj.slots)
        status = str(slots["status"]["value"])
        inventory = str(slots["inventory"]["value"]) if "inventory" in slots else None

        coordinators = get_coordinators(hass)
        if not coordinators:
            raise intent.IntentHandleError("No inventories configured")

        inventory_id: str | None = None
        if inventory is not None:
            try:
                inventory_id = await resolve_inventory_id(hass, None, inventory)
            except ServiceValidationError as err:
                raise intent.IntentHandleError(str(err)) from err

        coordinator = next(iter(coordinators.values()))
        expiring = await coordinator.async_get_items_expiring_soon(inventory_id)
        if status == "expired":
            matches = [entry for entry in expiring if entry["days_until_expiry"] < 0]
            status_phrase = "expired"
        else:
            matches = [entry for entry in expiring if entry["days_until_expiry"] >= 0]
            status_phrase = "expiring soon"

        count = len(matches)
        noun = "item" if count == 1 else "items"
        verb = "is" if count == 1 else "are"
        speech = f"{count} {noun} {verb} {status_phrase}"
        if inventory is not None:
            speech += f" in {inventory}"
        if matches:
            names = [str(entry.get("name", "unknown")) for entry in matches]
            shown = names[: self._MAX_NAMED_ITEMS]
            remainder = len(names) - len(shown)
            if remainder > 0:
                shown = [*shown, f"{remainder} more"]
            speech += f": {_format_name_list(shown)}"
        speech += "."

        response = intent_obj.create_response()
        response.async_set_speech(speech)
        return response


class SetItemQuantityIntent(intent.IntentHandler):
    """Set an item's quantity to an exact amount (not a relative add/remove)."""

    intent_type = INTENT_SET_ITEM_QUANTITY
    description = (
        "Set an item's quantity to an exact amount in a household "
        "inventory (e.g. freezer, dry storage, disposable goods) -- for "
        "when the user just took a physical inventory count, not a "
        "relative add or remove. Requires the item name, the inventory "
        "name, and the new quantity. Does not create new items -- the "
        "item must already exist."
    )

    @property
    def slot_schema(self) -> dict:
        return {
            vol.Required("item"): intent.non_empty_string,
            vol.Required("inventory"): intent.non_empty_string,
            vol.Required("quantity"): vol.All(vol.Coerce(float), vol.Range(min=0)),
        }

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        hass = intent_obj.hass
        slots = self.async_validate_slots(intent_obj.slots)
        item = str(slots["item"]["value"])
        inventory = str(slots["inventory"]["value"])
        quantity = float(slots["quantity"]["value"])

        try:
            inventory_id = await resolve_inventory_id(hass, None, inventory)
            coordinator = get_coordinators(hass).get(inventory_id)
            if coordinator is None:
                raise ServiceValidationError(f"Inventory '{inventory}' is not currently loaded")
            resolved_item = await resolve_item_name(coordinator, inventory_id, item)
        except ServiceValidationError as err:
            raise intent.IntentHandleError(str(err)) from err

        try:
            await hass.services.async_call(
                DOMAIN,
                SERVICE_UPDATE_ITEM,
                {
                    "inventory_id": inventory_id,
                    "old_name": resolved_item,
                    "name": resolved_item,
                    "quantity": quantity,
                },
                blocking=True,
                context=intent_obj.context,
            )
        except ServiceValidationError as err:
            raise intent.IntentHandleError(str(err)) from err

        response = intent_obj.create_response()
        response.async_set_speech(f"Set {item} to {_format_amount(quantity)} in {inventory}.")
        return response
