from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final, TypeVar

DOMAIN: Final = "simple_inventory"
STORAGE_KEY: Final = f"{DOMAIN}.storage"
STORAGE_VERSION: Final = 1

# Frontend contract version reported by the `simple_inventory/get_info` WS command.
# Bump ONLY for breaking contract changes; additive changes go in FEATURES.
API_VERSION: Final = 4
# Optional capability strings; the card gates optional UI on these, never on version.
FEATURES: Final[tuple[str, ...]] = (
    "batches",
    "transfers",
    "item_icons",
    "item_images",
    "panel",
    "tile_images",
    "search",
    "overview",
)

# Config entry data keys and values (see entries.py for the helpers that read them)
CONF_NAME: Final = "name"
CONF_ICON: Final = "icon"
CONF_DESCRIPTION: Final = "description"
CONF_ENTRY_TYPE: Final = "entry_type"
# One-shot request on the first inventory entry: create the global entry during setup.
CONF_CREATE_GLOBAL: Final = "create_global"
ENTRY_TYPE_INVENTORY: Final = "inventory"
ENTRY_TYPE_GLOBAL: Final = "global"
DEFAULT_INVENTORY_ICON: Final = "mdi:package-variant"
GLOBAL_ENTRY_TITLE: Final = "All Items Expiring Soon"
GLOBAL_ENTRY_ICON: Final = "mdi:calendar-alert"
GLOBAL_ENTRY_DESCRIPTION: Final = "Tracks expiring items across all inventories"

CONF_SHOW_PANEL: Final = "show_panel"
CONF_PANEL_ADMIN_ONLY: Final = "panel_admin_only"

SERVICE_ADD_ITEM: Final = "add_item"
SERVICE_DECREMENT_ITEM: Final = "decrement_item"
SERVICE_INCREMENT_ITEM: Final = "increment_item"
SERVICE_REMOVE_ITEM: Final = "remove_item"
SERVICE_UPDATE_ITEM: Final = "update_item"
SERVICE_GET_ITEMS: Final = "get_items"
SERVICE_GET_ALL_ITEMS: Final = "get_items_from_all_inventories"
SERVICE_GET_INVENTORY_CONSUMPTION_RATES: Final = "get_inventory_consumption_rates"
SERVICE_GET_ITEM_CONSUMPTION_RATES: Final = "get_item_consumption_rates"
SERVICE_LOOKUP_BY_BARCODE: Final = "lookup_by_barcode"
SERVICE_LOOKUP_BARCODE_PRODUCT: Final = "lookup_barcode_product"
SERVICE_SCAN_BARCODE: Final = "scan_barcode"
SERVICE_UPDATE_BATCH: Final = "update_batch"
SERVICE_REMOVE_BATCH: Final = "remove_batch"
SERVICE_TRANSFER_ITEM: Final = "transfer_item"
SERVICE_SET_ITEM_IMAGE_FROM_BARCODE: Final = "set_item_image_from_barcode"
SERVICE_SET_ITEM_IMAGE_FROM_MEDIA: Final = "set_item_image_from_media"
SERVICE_CLEAR_ITEM_IMAGE: Final = "clear_item_image"
SERVICE_BACKUP_DATABASE: Final = "backup_database"
SERVICE_RESTORE_DATABASE: Final = "restore_database"
SERVICE_EXPORT: Final = "export"

