"""Tests for the barcode provider registry."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.simple_inventory.providers.open_beauty_facts import (
    OpenBeautyFactsProvider,
)
from custom_components.simple_inventory.providers.open_pet_food_facts import (
    OpenPetFoodFactsProvider,
)
from custom_components.simple_inventory.providers.openfoodfacts import OpenFoodFactsProvider
from custom_components.simple_inventory.providers.registry import (
    PROVIDER_REGISTRY,
    PROVIDERS,
    create_provider,
    get_all_providers,
)
from custom_components.simple_inventory.providers.upcitemdb import UPCItemDBProvider


@pytest.fixture
def hass_mock() -> MagicMock:
    return MagicMock()


class TestCreateProvider:
    def test_creates_openfoodfacts_provider(self, hass_mock: MagicMock) -> None:
        provider = create_provider(hass_mock, "openfoodfacts")
        assert isinstance(provider, OpenFoodFactsProvider)

    def test_creates_openbeautyfacts_provider(self, hass_mock: MagicMock) -> None:
        provider = create_provider(hass_mock, "openbeautyfacts")
        assert isinstance(provider, OpenBeautyFactsProvider)

    def test_creates_openpetfoodfacts_provider(self, hass_mock: MagicMock) -> None:
        provider = create_provider(hass_mock, "openpetfoodfacts")
        assert isinstance(provider, OpenPetFoodFactsProvider)

    def test_creates_upcitemdb_provider(self, hass_mock: MagicMock) -> None:
        provider = create_provider(hass_mock, "upcitemdb")
        assert isinstance(provider, UPCItemDBProvider)

    def test_unknown_provider_raises(self, hass_mock: MagicMock) -> None:
        with pytest.raises(ValueError, match="Unknown barcode provider"):
            create_provider(hass_mock, "nonexistent")


class TestProviderRegistry:
    def test_registry_contains_all_providers(self) -> None:
        assert "openfoodfacts" in PROVIDER_REGISTRY
        assert "openbeautyfacts" in PROVIDER_REGISTRY
        assert "openpetfoodfacts" in PROVIDER_REGISTRY
        assert "upcitemdb" in PROVIDER_REGISTRY

    def test_registry_has_four_providers(self) -> None:
        assert len(PROVIDER_REGISTRY) == 4

    def test_registry_is_keyed_by_provider_name(self) -> None:
        assert PROVIDER_REGISTRY == {cls.name: cls for cls in PROVIDERS}


class TestGetAllProviders:
    def test_returns_all_providers(self, hass_mock: MagicMock) -> None:
        providers = get_all_providers(hass_mock)
        assert len(providers) == 4
        names = {p.name for p in providers}
        assert names == {"openfoodfacts", "openbeautyfacts", "openpetfoodfacts", "upcitemdb"}

    def test_returns_provider_instances(self, hass_mock: MagicMock) -> None:
        providers = get_all_providers(hass_mock)
        for p in providers:
            assert hasattr(p, "async_lookup")
            assert p.hass is hass_mock
