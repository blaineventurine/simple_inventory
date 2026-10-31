"""Tests for the typed hass.data accessors."""

from unittest.mock import MagicMock

import pytest

from custom_components.simple_inventory.const import DOMAIN
from custom_components.simple_inventory.data import (
    SimpleInventoryData,
    get_coordinators,
    get_domain_data,
    get_hub,
    get_repository,
    get_service_handler,
    get_todo_manager,
)


def test_get_domain_data_raises_when_not_set_up() -> None:
    hass = MagicMock()
    hass.data = {}
    with pytest.raises(RuntimeError, match="not set up"):
        get_domain_data(hass)


def test_optional_accessors_when_not_set_up() -> None:
    hass = MagicMock()
    hass.data = {}
    assert get_coordinators(hass) == {}
    assert get_hub(hass) is None
    assert get_repository(hass) is None
    assert get_todo_manager(hass) is None
    assert get_service_handler(hass) is None


def test_accessors_return_stored_state() -> None:
    hass = MagicMock()
    data = SimpleInventoryData(
        repository=MagicMock(), todo_manager=MagicMock(), service_handler=MagicMock()
    )
    hass.data = {DOMAIN: data}
    assert get_domain_data(hass) is data
    assert get_coordinators(hass) is data.coordinators
    assert get_repository(hass) is data.repository
    assert get_todo_manager(hass) is data.todo_manager
    assert get_service_handler(hass) is data.service_handler


def test_get_hub_only_while_an_inventory_is_loaded() -> None:
    """Cross-inventory reads need a loaded inventory; the hub outlives none."""
    hass = MagicMock()
    data = SimpleInventoryData(repository=MagicMock(), hub=MagicMock())
    hass.data = {DOMAIN: data}
    assert get_hub(hass) is None

    data.coordinators["kitchen"] = MagicMock()
    assert get_hub(hass) is data.hub