# Item Fields (for data structure), needs to match params constants in frontend
FIELD_AUTO_ADD_ENABLED: Final = "auto_add_enabled"
FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED: Final = "auto_add_id_to_description_enabled"
FIELD_AUTO_ADD_TO_LIST_QUANTITY: Final = "auto_add_to_list_quantity"
FIELD_ALIASES: Final = "aliases"
FIELD_AMOUNT: Final = "amount"
FIELD_BARCODE: Final = "barcode"
FIELD_BARCODES: Final = "barcodes"
FIELD_CATEGORIES: Final = "categories"
FIELD_DESIRED_QUANTITY: Final = "desired_quantity"
FIELD_CATEGORY: Final = "category"
FIELD_DESCRIPTION: Final = "description"
FIELD_EVENT_TYPE: Final = "event_type"
FIELD_EXPIRY_ALERT_DAYS: Final = "expiry_alert_days"
FIELD_END_DATE: Final = "end_date"
FIELD_EXPIRY_DATE: Final = "expiry_date"
FIELD_ICON: Final = "icon"
FIELD_IMAGE: Final = "image"
FIELD_FORMAT: Final = "format"
FIELD_FROM_LOCATION: Final = "from_location"
FIELD_ITEMS: Final = "items"
FIELD_LIMIT: Final = "limit"
FIELD_LOCATION: Final = "location"
FIELD_LOCATIONS: Final = "locations"
FIELD_MERGE_STRATEGY: Final = "merge_strategy"
FIELD_NAME: Final = "name"
FIELD_PERIOD: Final = "period"
FIELD_QUANTITY: Final = "quantity"
FIELD_START_DATE: Final = "start_date"
FIELD_TODO_LIST: Final = "todo_list"
FIELD_TODO_QUANTITY_PLACEMENT: Final = "todo_quantity_placement"
FIELD_TO_LOCATION: Final = "to_location"
FIELD_PRICE: Final = "price"
FIELD_UNIT: Final = "unit"
FIELD_BATCHES: Final = "batches"
FIELD_BATCH_ID: Final = "batch_id"
FIELD_PURCHASED_AT: Final = "purchased_at"
FIELD_STOCKED_LOCATIONS: Final = "stocked_locations"
FIELD_UNIT_PRICE: Final = "unit_price"

DEFAULT_AUTO_ADD_ENABLED: Final = False
DEFAULT_AUTO_ADD_TO_LIST_QUANTITY: Final = 0
DEFAULT_DESIRED_QUANTITY: Final = 0
DEFAULT_CATEGORY: Final = ""
DEFAULT_EXPIRY_ALERT_DAYS: Final = 0
DEFAULT_EXPIRY_DATE: Final = ""
DEFAULT_QUANTITY: Final = 1
DEFAULT_TODO_LIST: Final = ""
DEFAULT_TODO_QUANTITY_PLACEMENT: Final = "name"
DEFAULT_UNIT: Final = ""
DEFAULT_ITEM_ICON: Final = ""
DEFAULT_LOCATION: Final = ""
DEFAULT_PRICE: Final = 0

ANALYTICS_MIN_EVENTS: Final = 2


QUANTITY_PRECISION: Final = 6


def round_quantity(value: float) -> float:
    """Round a stored quantity to QUANTITY_PRECISION decimals.

    Applied on every write so float drift (e.g. 0.1 + 0.2) never leaks into the
    database and depletion/threshold comparisons work on exact values.
    """
    rounded = round(float(value), QUANTITY_PRECISION)
    return 0.0 if rounded == 0 else rounded


def compute_quantity_needed(quantity: float, threshold: float, desired: float) -> float:
    """Compute how many units are needed to reach the restock target.

    When desired_quantity > 0, the shortfall is desired - current.
    Otherwise falls back to the legacy formula: threshold - current + 1.
    """
    if desired > 0:
        return desired - quantity
    return threshold - quantity + 1


def match_key(value: str) -> str:
    """The one case-insensitive comparison key for names and aliases: trimmed, casefolded.

    Unicode case folding, wider than SQLite's ASCII-only ``NOCASE``: "Čokolada" equals
    "čokolada" and "Straße" equals "STRASSE". The search SQL's ``casefold()`` agrees.
    """
    return value.strip().casefold()


