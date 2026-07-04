from __future__ import annotations

from typing import TYPE_CHECKING, Any, NotRequired, TypedDict

if TYPE_CHECKING:
    from .coordinator import SimpleInventoryCoordinator
    from .services import ServiceHandler
    from .storage.repository import InventoryRepository
    from .todo_manager import TodoManager


class AddItemServiceData(TypedDict):
    """Type for add item service call data."""

    aliases: NotRequired[str]
    auto_add_enabled: NotRequired[bool]
    auto_add_id_to_description_enabled: NotRequired[bool]
    auto_add_to_list_quantity: NotRequired[float]
    barcode: NotRequired[str]
    category: NotRequired[str]
    description: NotRequired[str]
    desired_quantity: NotRequired[float]
    expiry_alert_days: NotRequired[int]
    expiry_date: NotRequired[str]
    inventory_id: NotRequired[str]
    inventory_name: NotRequired[str]
    location: NotRequired[str]
    name: str
    price: NotRequired[float]
    quantity: NotRequired[float]
    todo_list: NotRequired[str]
    todo_quantity_placement: NotRequired[str]
    unit: NotRequired[str]


class UpdateItemServiceData(TypedDict):
    """Type for update item service call data."""

    aliases: NotRequired[str]
    auto_add_enabled: NotRequired[bool]
    auto_add_id_to_description_enabled: NotRequired[bool]
    auto_add_to_list_quantity: NotRequired[float]
    barcode: NotRequired[str]
    category: NotRequired[str]
    description: NotRequired[str]
    desired_quantity: NotRequired[float]
    expiry_alert_days: NotRequired[int]
    expiry_date: NotRequired[str]
    inventory_id: NotRequired[str]
    inventory_name: NotRequired[str]
    location: NotRequired[str]
    name: str
    old_name: str
    price: NotRequired[float]
    quantity: NotRequired[float]
    todo_list: NotRequired[str]
    todo_quantity_placement: NotRequired[str]
    unit: NotRequired[str]


class RemoveItemServiceData(TypedDict):
    """Type for remove item service call data."""

    inventory_id: NotRequired[str]
    inventory_name: NotRequired[str]
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
    auto_add_to_list_quantity: float
    category: str
    description: str
    desired_quantity: float
    expiry_alert_days: int
    expiry_date: str
    inventory_id: str
    location: str
    name: str
    price: float
    quantity: float
    todo_list: str
    todo_quantity_placement: str
    unit: str


class InventoryData(TypedDict):
    """Type definition for the main inventory data structure."""

    inventories: dict[str, dict[str, Any]]
    config: NotRequired[dict[str, Any]]  # Optional field


class SimpleInventoryDomainData(TypedDict):
    coordinators: dict[str, "SimpleInventoryCoordinator"]
    repository: "InventoryRepository"
    repository_task: NotRequired[object]
    service_handler: NotRequired["ServiceHandler"]
    services_registered: bool
    todo_manager: NotRequired["TodoManager"]
