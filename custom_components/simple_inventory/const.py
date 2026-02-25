from typing import Final

DOMAIN: Final = "simple_inventory"
STORAGE_KEY: Final = f"{DOMAIN}.storage"
STORAGE_VERSION: Final = 1

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

# Item Fields (for data structure), needs to match params constants in frontend
FIELD_AUTO_ADD_ENABLED: Final = "auto_add_enabled"
FIELD_AUTO_ADD_ID_TO_DESCRIPTION_ENABLED: Final = "auto_add_id_to_description_enabled"
FIELD_AUTO_ADD_TO_LIST_QUANTITY: Final = "auto_add_to_list_quantity"
FIELD_AMOUNT: Final = "amount"
FIELD_BARCODE: Final = "barcode"
FIELD_DESIRED_QUANTITY: Final = "desired_quantity"
FIELD_CATEGORY: Final = "category"
FIELD_DESCRIPTION: Final = "description"
FIELD_EVENT_TYPE: Final = "event_type"
FIELD_EXPIRY_ALERT_DAYS: Final = "expiry_alert_days"
FIELD_END_DATE: Final = "end_date"
FIELD_EXPIRY_DATE: Final = "expiry_date"
FIELD_FORMAT: Final = "format"
FIELD_FROM_LOCATION: Final = "from_location"
FIELD_ITEMS: Final = "items"
FIELD_LIMIT: Final = "limit"
FIELD_LOCATION: Final = "location"
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
DEFAULT_LOCATION: Final = ""
DEFAULT_PRICE: Final = 0

ANALYTICS_MIN_EVENTS: Final = 2


def compute_quantity_needed(quantity: float, threshold: float, desired: float) -> float:
    """Compute how many units are needed to reach the restock target.

    When desired_quantity > 0, the shortfall is desired - current.
    Otherwise falls back to the legacy formula: threshold - current + 1.
    """
    if desired > 0:
        return desired - quantity
    return threshold - quantity + 1


# HA events
EVENT_ITEM_ADDED_TO_LIST: Final = f"{DOMAIN}_item_added_to_list"
EVENT_ITEM_REMOVED_FROM_LIST: Final = f"{DOMAIN}_item_removed_from_list"
EVENT_ITEM_DEPLETED: Final = f"{DOMAIN}_item_depleted"
EVENT_ITEM_RESTOCKED: Final = f"{DOMAIN}_item_restocked"
EVENT_ITEM_ADDED: Final = f"{DOMAIN}_item_added"
EVENT_ITEM_REMOVED: Final = f"{DOMAIN}_item_removed"
EVENT_ITEM_QUANTITY_CHANGED: Final = f"{DOMAIN}_item_quantity_changed"

INVENTORY_CONFIG: Final = "config"
INVENTORY_ITEMS: Final = "items"
INVENTORY_NAME: Final = "name"
