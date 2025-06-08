from typing import Final

# Core Integration
DOMAIN: Final = "simple_inventory"
STORAGE_KEY: Final = f"{DOMAIN}.storage"
STORAGE_VERSION: Final = 1

# Services
SERVICE_ADD_ITEM: Final = "add_item"
SERVICE_REMOVE_ITEM: Final = "remove_item"
SERVICE_INCREMENT_ITEM: Final = "increment_item"
SERVICE_DECREMENT_ITEM: Final = "decrement_item"
SERVICE_UPDATE_ITEM: Final = "update_item"
SERVICE_UPDATE_ITEM_SETTINGS: Final = "update_item_settings"

# Service Parameters
PARAM_INVENTORY_ID: Final = "inventory_id"
PARAM_NAME: Final = "name"
PARAM_OLD_NAME: Final = "old_name"
PARAM_QUANTITY: Final = "quantity"
PARAM_UNIT: Final = "unit"
PARAM_CATEGORY: Final = "category"
PARAM_EXPIRY_DATE: Final = "expiry_date"
PARAM_AUTO_ADD_ENABLED: Final = "auto_add_enabled"
PARAM_THRESHOLD: Final = "threshold"
PARAM_TODO_LIST: Final = "todo_list"
PARAM_AMOUNT: Final = "amount"

# Item Fields (for data structure)
FIELD_ITEMS: Final = "items"
FIELD_NAME: Final = "name"
FIELD_QUANTITY: Final = "quantity"
FIELD_UNIT: Final = "unit"
FIELD_CATEGORY: Final = "category"
FIELD_EXPIRY_DATE: Final = "expiry_date"
FIELD_AUTO_ADD_ENABLED: Final = "auto_add_enabled"
FIELD_THRESHOLD: Final = "threshold"
FIELD_TODO_LIST: Final = "todo_list"

# Default Values
DEFAULT_QUANTITY: Final = 1
DEFAULT_THRESHOLD: Final = 0
DEFAULT_UNIT: Final = ""
DEFAULT_CATEGORY: Final = ""
DEFAULT_EXPIRY_DATE: Final = ""
DEFAULT_TODO_LIST: Final = ""
DEFAULT_AUTO_ADD_ENABLED: Final = False

# Inventory Structure Keys
INVENTORY_ITEMS: Final = "items"
INVENTORY_CONFIG: Final = "config"
INVENTORY_NAME: Final = "name"

# Entity Attributes
ATTR_ITEMS: Final = "items"
ATTR_INVENTORY_ID: Final = "inventory_id"
ATTR_FRIENDLY_NAME: Final = "friendly_name"
ATTR_UNIQUE_ID: Final = "unique_id"

# File Storage
STORAGE_FILE_SUFFIX: Final = "inventories.json"

# Error Messages
ERROR_INVENTORY_NOT_FOUND: Final = "Inventory not found"
ERROR_ITEM_NOT_FOUND: Final = "Item not found"
ERROR_INVALID_QUANTITY: Final = "Invalid quantity"
ERROR_INVALID_THRESHOLD: Final = "Invalid threshold"
ERROR_MISSING_NAME: Final = "Item name is required"
ERROR_MISSING_INVENTORY_ID: Final = "Inventory ID is required"

# Success Messages
SUCCESS_ITEM_ADDED: Final = "Item added successfully"
SUCCESS_ITEM_UPDATED: Final = "Item updated successfully"
SUCCESS_ITEM_REMOVED: Final = "Item removed successfully"
SUCCESS_QUANTITY_UPDATED: Final = "Quantity updated successfully"
