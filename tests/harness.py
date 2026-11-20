"""Shared real-stack test harnesses.

- ``point_config_dir``: aim ``hass.config`` (and so the SQLite database) at a temp dir.
- ``todo_stack``: real ServiceHandler -> SimpleInventoryCoordinator -> InventoryRepository
  (tmp SQLite) -> TodoManager, with an in-memory todo integration (``FakeTodo``) standing
  in for HA's.
- ``integration_env`` and friends: the integration set up for real through config entries
  (diagnostics/repairs/HTTP tests); manifest dependencies/requirements are skipped, only
  ``http`` is set up.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant import setup
from homeassistant.components.todo import TodoListEntityFeature
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.loader import Integration
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (  # type: ignore[import-untyped]
    MockConfigEntry,
)

from custom_components.simple_inventory.const import DOMAIN
from custom_components.simple_inventory.coordinator import SimpleInventoryCoordinator
from custom_components.simple_inventory.data import SimpleInventoryData
from custom_components.simple_inventory.hub import InventoryHub
from custom_components.simple_inventory.schemas.service_schemas import SERVICES
from custom_components.simple_inventory.services import ServiceHandler
from custom_components.simple_inventory.storage.repository import InventoryRepository
from custom_components.simple_inventory.todo_manager import TodoManager


def point_config_dir(hass: HomeAssistant, tmp_path: Path) -> None:
    """Make *tmp_path* the config dir, so ``hass.config.path`` resolves inside it."""
    hass.config.config_dir = str(tmp_path)

    def _path(*parts: str) -> str:
        return str(tmp_path.joinpath(*parts))

    hass.config.path = _path  # type: ignore[method-assign]


DESCRIPTION_FEATURES = int(
    TodoListEntityFeature.CREATE_TODO_ITEM
    | TodoListEntityFeature.UPDATE_TODO_ITEM
    | TodoListEntityFeature.DELETE_TODO_ITEM
    | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
)

_RESPONSE_SERVICES = {spec.name for spec in SERVICES if spec.response is not SupportsResponse.NONE}


@dataclass
class FakeTodo:
    """In-memory todo integration: lists of ``{uid, summary, status, description?}``."""

    hass: HomeAssistant
    lists: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    # Lists whose ``get_items`` fails (e.g. the integration behind them is unavailable).
    unreadable: set[str] = field(default_factory=set)

    def add_list(self, entity_id: str, features: int = DESCRIPTION_FEATURES) -> None:
        self.lists[entity_id] = []
        self.hass.states.async_set(entity_id, "0", {"supported_features": features})

    def seed(self, entity_id: str, summary: str, description: str | None = None) -> None:
        entry: dict[str, Any] = {
            "uid": uuid.uuid4().hex,
            "summary": summary,
            "status": "needs_action",
        }
        if description is not None:
            entry["description"] = description
        self.lists[entity_id].append(entry)

    def summaries(self, entity_id: str) -> list[str]:
        return [entry["summary"] for entry in self.lists[entity_id]]

    def _find(self, entity_id: str, item: str) -> dict[str, Any]:
        for entry in self.lists[entity_id]:
            if item in (entry["uid"], entry["summary"]):
                return entry
        raise AssertionError(f"{item!r} not on {entity_id}")

    def register(self) -> None:
        def entity(call: ServiceCall) -> str:
            raw = call.data["entity_id"]
            return str(raw[0] if isinstance(raw, list) else raw)

        async def get_items(call: ServiceCall) -> ServiceResponse:
            eid = entity(call)
            self.calls.append(("get_items", dict(call.data)))
            if eid not in self.lists or eid in self.unreadable:
                raise ValueError(f"Entity {eid} not found")
            return {eid: {"items": [dict(entry) for entry in self.lists[eid]]}}

        async def add_item(call: ServiceCall) -> None:
            eid = entity(call)
            self.calls.append(("add_item", dict(call.data)))
            if eid not in self.lists:
                return  # HA logs and ignores calls targeting missing entities
            entry: dict[str, Any] = {
                "uid": uuid.uuid4().hex,
                "summary": call.data["item"],
                "status": "needs_action",
            }
            if "description" in call.data:
                entry["description"] = call.data["description"]
            self.lists[eid].append(entry)

        async def update_item(call: ServiceCall) -> None:
            eid = entity(call)
            self.calls.append(("update_item", dict(call.data)))
            entry = self._find(eid, call.data["item"])
            if "rename" in call.data:
                entry["summary"] = call.data["rename"]
            if "description" in call.data:
                entry["description"] = call.data["description"]

        async def remove_item(call: ServiceCall) -> None:
            eid = entity(call)
            self.calls.append(("remove_item", dict(call.data)))
            self.lists[eid].remove(self._find(eid, call.data["item"]))

        self.hass.services.async_register(
            "todo", "get_items", get_items, supports_response=SupportsResponse.ONLY
        )
        self.hass.services.async_register("todo", "add_item", add_item)
        self.hass.services.async_register("todo", "update_item", update_item)
        self.hass.services.async_register("todo", "remove_item", remove_item)


@dataclass
class TodoStack:
    hass: HomeAssistant
    repo: InventoryRepository
    hub: InventoryHub
    todo: FakeTodo
    todo_manager: TodoManager
    handler: ServiceHandler
    coordinators: dict[str, SimpleInventoryCoordinator]

    async def add_inventory(self, inventory_id: str, name: str) -> SimpleInventoryCoordinator:
        entry = MockConfigEntry(
            domain=DOMAIN,
            entry_id=inventory_id,
            data={"name": name, "entry_type": "inventory"},
        )
        entry.add_to_hass(self.hass)
        coordinator = SimpleInventoryCoordinator(self.hass, entry, self.repo, self.hub)
        await coordinator.async_upsert_inventory_metadata(inventory_id, name)
        self.coordinators[inventory_id] = coordinator
        return coordinator

    async def call(self, service: str, **data: Any) -> Any:
        return await self.hass.services.async_call(
            DOMAIN,
            service,
            data,
            blocking=True,
            return_response=service in _RESPONSE_SERVICES,
        )

    async def item(self, inventory_id: str, name: str) -> dict[str, Any] | None:
        return await self.repo.get_item_by_name(inventory_id, name)


@pytest.fixture
async def todo_stack(hass: HomeAssistant, tmp_path: Path) -> AsyncGenerator[TodoStack, None]:
    """Real service stack with one inventory ("kitchen") and lists grocery/other."""
    point_config_dir(hass, tmp_path)

    repo = InventoryRepository(hass, db_filename="todo_sync.db")
    await repo.async_initialize()

    todo = FakeTodo(hass)
    todo.register()
    todo.add_list("todo.grocery")
    todo.add_list("todo.other")

    todo_manager = TodoManager(hass)
    coordinators: dict[str, SimpleInventoryCoordinator] = {}
    hub = InventoryHub(hass, repo)
    hass.data[DOMAIN] = SimpleInventoryData(
        coordinators=coordinators, repository=repo, hub=hub, todo_manager=todo_manager
    )
    handler = ServiceHandler(hass, todo_manager)
    hass.data[DOMAIN].service_handler = handler

    for spec in SERVICES:
        hass.services.async_register(
            DOMAIN,
            spec.name,
            getattr(handler, spec.handler),
            schema=spec.schema,
            supports_response=spec.response,
        )

    stack = TodoStack(hass, repo, hub, todo, todo_manager, handler, coordinators)
    await stack.add_inventory("kitchen", "Kitchen")
    try:
        yield stack
    finally:
        await repo.async_close()


@asynccontextmanager
async def integration_env(hass: HomeAssistant, tmp_path: Path) -> AsyncIterator[HomeAssistant]:
    """Point the config dir at *tmp_path*; unload every entry (closing the DB) on exit."""
    point_config_dir(hass, tmp_path)

    original = setup.async_process_deps_reqs

    async def _skip_own_deps(hass: HomeAssistant, config: Any, integration: Integration) -> None:
        if integration.domain != DOMAIN:
            await original(hass, config, integration)

    with patch("homeassistant.setup.async_process_deps_reqs", new=_skip_own_deps):
        try:
            # The image views need HTTP (a manifest dependency, skipped above).
            assert await async_setup_component(hass, "http", {})
            yield hass
        finally:
            for entry in hass.config_entries.async_entries(DOMAIN):
                if entry.state is ConfigEntryState.LOADED:
                    await hass.config_entries.async_unload(entry.entry_id)
            await hass.async_block_till_done()


@asynccontextmanager
async def open_database(hass: HomeAssistant) -> AsyncIterator[InventoryRepository]:
    """A second connection to the integration's database, for seeding and asserting."""
    repository = InventoryRepository(hass)
    await repository.async_initialize()
    try:
        yield repository
    finally:
        await repository.async_close()


def add_entry(
    hass: HomeAssistant, entry_id: str, name: str, entry_type: str = "inventory"
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id=entry_id,
        title=name,
        data={"name": name, "entry_type": entry_type},
    )
    entry.add_to_hass(hass)
    return entry


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Set up *entry*; the first setup loads the domain, which sets up every added entry."""
    if entry.state is ConfigEntryState.NOT_LOADED:
        await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def seed_items(
    hass: HomeAssistant, inventory_id: str, name: str, items: list[dict[str, Any]]
) -> None:
    async with open_database(hass) as repository:
        await repository.upsert_inventory(inventory_id, name, entry_type="inventory")
        for item in items:
            await repository.create_item(inventory_id, item)