def split_unique(value: str | None, *, case_sensitive: bool = False) -> list[str]:
    """Split a comma-separated string into trimmed, non-empty, de-duplicated values.

    First occurrence wins and caller order is kept. Locations, categories and aliases
    compare case-insensitively (as users and voice matching treat them); barcodes
    compare exactly.
    """
    result: list[str] = []
    seen: set[str] = set()
    for part in (value or "").split(","):
        cleaned = part.strip()
        key = cleaned if case_sensitive else match_key(cleaned)
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def is_out_of_stock(item: Mapping[str, Any]) -> bool:
    """True if `item`'s quantity is at or below zero."""
    return float(item.get(FIELD_QUANTITY, 0)) <= 0


def is_below_threshold(item: Mapping[str, Any]) -> bool:
    """True if `item`'s quantity is at or below its auto-add threshold.

    A threshold of 0 is the default for every item, so it only counts when auto-add is
    enabled ("add when empty"); otherwise every out-of-stock item would match.
    """
    threshold = float(item.get(FIELD_AUTO_ADD_TO_LIST_QUANTITY, DEFAULT_AUTO_ADD_TO_LIST_QUANTITY))
    if threshold <= 0 and not item.get(FIELD_AUTO_ADD_ENABLED, DEFAULT_AUTO_ADD_ENABLED):
        return False
    return float(item.get(FIELD_QUANTITY, 0)) <= threshold


# Overview attention sections, most urgent first; an item is listed in the first that applies.
ATTENTION_SECTIONS: Final = ("expired", "expiring_soon", "out_of_stock", "low_stock")


_ExpiryEntry = TypeVar("_ExpiryEntry", bound=Mapping[str, Any])


def partition_expiry(
    entries: Iterable[_ExpiryEntry],
) -> tuple[list[_ExpiryEntry], list[_ExpiryEntry]]:
    """Split expiry entries into ``(expired, expiring_soon)``, keeping their order."""
    expired: list[_ExpiryEntry] = []
    expiring_soon: list[_ExpiryEntry] = []
    for entry in entries:
        (expired if entry["days_until_expiry"] < 0 else expiring_soon).append(entry)
    return expired, expiring_soon


def expiry_icon(expiring_soon: Sequence[Mapping[str, Any]]) -> str:
    """Urgency icon for not-yet-expired entries sorted soonest first."""
    if not expiring_soon:
        return "mdi:calendar-check"
    most_urgent = expiring_soon[0]["days_until_expiry"]
    if most_urgent <= 1:
        return "mdi:calendar-alert"
    if most_urgent <= 3:
        return "mdi:calendar-clock"
    return "mdi:calendar-week"


# Refresh signals: the general one after any inventory change, plus a per-inventory one.
# Sensors listen to them and the `simple_inventory/subscribe` WS command forwards them.
EVENT_UPDATED: Final = f"{DOMAIN}_updated"


def updated_event(inventory_id: str | None) -> str:
    """The refresh signal for one inventory, or the general one for ``None``."""
    return f"{EVENT_UPDATED}_{inventory_id}" if inventory_id else EVENT_UPDATED


EVENT_ITEM_ADDED_TO_LIST: Final = f"{DOMAIN}_item_added_to_list"
EVENT_ITEM_REMOVED_FROM_LIST: Final = f"{DOMAIN}_item_removed_from_list"
EVENT_ITEM_DEPLETED: Final = f"{DOMAIN}_item_depleted"
EVENT_ITEM_RESTOCKED: Final = f"{DOMAIN}_item_restocked"
EVENT_ITEM_ADDED: Final = f"{DOMAIN}_item_added"
EVENT_ITEM_REMOVED: Final = f"{DOMAIN}_item_removed"
EVENT_ITEM_QUANTITY_CHANGED: Final = f"{DOMAIN}_item_quantity_changed"
EVENT_ITEM_TRANSFERRED: Final = f"{DOMAIN}_item_transferred"

INVENTORY_ITEMS: Final = "items"
INVENTORY_NAME: Final = "name"
