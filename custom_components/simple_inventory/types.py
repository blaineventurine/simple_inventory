from typing import Any, NotRequired, TypedDict


class AddItemServiceData(TypedDict):
    """Type for add item service call data."""

    auto_add_enabled: NotRequired[bool]
    auto_add_id_to_description_enabled: NotRequired[bool]
    auto_add_to_list_quantity: NotRequired[int]
    category: NotRequired[str]
    description: NotRequired[str]
    expiry_alert_days: NotRequired[int]
    expiry_date: NotRequired[str]
    inventory_id: str
    location: NotRequired[str]
    name: str
    quantity: NotRequired[int]
    todo_list: NotRequired[str]
    unit: NotRequired[str]


class UpdateItemServiceData(TypedDict):
    """Type for update item service call data."""

    auto_add_enabled: NotRequired[bool]
    auto_add_id_to_description_enabled: NotRequired[bool]
    auto_add_to_list_quantity: NotRequired[int]
    category: NotRequired[str]
    description: NotRequired[str]
    expiry_alert_days: NotRequired[int]
    expiry_date: NotRequired[str]
    inventory_id: str
    location: NotRequired[str]
    name: str
    old_name: str
    quantity: NotRequired[int]
    todo_list: NotRequired[str]
    unit: NotRequired[str]


class RemoveItemServiceData(TypedDict):
    """Type for remove item service call data."""

    inventory_id: str
    name: str


class GetItemsServiceData(TypedDict, total=False):
    """Type for get items service call data.

    Either inventory_id or inventory_name must be provided, but not both.
    """

    inventory_id: str
    inventory_name: str


class GetAllItemsServiceData(TypedDict, total=False):
    """Type for get items from all inventories service call data."""

    pass


class InventoryItem(TypedDict, total=False):
    """Type definition for inventory item data."""

    auto_add_enabled: bool
    auto_add_id_to_description_enabled: bool
    auto_add_to_list_quantity: int
    category: str
    description: str
    expiry_alert_days: int
    expiry_date: str
    location: str
    name: str
    quantity: int
    todo_list: str
    unit: str


class InventoryData(TypedDict):
    """Type definition for the main inventory data structure."""

    inventories: dict[str, dict[str, Any]]
    config: NotRequired[dict[str, Any]]  # Optional field
