from typing import Final

DOMAIN: Final = "simple_inventory"
STORAGE_KEY: Final = f"{DOMAIN}.storage"
STORAGE_VERSION: Final = 1

SERVICE_ADD_ITEM: Final = "add_item"
SERVICE_DECREMENT_ITEM: Final = "decrement_item"
SERVICE_INCREMENT_ITEM: Final = "increment_item"
SERVICE_REMOVE_ITEM: Final = "remove_item"
SERVICE_UPDATE_ITEM: Final = "update_item"

# Item Fields (for data structure), needs to match params constants in frontend
FIELD_AUTO_ADD_ENABLED: Final = "auto_add_enabled"
FIELD_AUTO_ADD_TO_LIST_QUANTITY: Final = "auto_add_to_list_quantity"
FIELD_CATEGORY: Final = "category"
FIELD_EXPIRY_ALERT_DAYS: Final = "expiry_alert_days"
FIELD_EXPIRY_DATE: Final = "expiry_date"
FIELD_ITEMS: Final = "items"
FIELD_NAME: Final = "name"
FIELD_QUANTITY: Final = "quantity"
FIELD_TODO_LIST: Final = "todo_list"
FIELD_UNIT: Final = "unit"

DEFAULT_AUTO_ADD_ENABLED: Final = False
DEFAULT_AUTO_ADD_TO_LIST_QUANTITY: Final = 0
DEFAULT_CATEGORY: Final = ""
DEFAULT_EXPIRY_ALERT_DAYS: Final = 7
DEFAULT_EXPIRY_DATE: Final = ""
DEFAULT_QUANTITY: Final = 1
DEFAULT_TODO_LIST: Final = ""
DEFAULT_UNIT: Final = ""

INVENTORY_CONFIG: Final = "config"
INVENTORY_ITEMS: Final = "items"
INVENTORY_NAME: Final = "name"
