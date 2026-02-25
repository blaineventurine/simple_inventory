from __future__ import annotations

from typing import TYPE_CHECKING, cast

from homeassistant.core import HomeAssistant

from ..const import DOMAIN
from ..coordinator import SimpleInventoryCoordinator
from ..storage.repository import InventoryRepository
from ..types import SimpleInventoryDomainData

if TYPE_CHECKING:
    from ..todo_manager import TodoManager
    from . import ServiceHandler


def get_domain_data(hass: HomeAssistant) -> SimpleInventoryDomainData | None:
    """Return typed hass.data[DOMAIN] if present."""
    return cast(
        SimpleInventoryDomainData | None,
        cast(object, hass.data.get(DOMAIN)),
    )


def get_coordinators(hass: HomeAssistant) -> dict[str, SimpleInventoryCoordinator]:
    """Return the coordinators mapping (or an empty dict)."""
    domain_data = get_domain_data(hass)
    if domain_data is None:
        return {}
    return domain_data["coordinators"]


def get_repository(hass: HomeAssistant) -> InventoryRepository | None:
    """Return the shared repository if available."""
    domain_data = get_domain_data(hass)
    if domain_data is None:
        return None
    return domain_data["repository"]


def get_todo_manager(hass: HomeAssistant) -> "TodoManager | None":
    """Return the todo manager if available."""
    domain_data = get_domain_data(hass)
    if domain_data is None:
        return None
    return domain_data.get("todo_manager")


def get_service_handler(hass: HomeAssistant) -> "ServiceHandler | None":
    """Return the service handler if available."""
    domain_data = get_domain_data(hass)
    if domain_data is None:
        return None
    return domain_data.get("service_handler")
