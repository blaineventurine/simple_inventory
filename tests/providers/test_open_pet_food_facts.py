"""Tests for the Open Pet Food Facts barcode provider."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.simple_inventory.providers.open_pet_food_facts import (
    OpenPetFoodFactsProvider,
)


@pytest.fixture
def hass_mock() -> MagicMock:
    return MagicMock()


@pytest.fixture
def provider(hass_mock: MagicMock) -> OpenPetFoodFactsProvider:
    return OpenPetFoodFactsProvider(hass_mock)


def _mock_response(data: dict, status: int = 200) -> AsyncMock:
    resp = AsyncMock()
    resp.status = status
    resp.raise_for_status = MagicMock()
    resp.json = AsyncMock(return_value=data)
    return resp


class TestOpenPetFoodFactsProvider:
    def test_provider_name(self, provider: OpenPetFoodFactsProvider) -> None:
        assert provider.provider_name == "openpetfoodfacts"

    def test_api_base(self, provider: OpenPetFoodFactsProvider) -> None:
        assert provider._API_BASE == "https://world.openpetfoodfacts.org"

    async def test_successful_lookup(self, provider: OpenPetFoodFactsProvider) -> None:
        data = {
            "status": 1,
            "product": {
                "product_name": "Premium Dog Food",
                "brands": "Purina",
                "categories": "en:dog-food",
                "generic_name": "Dry dog food",
                "quantity": "2kg",
            },
        }
        mock_session = MagicMock()
        mock_session.get = AsyncMock(return_value=_mock_response(data))

        with patch(
            "custom_components.simple_inventory.providers.openfoodfacts.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await provider.async_lookup("4567890123456")

        assert result is not None
        assert result["name"] == "Premium Dog Food"
        assert result["brand"] == "Purina"

        # Verify correct API base URL was used
        call_args = mock_session.get.call_args
        assert call_args[0][0].startswith("https://world.openpetfoodfacts.org/")

    async def test_not_found_returns_none(self, provider: OpenPetFoodFactsProvider) -> None:
        data = {"status": 0}
        mock_session = MagicMock()
        mock_session.get = AsyncMock(return_value=_mock_response(data))

        with patch(
            "custom_components.simple_inventory.providers.openfoodfacts.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await provider.async_lookup("0000000000000")

        assert result is None
