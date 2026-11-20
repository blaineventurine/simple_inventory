"""Tests for the parallel barcode lookup module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.simple_inventory.const import DOMAIN
from custom_components.simple_inventory.data import SimpleInventoryData
from custom_components.simple_inventory.providers.lookup import (
    async_lookup_barcode_all_providers,
)


@pytest.fixture
def hass_mock() -> MagicMock:
    hass = MagicMock()
    hass.data = {}
    return hass


def _make_provider(name: str, product: dict | None = None, error: bool = False) -> MagicMock:
    provider = MagicMock()
    provider.name = name
    if error:
        provider.async_lookup = AsyncMock(side_effect=Exception("Network error"))
    else:
        provider.async_lookup = AsyncMock(return_value=product)
    return provider


class TestAsyncLookupBarcodeAllProviders:
    async def test_all_providers_return_results(self, hass_mock: MagicMock) -> None:
        providers = [
            _make_provider("openfoodfacts", {"name": "Cheerios", "brand": "General Mills"}),
            _make_provider("openbeautyfacts", None),
            _make_provider("openpetfoodfacts", None),
        ]

        with patch(
            "custom_components.simple_inventory.providers.lookup.get_all_providers",
            return_value=providers,
        ):
            results = await async_lookup_barcode_all_providers(hass_mock, "123456")

        assert len(results) == 3
        assert results[0] == {
            "provider": "openfoodfacts",
            "found": True,
            "product": {"name": "Cheerios", "brand": "General Mills"},
        }
        assert results[1] == {"provider": "openbeautyfacts", "found": False}
        assert results[2] == {"provider": "openpetfoodfacts", "found": False}

    async def test_one_provider_fails_others_succeed(self, hass_mock: MagicMock) -> None:
        providers = [
            _make_provider("openfoodfacts", {"name": "Soup"}),
            _make_provider("openbeautyfacts", error=True),
            _make_provider("openpetfoodfacts", None),
        ]

        with patch(
            "custom_components.simple_inventory.providers.lookup.get_all_providers",
            return_value=providers,
        ):
            results = await async_lookup_barcode_all_providers(hass_mock, "123456")

        assert len(results) == 3
        assert results[0]["found"] is True
        assert results[0]["product"] == {"name": "Soup"}
        assert results[1] == {"provider": "openbeautyfacts", "found": False}
        assert results[2] == {"provider": "openpetfoodfacts", "found": False}

    async def test_all_not_found(self, hass_mock: MagicMock) -> None:
        providers = [
            _make_provider("openfoodfacts", None),
            _make_provider("openbeautyfacts", None),
        ]

        with patch(
            "custom_components.simple_inventory.providers.lookup.get_all_providers",
            return_value=providers,
        ):
            results = await async_lookup_barcode_all_providers(hass_mock, "000000")

        assert len(results) == 2
        assert all(r["found"] is False for r in results)

    async def test_single_provider_found(self, hass_mock: MagicMock) -> None:
        providers = [
            _make_provider("openfoodfacts", {"name": "Test Product"}),
        ]

        with patch(
            "custom_components.simple_inventory.providers.lookup.get_all_providers",
            return_value=providers,
        ):
            results = await async_lookup_barcode_all_providers(hass_mock, "123456")

        assert len(results) == 1
        assert results[0]["found"] is True
        assert results[0]["product"]["name"] == "Test Product"

    async def test_no_providers_returns_empty(self, hass_mock: MagicMock) -> None:
        with patch(
            "custom_components.simple_inventory.providers.lookup.get_all_providers",
            return_value=[],
        ):
            results = await async_lookup_barcode_all_providers(hass_mock, "123456")

        assert results == []

    async def test_multiple_providers_found(self, hass_mock: MagicMock) -> None:
        providers = [
            _make_provider("openfoodfacts", {"name": "Product A"}),
            _make_provider("openbeautyfacts", {"name": "Product B", "brand": "BrandB"}),
        ]

        with patch(
            "custom_components.simple_inventory.providers.lookup.get_all_providers",
            return_value=providers,
        ):
            results = await async_lookup_barcode_all_providers(hass_mock, "123456")

        found_results = [r for r in results if r["found"]]
        assert len(found_results) == 2
        assert found_results[0]["product"]["name"] == "Product A"
        assert found_results[1]["product"]["name"] == "Product B"


def _hass_with_provider_config(config: dict | Exception) -> MagicMock:
    hass = MagicMock()
    repository = MagicMock()
    if isinstance(config, Exception):
        repository.get_barcode_provider_config = AsyncMock(side_effect=config)
    else:
        repository.get_barcode_provider_config = AsyncMock(return_value=config)
    hass.data = {DOMAIN: SimpleInventoryData(repository=repository)}
    return hass


class TestConfiguredProvider:
    async def test_stored_provider_is_the_only_one_queried(self) -> None:
        hass = _hass_with_provider_config({"provider": "upcitemdb"})
        selected = _make_provider("upcitemdb", {"name": "Widget"})

        with (
            patch(
                "custom_components.simple_inventory.providers.lookup.create_provider",
                return_value=selected,
            ) as create_mock,
            patch(
                "custom_components.simple_inventory.providers.lookup.get_all_providers"
            ) as all_mock,
        ):
            results = await async_lookup_barcode_all_providers(hass, "123456")

        create_mock.assert_called_once_with(hass, "upcitemdb")
        all_mock.assert_not_called()
        assert results == [{"provider": "upcitemdb", "found": True, "product": {"name": "Widget"}}]

    @pytest.mark.parametrize(
        "config", [{}, {"provider": "no_longer_registered"}, RuntimeError("db closed")]
    )
    async def test_falls_back_to_all_providers(self, config: dict | Exception) -> None:
        hass = _hass_with_provider_config(config)
        providers = [_make_provider("openfoodfacts", None), _make_provider("upcitemdb", None)]

        with patch(
            "custom_components.simple_inventory.providers.lookup.get_all_providers",
            return_value=providers,
        ):
            results = await async_lookup_barcode_all_providers(hass, "123456")

        assert [r["provider"] for r in results] == ["openfoodfacts", "upcitemdb"]
