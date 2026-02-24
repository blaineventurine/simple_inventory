"""Tests for the parallel barcode lookup module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.simple_inventory.providers.lookup import (
    async_lookup_barcode_all_providers,
)


@pytest.fixture
def hass_mock() -> MagicMock:
    return MagicMock()


def _make_provider(name: str, product: dict | None = None, error: bool = False) -> MagicMock:
    provider = MagicMock()
    provider.provider_name = name
    if error:
        provider.async_lookup = AsyncMock(side_effect=Exception("Network error"))
    else:
        provider.async_lookup = AsyncMock(return_value=product)
    provider.async_close = AsyncMock()
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

    async def test_async_close_called_on_all(self, hass_mock: MagicMock) -> None:
        providers = [
            _make_provider("openfoodfacts", {"name": "Product"}),
            _make_provider("openbeautyfacts", error=True),
        ]

        with patch(
            "custom_components.simple_inventory.providers.lookup.get_all_providers",
            return_value=providers,
        ):
            await async_lookup_barcode_all_providers(hass_mock, "123456")

        for p in providers:
            p.async_close.assert_awaited_once()

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
