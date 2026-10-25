"""Tests for the Open Food Facts barcode provider."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.simple_inventory.providers.openfoodfacts import (
    OpenFoodFactsProvider,
    _strip_lang_prefix,
)


@pytest.fixture
def hass_mock() -> MagicMock:
    return MagicMock()


@pytest.fixture
def provider(hass_mock: MagicMock) -> OpenFoodFactsProvider:
    return OpenFoodFactsProvider(hass_mock)


def _mock_response(data: dict, status: int = 200) -> AsyncMock:
    resp = AsyncMock()
    resp.status = status
    resp.raise_for_status = MagicMock()
    resp.json = AsyncMock(return_value=data)
    return resp


class TestOpenFoodFactsProvider:
    async def test_successful_lookup(self, provider: OpenFoodFactsProvider) -> None:
        data = {
            "status": 1,
            "product": {
                "product_name": "Organic Tomato Soup",
                "brands": "Campbell's",
                "categories": "en:soups, en:canned-foods, en:prepared-meals",
                "generic_name": "Tomato soup ready to serve",
                "quantity": "400g",
                "image_url": "https://example.com/soup.jpg",
            },
        }
        mock_session = MagicMock()
        mock_session.get = AsyncMock(return_value=_mock_response(data))

        with patch(
            "custom_components.simple_inventory.providers.openfoodfacts.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await provider.async_lookup("1234567890123")

        assert result is not None
        assert result["name"] == "Organic Tomato Soup"
        assert result["brand"] == "Campbell's"
        assert result["description"] == "Tomato soup ready to serve"
        assert result["category"] == "soups, canned-foods, prepared-meals"
        assert result["unit"] == "400g"
        assert result["image_url"] == "https://example.com/soup.jpg"

    async def test_status_zero_returns_none(self, provider: OpenFoodFactsProvider) -> None:
        data = {"status": 0}
        mock_session = MagicMock()
        mock_session.get = AsyncMock(return_value=_mock_response(data))

        with patch(
            "custom_components.simple_inventory.providers.openfoodfacts.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await provider.async_lookup("0000000000000")

        assert result is None

    async def test_http_error_returns_none(self, provider: OpenFoodFactsProvider) -> None:
        mock_session = MagicMock()
        mock_session.get = AsyncMock(side_effect=aiohttp.ClientError("Connection failed"))

        with patch(
            "custom_components.simple_inventory.providers.openfoodfacts.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await provider.async_lookup("1234567890123")

        assert result is None

    async def test_empty_product_name_returns_none(self, provider: OpenFoodFactsProvider) -> None:
        data = {"status": 1, "product": {"product_name": ""}}
        mock_session = MagicMock()
        mock_session.get = AsyncMock(return_value=_mock_response(data))

        with patch(
            "custom_components.simple_inventory.providers.openfoodfacts.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await provider.async_lookup("1234567890123")

        assert result is None

    async def test_category_lang_prefix_stripping(self, provider: OpenFoodFactsProvider) -> None:
        data = {
            "status": 1,
            "product": {
                "product_name": "Test Product",
                "categories": "en:beverages, fr:boissons, de:getränke, Plain Category",
            },
        }
        mock_session = MagicMock()
        mock_session.get = AsyncMock(return_value=_mock_response(data))

        with patch(
            "custom_components.simple_inventory.providers.openfoodfacts.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await provider.async_lookup("1234567890123")

        assert result is not None
        # Should strip lang prefixes and limit to 3
        assert result["category"] == "beverages, boissons, getränke"

    async def test_minimal_product_only_name(self, provider: OpenFoodFactsProvider) -> None:
        data = {"status": 1, "product": {"product_name": "Simple Item"}}
        mock_session = MagicMock()
        mock_session.get = AsyncMock(return_value=_mock_response(data))

        with patch(
            "custom_components.simple_inventory.providers.openfoodfacts.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await provider.async_lookup("1234567890123")

        assert result is not None
        assert result["name"] == "Simple Item"
        assert "brand" not in result
        assert "description" not in result
        assert "category" not in result

    def test_provider_name(self, provider: OpenFoodFactsProvider) -> None:
        assert provider.name == "openfoodfacts"


class TestStripLangPrefix:
    def test_with_prefix(self) -> None:
        assert _strip_lang_prefix("en:beverages") == "beverages"

    def test_without_prefix(self) -> None:
        assert _strip_lang_prefix("Plain Category") == "Plain Category"

    def test_long_prefix_not_stripped(self) -> None:
        assert _strip_lang_prefix("food:subcategory") == "food:subcategory"

    def test_two_char_prefix(self) -> None:
        assert _strip_lang_prefix("fr:boissons") == "boissons"


class TestNullFields:
    """OFF returns JSON null for missing secondary fields; that must not drop the product."""

    async def test_null_secondary_fields_keep_product(
        self, provider: OpenFoodFactsProvider
    ) -> None:
        data = {
            "status": 1,
            "product": {
                "product_name": "Peanut Butter",
                "brands": None,
                "categories": None,
                "generic_name": None,
                "quantity": None,
                "image_url": None,
            },
        }
        mock_session = MagicMock()
        mock_session.get = AsyncMock(return_value=_mock_response(data))

        with patch(
            "custom_components.simple_inventory.providers.openfoodfacts.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await provider.async_lookup("1234567890123")

        assert result == {"name": "Peanut Butter"}

    @pytest.mark.parametrize("product", [None, {"product_name": None}])
    async def test_null_product_or_name_is_not_found(
        self, provider: OpenFoodFactsProvider, product: dict | None
    ) -> None:
        mock_session = MagicMock()
        mock_session.get = AsyncMock(return_value=_mock_response({"status": 1, "product": product}))

        with patch(
            "custom_components.simple_inventory.providers.openfoodfacts.async_get_clientsession",
            return_value=mock_session,
        ):
            assert await provider.async_lookup("1234567890123") is None
