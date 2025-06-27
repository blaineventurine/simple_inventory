from typing import Any, NotRequired, TypedDict


class AddItemServiceData(TypedDict):
    """Type for add item service call data."""

    inventory_id: str
    name: str
    quantity: NotRequired[int]
    unit: NotRequired[str]
    category: NotRequired[str]
    expiry_date: NotRequired[str]
    auto_add_enabled: NotRequired[bool]
    auto_add_to_list_quantity: NotRequired[int]
    expiry_alert_days: NotRequired[int]
    todo_list: NotRequired[str]


class UpdateItemServiceData(TypedDict):
    """Type for update item service call data."""

    inventory_id: str
    old_name: str
    name: str
    quantity: NotRequired[int]
    unit: NotRequired[str]
    category: NotRequired[str]
    expiry_date: NotRequired[str]
    auto_add_enabled: NotRequired[bool]
    auto_add_to_list_quantity: NotRequired[int]
    expiry_alert_days: NotRequired[int]
    todo_list: NotRequired[str]


class RemoveItemServiceData(TypedDict):
    """Type for remove item service call data."""

    inventory_id: str
    name: str


class InventoryItem(TypedDict, total=False):
    """Type definition for inventory item data."""

    auto_add_enabled: bool
    auto_add_to_list_quantity: int
    category: str
    expiry_alert_days: int
    expiry_date: str
    name: str
    quantity: int
    todo_list: str
    unit: str


class InventoryData(TypedDict):
    """Type definition for the main inventory data structure."""

    inventories: dict[str, dict[str, Any]]
    config: NotRequired[dict[str, Any]]  # Optional field
