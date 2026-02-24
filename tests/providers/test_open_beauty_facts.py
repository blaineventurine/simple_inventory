"""Tests for the Open Beauty Facts barcode provider."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.simple_inventory.providers.open_beauty_facts import (
    OpenBeautyFactsProvider,
)


@pytest.fixture
def hass_mock() -> MagicMock:
    return MagicMock()


@pytest.fixture
def provider(hass_mock: MagicMock) -> OpenBeautyFactsProvider:
    return OpenBeautyFactsProvider(hass_mock)


def _mock_response(data: dict, status: int = 200) -> AsyncMock:
    resp = AsyncMock()
    resp.status = status
    resp.raise_for_status = MagicMock()
    resp.json = AsyncMock(return_value=data)
    return resp


class TestOpenBeautyFactsProvider:
    def test_provider_name(self, provider: OpenBeautyFactsProvider) -> None:
        assert provider.provider_name == "openbeautyfacts"

    def test_api_base(self, provider: OpenBeautyFactsProvider) -> None:
        assert provider._API_BASE == "https://world.openbeautyfacts.org"

    async def test_successful_lookup(self, provider: OpenBeautyFactsProvider) -> None:
        data = {
            "status": 1,
            "product": {
                "product_name": "Shampoo Gentle Care",
                "brands": "Dove",
                "categories": "en:shampoos",
                "generic_name": "Hair shampoo",
                "quantity": "400ml",
            },
        }
        mock_session = MagicMock()
        mock_session.get = AsyncMock(return_value=_mock_response(data))

        with patch(
            "custom_components.simple_inventory.providers.openfoodfacts.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await provider.async_lookup("3456789012345")

        assert result is not None
        assert result["name"] == "Shampoo Gentle Care"
        assert result["brand"] == "Dove"

        # Verify correct API base URL was used
        call_args = mock_session.get.call_args
        assert call_args[0][0].startswith("https://world.openbeautyfacts.org/")

    async def test_not_found_returns_none(self, provider: OpenBeautyFactsProvider) -> None:
        data = {"status": 0}
        mock_session = MagicMock()
        mock_session.get = AsyncMock(return_value=_mock_response(data))

        with patch(
            "custom_components.simple_inventory.providers.openfoodfacts.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await provider.async_lookup("0000000000000")

        assert result is None
