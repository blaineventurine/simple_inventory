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

import logging
import re
from collections.abc import Iterable
from typing import Any

import voluptuous as vol
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import intent
from homeassistant.util import language as language_util

from .const import (
    DOMAIN,
    FIELD_AMOUNT,
    FIELD_BATCHES,
    FIELD_FROM_LOCATION,
    FIELD_LOCATION,
    FIELD_NAME,
    FIELD_QUANTITY,
    FIELD_STOCKED_LOCATIONS,
    FIELD_TO_LOCATION,
    SERVICE_DECREMENT_ITEM,
    SERVICE_INCREMENT_ITEM,
    SERVICE_TRANSFER_ITEM,
    SERVICE_UPDATE_ITEM,
    is_out_of_stock,
    match_key,
    partition_expiry,
)
from .coordinator import SimpleInventoryCoordinator
from .data import get_coordinators, get_hub
from .entries import enabled_inventory_entries, entry_display_name, inventory_display_name
from .hub import InventoryHub
from .services.resolvers import (
    exact_inventory_id,
    inventory_not_loaded_error,
    match_names,
    resolve_inventory_id,
    resolve_item_name,
)
from .speech import Speech

_LOGGER = logging.getLogger(__name__)

INTENT_REMOVE_ITEM = "SimpleInventoryRemoveItem"
INTENT_ADD_ITEM = "SimpleInventoryAddItem"
INTENT_QUERY_ITEM = "SimpleInventoryQueryItem"
INTENT_EXPIRY_COUNT_QUERY = "SimpleInventoryExpiryCountQuery"
INTENT_LOW_STOCK_COUNT_QUERY = "SimpleInventoryLowStockCountQuery"
INTENT_EXPIRY_LIST_QUERY = "SimpleInventoryExpiryListQuery"
INTENT_SET_ITEM_QUANTITY = "SimpleInventorySetItemQuantity"
INTENT_TRANSFER_ITEM = "SimpleInventoryTransferItem"
INTENT_FIND_ITEM = "SimpleInventoryFindItem"
INTENT_LOW_STOCK_LIST_QUERY = "SimpleInventoryLowStockListQuery"


def async_register_intents(hass: HomeAssistant) -> None:
    """Register all Simple Inventory intents. Idempotent; call once per hass."""
    for handler in INTENT_HANDLERS:
        intent.async_register(hass, handler())


def async_unregister_intents(hass: HomeAssistant) -> None:
    """Remove all Simple Inventory intents."""
    for intent_type in INTENT_TYPES:
        intent.async_remove(hass, intent_type)


class _Refusal(Exception):
    """A user-facing refusal, spoken in the conversation's language; nothing has changed.

    Either one of the speech sentences (key + placeholders) or a service error, whose
    translated message is rendered the way Home Assistant renders it.
    """

    def __init__(
        self, key: str, error: HomeAssistantError | None = None, **placeholders: str
    ) -> None:
        super().__init__(key)
        self.key = key
        self.error = error
        self.placeholders = placeholders

    @classmethod
    def from_error(cls, err: HomeAssistantError) -> _Refusal:
        return cls(err.translation_key or "", err)

    def render(self, speech: Speech) -> str:
        if self.error is not None:
            return speech.error(self.error)
        return speech(self.key, **self.placeholders)


class _InventoryIntentHandler(intent.IntentHandler):
    """Speaks in the intent's language and answers a refusal with a spoken error response.

    Raising intent.IntentHandleError instead would lose the message: Home Assistant's
    default conversation agent replaces it with its generic "An unexpected error
    occurred". LLM tools get the same response, so they see the message too.
    """

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        speech = await Speech.async_load(intent_obj.hass, intent_obj.language)
        try:
            return await self._async_handle(intent_obj, speech)
        except _Refusal as refusal:
            response = intent_obj.create_response()
            response.async_set_error(
                intent.IntentResponseErrorCode.FAILED_TO_HANDLE, refusal.render(speech)
            )
            return response

    async def _async_handle(
        self, intent_obj: intent.Intent, speech: Speech
    ) -> intent.IntentResponse:
        raise NotImplementedError


