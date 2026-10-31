"""Typed integration-wide state stored in ``hass.data[DOMAIN]``."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.util.hass_dict import HassKey

from .const import DOMAIN

if TYPE_CHECKING:
    from .coordinator import SimpleInventoryCoordinator
    from .hub import InventoryHub
    from .services import ServiceHandler
    from .storage.repository import InventoryRepository
    from .todo_manager import TodoManager


@dataclass
class SimpleInventoryData:
    """State shared by every config entry of the integration.

    Coordinators live in a dict keyed by entry id rather than ``entry.runtime_data``:
    services, WebSocket commands, intents and the HTTP view resolve any inventory id
    to its coordinator, and setup/unload use "no coordinator left" to decide when to
    tear down the shared repository and services.
    """

    coordinators: dict[str, SimpleInventoryCoordinator] = field(default_factory=dict)
    repository: InventoryRepository | None = None
    # Cross-inventory reads and the one expiry cache; created and dropped with ``repository``.
    hub: InventoryHub | None = None
    repository_task: asyncio.Task[None] | None = None
    services_registered: bool = False
    todo_manager: TodoManager | None = None
    service_handler: ServiceHandler | None = None


DATA_KEY: HassKey[SimpleInventoryData] = HassKey(DOMAIN)


def get_domain_data(hass: HomeAssistant) -> SimpleInventoryData:
    """Return the integration state; raise if no config entry has been set up."""
    data = hass.data.get(DATA_KEY)
    if data is None:
        raise RuntimeError(f"{DOMAIN} is not set up: hass.data[{DOMAIN!r}] is missing")
    return data


def get_coordinators(hass: HomeAssistant) -> dict[str, SimpleInventoryCoordinator]:
    """Return the coordinators mapping (or an empty dict when not set up)."""
    data = hass.data.get(DATA_KEY)
    return {} if data is None else data.coordinators


def get_hub(hass: HomeAssistant) -> InventoryHub | None:
    """The cross-inventory hub, or None while no inventory is loaded."""
    data = hass.data.get(DATA_KEY)
    return None if data is None or not data.coordinators else data.hub


def get_repository(hass: HomeAssistant) -> InventoryRepository | None:
    """Return the shared repository if available."""
    data = hass.data.get(DATA_KEY)
    return None if data is None else data.repository


def get_todo_manager(hass: HomeAssistant) -> TodoManager | None:
    """Return the shared todo manager if available."""
    data = hass.data.get(DATA_KEY)
    return None if data is None else data.todo_manager


def get_service_handler(hass: HomeAssistant) -> ServiceHandler | None:
    """Return the service handler if available."""
    data = hass.data.get(DATA_KEY)
    return None if data is None else data.service_handler