def _distinct_items(entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse per-batch expiry entries to one per item, keeping the first (most urgent)."""
    seen: dict[tuple[Any, Any], dict[str, Any]] = {}
    for entry in entries:
        seen.setdefault((entry.get("inventory_id"), entry.get(FIELD_NAME)), entry)
    return list(seen.values())


def _named_list(speech: Speech, names: list[str], limit: int) -> str:
    """The first *limit* names joined for speech, then 'N more' for the rest."""
    shown = names[:limit]
    if len(names) > limit:
        shown.append(speech.count("speech_more", len(names) - limit))
    return speech.and_list(shown)


def _location_breakdown(speech: Speech, item: dict[str, Any]) -> str:
    """'2 in Fridge, 1 in Garage[, 1 unassigned]' when stock spans several locations, else ''."""
    locations: list[str] = item.get(FIELD_STOCKED_LOCATIONS) or []
    if len(locations) <= 1:
        return ""
    totals = dict.fromkeys(locations, 0.0)
    unassigned = 0.0
    for batch in item.get(FIELD_BATCHES) or []:
        quantity = float(batch.get(FIELD_QUANTITY) or 0)
        if batch.get(FIELD_LOCATION) in totals:
            totals[batch[FIELD_LOCATION]] += quantity
        else:
            unassigned += quantity
    parts = [
        speech("speech_amount_at_location", amount=speech.amount(qty), location=loc)
        for loc, qty in totals.items()
    ]
    if unassigned > 0:
        parts.append(speech("speech_amount_unassigned", amount=speech.amount(unassigned)))
    return ", ".join(parts)


def _item_locations(item: dict[str, Any]) -> list[str]:
    """Where the item's stock is (its batches' locations), else its own locations."""
    return list(item.get(FIELD_STOCKED_LOCATIONS) or item.get("locations") or [])


# Per language: the word putting an item "in" an inventory, and the articles that may
# precede the inventory's name.
_SCOPE_WORDS: dict[str, tuple[str, str]] = {
    "en": ("in", r"the\s+"),
    "es": ("en", r"(?:el|la|los|las)\s+"),
    "fr": ("dans", r"(?:(?:le|la|les)\s+|l['’])"),
    "sl": ("v", ""),
}


def _with_scope_split_off(
    hass: HomeAssistant, language: str, slots: dict[str, Any]
) -> dict[str, Any]:
    """Move '… in [the] <inventory>' from the item slot to the inventory slot.

    hassil prefers parses with fewer wildcards, so "do we have milk in the kitchen" fills
    only the item slot. Split when the words after the last 'in' (without an article)
    name an inventory exactly; otherwise keep the slots as they are.
    """
    matched = language_util.matches(language, list(_SCOPE_WORDS))
    if "inventory" in slots or not matched:
        return slots
    word, article = _SCOPE_WORDS[matched[0]]
    spoken = str(slots["item"]["value"])
    for separator in reversed(list(re.finditer(rf"\s+{word}\s+", spoken, re.IGNORECASE))):
        item = spoken[: separator.start()].strip()
        tail = spoken[separator.end() :].strip()
        stripped = re.sub(rf"^{article}", "", tail, flags=re.IGNORECASE)
        for inventory in dict.fromkeys((tail, stripped)):
            if item and exact_inventory_id(hass, inventory):
                return {**slots, "item": {"value": item}, "inventory": {"value": inventory}}
    return slots


async def _async_resolve_item(
    hass: HomeAssistant, inventory: str, item: str
) -> tuple[str, SimpleInventoryCoordinator, str]:
    """Resolve spoken inventory/item names to (inventory_id, coordinator, stored item name)."""
    try:
        inventory_id = await resolve_inventory_id(hass, None, inventory)
        coordinator = get_coordinators(hass).get(inventory_id)
        if coordinator is None:
            raise inventory_not_loaded_error(hass, inventory_id, inventory)
        resolved_item = await resolve_item_name(coordinator, inventory_id, item)
    except ServiceValidationError as err:
        raise _Refusal.from_error(err) from err
    return inventory_id, coordinator, resolved_item


async def _async_call_inventory_service(
    hass: HomeAssistant,
    service: str,
    data: dict[str, Any],
    context: Context,
    failure: _Refusal,
) -> None:
    """Call a mutating service; turn any failure into a speakable intent error."""
    try:
        await hass.services.async_call(DOMAIN, service, data, blocking=True, context=context)
    except ServiceValidationError as err:
        raise _Refusal.from_error(err) from err
    except HomeAssistantError as err:
        _LOGGER.exception("Voice/AI %s failed: %s", service, data)
        raise failure from err


async def _async_location_candidates(
    coordinator: SimpleInventoryCoordinator, inventory_id: str, location: str
) -> list[str]:
    """Existing location names of the inventory matching a spoken location (sorted)."""
    return match_names(location, await coordinator.async_list_location_names(inventory_id))


def _ambiguous_location(inventory: str, candidates: list[str]) -> _Refusal:
    return _Refusal(
        "speech_ambiguous_location", inventory=inventory, locations=", ".join(candidates)
    )


def _unknown_location(inventory: str, location: str) -> _Refusal:
    return _Refusal("speech_unknown_location", inventory=inventory, location=location)


async def _async_resolve_location(
    coordinator: SimpleInventoryCoordinator, inventory_id: str, inventory: str, location: str
) -> str:
    """Resolve a spoken location to an existing stored location name of the inventory."""
    candidates = await _async_location_candidates(coordinator, inventory_id, location)
    if len(candidates) == 1:
        return candidates[0]
    if candidates:
        raise _ambiguous_location(inventory, candidates)
    raise _unknown_location(inventory, location)


_IN_SEPARATOR = re.compile(r"\s+in\s+", re.IGNORECASE)
_LEADING_THE = re.compile(r"^the\s+", re.IGNORECASE)


def _with_and_without_the(text: str) -> list[str]:
    """``text`` itself, then without a leading "the" (inventories may be named "The ...")."""
    stripped = _LEADING_THE.sub("", text)
    return [text, stripped] if stripped != text else [text]


async def _async_split_location(hass: HomeAssistant, spoken: str) -> tuple[str, list[str]] | None:
    """Split a spoken '<location> in [the] <inventory>' into (inventory, location candidates).

    hassil prefers parses with fewer wildcards, so "remove 2 milk from the fridge in the
    kitchen" always matches the location-less sentence with the whole tail in the
    inventory slot. Split only when the text isn't itself an inventory name, the right
    part names an inventory exactly and the left part matches at least one of its
    locations; the last " in " is tried first, and each name as spoken before without a
    leading "the". Otherwise None: the caller keeps the whole text.
    """
    if any(exact_inventory_id(hass, text) for text in _with_and_without_the(spoken.strip())):
        return None
    for separator in reversed(list(_IN_SEPARATOR.finditer(spoken))):
        location = spoken[: separator.start()].strip()
        for inventory in _with_and_without_the(spoken[separator.end() :].strip()):
            inventory_id = exact_inventory_id(hass, inventory)
            coordinator = get_coordinators(hass).get(inventory_id) if inventory_id else None
            if coordinator is None or inventory_id is None:
                continue
            candidates = await _async_location_candidates(coordinator, inventory_id, location)
            if candidates:
                return inventory, candidates
    return None


async def _async_current_quantity(
    coordinator: SimpleInventoryCoordinator, inventory_id: str, item: str
) -> float | None:
    """Best-effort post-change quantity lookup by the stored item name."""
    try:
        item_data = await coordinator.async_get_item(inventory_id, item)
    except HomeAssistantError:
        return None
    if not item_data:
        return None
    return float(item_data.get(FIELD_QUANTITY, 0))


class _BaseQuantityIntent(_InventoryIntentHandler):
    """Shared slot parsing + service dispatch for add/remove item intents."""

    _service: str
    _failure_key: str

    @property
    def slot_schema(self) -> dict:
        return {
            vol.Required("item"): intent.non_empty_string,
            vol.Required("inventory"): intent.non_empty_string,
            vol.Optional("quantity"): vol.All(vol.Coerce(float), vol.Range(min=0.001)),
            vol.Optional(
                "location",
                description=(
                    "Storage spot inside the inventory (e.g. Fridge, Garage). "
                    "Only set it when the user names where the stock is."
                ),
            ): intent.non_empty_string,
        }

    async def _async_handle(
        self, intent_obj: intent.Intent, speech: Speech
    ) -> intent.IntentResponse:
        hass = intent_obj.hass
        slots = self.async_validate_slots(intent_obj.slots)
        item = str(slots["item"]["value"])
        inventory = str(slots["inventory"]["value"])
        amount = float(slots.get("quantity", {}).get("value", 1))
        data: dict[str, Any] = {FIELD_AMOUNT: amount}
        candidates: list[str] = []
        split = None if "location" in slots else await _async_split_location(hass, inventory)
        if split is not None:
            inventory, candidates = split
        inventory_id, coordinator, resolved_item = await _async_resolve_item(hass, inventory, item)
        if "location" in slots:
            spoken_location = str(slots["location"]["value"])
            candidates = await _async_location_candidates(
                coordinator, inventory_id, spoken_location
            )
            if not candidates:
                raise _unknown_location(inventory, spoken_location)
        if len(candidates) == 1:
            data[FIELD_LOCATION] = candidates[0]
        elif candidates:
            data[FIELD_LOCATION] = await self._async_pick_location(
                speech, coordinator, inventory_id, inventory, resolved_item, candidates
            )
        await _async_call_inventory_service(
            hass,
            self._service,
            {"inventory_id": inventory_id, FIELD_NAME: resolved_item, **data},
            intent_obj.context,
            _Refusal(self._failure_key, item=item, inventory=inventory),
        )

        remaining = await _async_current_quantity(coordinator, inventory_id, resolved_item)
        response = intent_obj.create_response()
        response.async_set_speech(self._speech(speech, item, inventory, amount, remaining))
        return response

    async def _async_pick_location(
        self,
        speech: Speech,
        coordinator: SimpleInventoryCoordinator,
        inventory_id: str,
        inventory: str,
        item: str,
        candidates: list[str],
    ) -> str:
        """Choose among several matching locations; by default ask which one was meant."""
        raise _ambiguous_location(inventory, candidates)

    def _speech(
        self, speech: Speech, item: str, inventory: str, amount: float, remaining: float | None
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
        "inventory name; quantity defaults to 1 if not specified. "
        "An optional location names the storage spot inside the inventory."
    )
    _service = SERVICE_DECREMENT_ITEM
    _failure_key = "speech_remove_failed"

    async def _async_pick_location(
        self,
        speech: Speech,
        coordinator: SimpleInventoryCoordinator,
        inventory_id: str,
        inventory: str,
        item: str,
        candidates: list[str],
    ) -> str:
        """Narrow several matching locations to those where the item has stock."""
        item_data = await coordinator.async_get_item(inventory_id, item) or {}
        stocked = {match_key(str(name)) for name in item_data.get(FIELD_STOCKED_LOCATIONS) or []}
        narrowed = [name for name in candidates if match_key(name) in stocked]
        if len(narrowed) == 1:
            return narrowed[0]
        if narrowed:
            raise _ambiguous_location(inventory, narrowed)
        raise _Refusal(
            "speech_not_at_locations",
            item=item,
            locations=speech.or_list(candidates),
            inventory=inventory,
        )

    def _speech(
        self, speech: Speech, item: str, inventory: str, amount: float, remaining: float | None
    ) -> str:
        said = {"amount": speech.amount(amount), "item": item, "inventory": inventory}
        if remaining is None:
            return speech("speech_removed", **said)
        if remaining <= 0:
            return speech("speech_removed_none_left", **said)
        return speech("speech_removed_left", remaining=speech.amount(remaining), **said)


class AddItemIntent(_BaseQuantityIntent):
    """Add/restock a quantity of an item to an inventory."""

    intent_type = INTENT_ADD_ITEM
    description = (
        "Add or restock a quantity of an item to a household inventory "
        "(e.g. freezer, dry storage, disposable goods). Use this when the "
        "user says they bought, restocked, or want to add stock of an item "
        "that is already tracked. Requires the item name and the inventory "
        "name; quantity defaults to 1 if not specified. Does not create new "
        "items -- the item must already exist in the inventory. "
        "An optional location names the storage spot inside the inventory."
    )
    _service = SERVICE_INCREMENT_ITEM
    _failure_key = "speech_add_failed"

    def _speech(
        self, speech: Speech, item: str, inventory: str, amount: float, remaining: float | None
    ) -> str:
        said = {"amount": speech.amount(amount), "item": item, "inventory": inventory}
        if remaining is None:
            return speech("speech_added", **said)
        return speech("speech_added_now_at", remaining=speech.amount(remaining), **said)


class QueryItemIntent(_InventoryIntentHandler):
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

    async def _async_handle(
        self, intent_obj: intent.Intent, speech: Speech
    ) -> intent.IntentResponse:
        hass = intent_obj.hass
        slots = self.async_validate_slots(intent_obj.slots)
        item = str(slots["item"]["value"])
        inventory = str(slots["inventory"]["value"])

        inventory_id, coordinator, resolved_item = await _async_resolve_item(hass, inventory, item)
        # Speak the stored names: the spoken ones may be misheard or fuzzily matched.
        inventory_name = inventory_display_name(hass, inventory_id)

        item_data = await coordinator.async_get_item(inventory_id, resolved_item)
        response = intent_obj.create_response()
        if not item_data:
            response.async_set_speech(
                speech("speech_item_missing", item=resolved_item, inventory=inventory_name)
            )
            return response
        said = {
            "inventory": inventory_name,
            "amount": speech.amount(float(item_data.get(FIELD_QUANTITY, 0))),
            "item": resolved_item,
        }
        breakdown = _location_breakdown(speech, item_data)
        response.async_set_speech(
            speech("speech_item_quantity_breakdown", breakdown=breakdown, **said)
            if breakdown
            else speech("speech_item_quantity", **said)
        )
        return response


# Spoken status → index into `partition_expiry`'s `(expired, expiring_soon)`.
_EXPIRY_SIDES: dict[str, int] = {"expired": 0, "expiring_soon": 1}


async def _async_scope(
    hass: HomeAssistant, slots: dict[str, Any]
) -> tuple[str | None, str | None, InventoryHub]:
    """Resolve the optional spoken inventory to (stored name, inventory_id, hub).

    No inventory slot means "across all inventories" (both None).
    """
    try:
        hub = get_hub(hass)
        if hub is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="no_inventories_configured"
            )
        if "inventory" not in slots:
            return None, None, hub
        inventory_id = await resolve_inventory_id(hass, None, str(slots["inventory"]["value"]))
    except ServiceValidationError as err:
        raise _Refusal.from_error(err) from err
    return inventory_display_name(hass, inventory_id), inventory_id, hub


def _count_sentence(speech: Speech, key: str, count: int, inventory: str | None) -> str:
    """The counted sentence *key* ('N items are …'), its '…_in' form when scoped."""
    if inventory is None:
        return speech.count(key, count)
    return speech.count(f"{key}_in", count, inventory=inventory)


class _ScopedQueryIntent(_InventoryIntentHandler):
    """Optional inventory slot (all inventories when absent) -> one query -> one sentence."""

    async def _async_handle(
        self, intent_obj: intent.Intent, speech: Speech
    ) -> intent.IntentResponse:
        slots = self.async_validate_slots(intent_obj.slots)
        inventory, inventory_id, hub = await _async_scope(intent_obj.hass, slots)
        response = intent_obj.create_response()
        response.async_set_speech(
            await self._async_speech(speech, hub, inventory_id, inventory, slots)
        )
        return response

    async def _async_speech(
        self,
        speech: Speech,
        hub: InventoryHub,
        inventory_id: str | None,
        inventory: str | None,
        slots: dict[str, Any],
    ) -> str:
        raise NotImplementedError


class _ExpiryQueryIntent(_ScopedQueryIntent):
    """Scoped query over items that are expired or expiring soon (``status`` slot)."""

    @property
    def slot_schema(self) -> dict:
        return {
            vol.Required("status"): vol.In(list(_EXPIRY_SIDES)),
            vol.Optional("inventory"): intent.non_empty_string,
        }

    @staticmethod
    async def _async_matches(
        hub: InventoryHub, inventory_id: str | None, status: str
    ) -> list[dict[str, Any]]:
        """One entry per item with the *status*, most urgent first."""
        expiring = await hub.async_items_expiring_soon(inventory_id)
        return _distinct_items(partition_expiry(expiring)[_EXPIRY_SIDES[status]])


class ExpiryCountIntent(_ExpiryQueryIntent):
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

    async def _async_speech(
        self,
        speech: Speech,
        hub: InventoryHub,
        inventory_id: str | None,
        inventory: str | None,
        slots: dict[str, Any],
    ) -> str:
        status = str(slots["status"]["value"])
        matches = await self._async_matches(hub, inventory_id, status)
        return _count_sentence(speech, f"speech_count_{status}", len(matches), inventory) + "."


class LowStockCountIntent(_ScopedQueryIntent):
    """Count how many items are low on stock (at or below their restock threshold)."""

    intent_type = INTENT_LOW_STOCK_COUNT_QUERY
    description = (
        "Count how many items are low on stock (at or below their restock "
        "threshold) in a household inventory (e.g. freezer, dry storage, "
        "disposable goods), or across all inventories if none is named, and "
        "how many of them are out of stock. Use this for questions like 'how "
        "many items are low on stock'. To name the items, use "
        "SimpleInventoryLowStockListQuery; for a specific item's quantity, use "
        "SimpleInventoryQueryItem."
    )

    @property
    def slot_schema(self) -> dict:
        return {
            vol.Optional("inventory"): intent.non_empty_string,
        }

    async def _async_speech(
        self,
        speech: Speech,
        hub: InventoryHub,
        inventory_id: str | None,
        inventory: str | None,
        slots: dict[str, Any],
    ) -> str:
        low_stock = await hub.async_low_stock_items(inventory_id)
        sentence = _count_sentence(speech, "speech_count_low_stock", len(low_stock), inventory)
        out_of_stock = sum(1 for item in low_stock if is_out_of_stock(item))
        if out_of_stock:
            sentence += ", " + speech.count("speech_out_of_stock_among", out_of_stock)
        return sentence + "."


class LowStockListIntent(_ScopedQueryIntent):
    """Name the items that are low on stock, marking the ones that are out of stock."""

    intent_type = INTENT_LOW_STOCK_LIST_QUERY
    description = (
        "List by name which items are low on stock (at or below their restock "
        "threshold) in a household inventory, or across all inventories if none "
        "is named; items with none left are marked out of stock. Use this for "
        "questions like 'what's running low' or 'what are we low on'. For just a "
        "number, use SimpleInventoryLowStockCountQuery instead."
    )

    _MAX_NAMED_ITEMS = 8

    @property
    def slot_schema(self) -> dict:
        return {
            vol.Optional("inventory"): intent.non_empty_string,
        }

    async def _async_speech(
        self,
        speech: Speech,
        hub: InventoryHub,
        inventory_id: str | None,
        inventory: str | None,
        slots: dict[str, Any],
    ) -> str:
        low_stock = sorted(
            await hub.async_low_stock_items(inventory_id),
            key=lambda item: str(item[FIELD_NAME]).casefold(),
        )
        sentence = _count_sentence(speech, "speech_count_low_stock", len(low_stock), inventory)
        if low_stock:
            names = [
                (
                    speech("speech_out_of_stock_item", item=item[FIELD_NAME])
                    if is_out_of_stock(item)
                    else str(item[FIELD_NAME])
                )
                for item in low_stock
            ]
            sentence += f": {_named_list(speech, names, self._MAX_NAMED_ITEMS)}"
        return sentence + "."


class ExpiryListIntent(_ExpiryQueryIntent):
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

    async def _async_speech(
        self,
        speech: Speech,
        hub: InventoryHub,
        inventory_id: str | None,
        inventory: str | None,
        slots: dict[str, Any],
    ) -> str:
        status = str(slots["status"]["value"])
        matches = await self._async_matches(hub, inventory_id, status)
        sentence = _count_sentence(speech, f"speech_count_{status}", len(matches), inventory)
        if matches:
            names = [str(entry[FIELD_NAME]) for entry in matches]
            sentence += f": {_named_list(speech, names, self._MAX_NAMED_ITEMS)}"
        return sentence + "."


class FindItemIntent(_InventoryIntentHandler):
    """Find an item by name or alias across inventories: how many, in which inventory, where."""

    intent_type = INTENT_FIND_ITEM
    description = (
        "Find an item by name or alias in every household inventory (or only in one, if "
        "named) and report how many there are, in which inventory and where they are kept. "
        "Use this when the user does not say which inventory, e.g. 'how many batteries do "
        "we have', 'do we have any butter' or 'where are the batteries'. Does not change "
        "any quantities."
    )

    _MAX_NAMED_ITEMS = 5
    _SEARCH_LIMIT = 50

    @property
    def slot_schema(self) -> dict:
        return {
            vol.Required("item"): intent.non_empty_string,
            vol.Optional("inventory"): intent.non_empty_string,
        }

    async def _async_handle(
        self, intent_obj: intent.Intent, speech: Speech
    ) -> intent.IntentResponse:
        hass = intent_obj.hass
        slots = _with_scope_split_off(
            hass, intent_obj.language, self.async_validate_slots(intent_obj.slots)
        )
        item = str(slots["item"]["value"])
        inventory, inventory_id, hub = await _async_scope(hass, slots)
        if inventory_id is None:
            names = {
                entry.entry_id: entry_display_name(entry)
                for entry in enabled_inventory_entries(hass)
            }
        else:
            names = {inventory_id: str(inventory)}

        found = await hub.async_search(item, names, self._SEARCH_LIMIT)
        matches = [entry for entry in found["items"] if entry["matched"] in ("name", "alias")]
        key = match_key(item)
        exact = [
            entry
            for entry in matches
            if match_key(str(entry[FIELD_NAME])) == key
            or key in {match_key(str(alias)) for alias in entry.get("aliases") or []}
        ]
        matches = exact or matches

        response = intent_obj.create_response()
        response.async_set_speech(self._speech(speech, item, inventory, matches))
        return response

    def _speech(
        self, speech: Speech, item: str, inventory: str | None, matches: list[dict[str, Any]]
    ) -> str:
        if not matches:
            if inventory is None:
                return speech("speech_item_missing_anywhere", item=item)
            return speech("speech_item_missing", item=item, inventory=inventory)
        if len(matches) == 1:
            entry = matches[0]
            said = {
                "inventory": entry["inventory_name"],
                "amount": speech.amount(float(entry.get(FIELD_QUANTITY, 0))),
                "item": entry[FIELD_NAME],
            }
            if locations := _item_locations(entry):
                return speech("speech_item_quantity_at", locations=", ".join(locations), **said)
            return speech("speech_item_quantity", **said)
        parts = []
        for entry in matches:
            said = {
                "amount": speech.amount(float(entry.get(FIELD_QUANTITY, 0))),
                "item": entry[FIELD_NAME],
                "inventory": entry["inventory_name"],
            }
            if locations := _item_locations(entry):
                parts.append(speech("speech_find_match_at", locations=", ".join(locations), **said))
            else:
                parts.append(speech("speech_find_match", **said))
        return speech.count(
            "speech_find_matches",
            len(matches),
            item=item,
            matches=_named_list(speech, parts, self._MAX_NAMED_ITEMS),
        )


class SetItemQuantityIntent(_InventoryIntentHandler):
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

    async def _async_handle(
        self, intent_obj: intent.Intent, speech: Speech
    ) -> intent.IntentResponse:
        hass = intent_obj.hass
        slots = self.async_validate_slots(intent_obj.slots)
        item = str(slots["item"]["value"])
        inventory = str(slots["inventory"]["value"])
        quantity = float(slots["quantity"]["value"])

        inventory_id, _coordinator, resolved_item = await _async_resolve_item(hass, inventory, item)
        await _async_call_inventory_service(
            hass,
            SERVICE_UPDATE_ITEM,
            {
                "inventory_id": inventory_id,
                "old_name": resolved_item,
                FIELD_NAME: resolved_item,
                FIELD_QUANTITY: quantity,
            },
            intent_obj.context,
            _Refusal("speech_update_failed", item=item, inventory=inventory),
        )

        response = intent_obj.create_response()
        response.async_set_speech(
            speech(
                "speech_set_quantity",
                item=item,
                quantity=speech.amount(quantity),
                inventory=inventory,
            )
        )
        return response


class TransferItemIntent(_InventoryIntentHandler):
    """Move stock of an item between two existing locations of one inventory."""

    intent_type = INTENT_TRANSFER_ITEM
    description = (
        "Move stock of an item from one storage spot to another inside the same "
        "household inventory (e.g. from the Fridge to the Garage fridge). Requires "
        "the item name, the inventory name and the destination location; both "
        "locations must already exist in the inventory. Without a from_location the "
        "soonest-expiring stock not already at the destination is moved; without a "
        "quantity everything at the source is moved."
    )

    @property
    def slot_schema(self) -> dict:
        return {
            vol.Required("item"): intent.non_empty_string,
            vol.Required("inventory"): intent.non_empty_string,
            vol.Required(
                "to_location",
                description=(
                    "Existing storage spot inside the inventory to move the stock to "
                    "(e.g. Garage)."
                ),
            ): intent.non_empty_string,
            vol.Optional(
                "from_location",
                description=(
                    "Existing storage spot the stock is taken from. "
                    "Only set it when the user names where the stock is now."
                ),
            ): intent.non_empty_string,
            vol.Optional("quantity"): vol.All(vol.Coerce(float), vol.Range(min=0.001)),
        }

    async def _async_handle(
        self, intent_obj: intent.Intent, speech: Speech
    ) -> intent.IntentResponse:
        hass = intent_obj.hass
        slots = self.async_validate_slots(intent_obj.slots)
        item = str(slots["item"]["value"])
        inventory = str(slots["inventory"]["value"])
        inventory_id, coordinator, resolved_item = await _async_resolve_item(hass, inventory, item)
        to_location = await _async_resolve_location(
            coordinator, inventory_id, inventory, str(slots["to_location"]["value"])
        )
        data: dict[str, Any] = {
            "inventory_id": inventory_id,
            FIELD_NAME: resolved_item,
            FIELD_TO_LOCATION: to_location,
        }
        what = item
        if "quantity" in slots:
            data[FIELD_AMOUNT] = float(slots["quantity"]["value"])
            what = f"{speech.amount(data[FIELD_AMOUNT])} {item}"
        if "from_location" in slots:
            data[FIELD_FROM_LOCATION] = await _async_resolve_location(
                coordinator, inventory_id, inventory, str(slots["from_location"]["value"])
            )

        await _async_call_inventory_service(
            hass,
            SERVICE_TRANSFER_ITEM,
            data,
            intent_obj.context,
            _Refusal("speech_move_failed", item=item, inventory=inventory),
        )

        response = intent_obj.create_response()
        response.async_set_speech(
            speech(
                "speech_moved_from",
                what=what,
                from_location=data[FIELD_FROM_LOCATION],
                to_location=to_location,
            )
            if FIELD_FROM_LOCATION in data
            else speech("speech_moved", what=what, to_location=to_location)
        )
        return response


INTENT_HANDLERS: tuple[type[_InventoryIntentHandler], ...] = (
    RemoveItemIntent,
    AddItemIntent,
    QueryItemIntent,
    FindItemIntent,
    ExpiryCountIntent,
    LowStockCountIntent,
    LowStockListIntent,
    ExpiryListIntent,
    SetItemQuantityIntent,
    TransferItemIntent,
)
INTENT_TYPES = tuple(handler.intent_type for handler in INTENT_HANDLERS)
