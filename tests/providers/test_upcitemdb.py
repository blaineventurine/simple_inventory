"""Tests for the UPC Item DB barcode provider."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.simple_inventory.providers.upcitemdb import UPCItemDBProvider


@pytest.fixture
def hass_mock() -> MagicMock:
    return MagicMock()


@pytest.fixture
def provider(hass_mock: MagicMock) -> UPCItemDBProvider:
    return UPCItemDBProvider(hass_mock)


def _mock_response(data: dict, status: int = 200) -> AsyncMock:
    resp = AsyncMock()
    resp.status = status
    resp.raise_for_status = MagicMock()
    resp.json = AsyncMock(return_value=data)
    return resp


class TestUPCItemDBProvider:
    async def test_successful_lookup(self, provider: UPCItemDBProvider) -> None:
        data = {
            "code": "OK",
            "total": 1,
            "offset": 0,
            "items": [
                {
                    "title": "Organic Whole Milk",
                    "description": "Pasteurized whole milk",
                    "brand": "Horizon",
                    "category": "Dairy",
                    "size": "1 gallon",
                }
            ],
        }
        mock_session = MagicMock()
        mock_session.get = AsyncMock(return_value=_mock_response(data))

        with patch(
            "custom_components.simple_inventory.providers.upcitemdb.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await provider.async_lookup("012345678905")

        assert result is not None
        assert result["name"] == "Organic Whole Milk"
        assert result["brand"] == "Horizon"
        assert result["description"] == "Pasteurized whole milk"
        assert result["category"] == "Dairy"
        assert result["unit"] == "1 gallon"

    async def test_not_found_404_returns_none(self, provider: UPCItemDBProvider) -> None:
        mock_session = MagicMock()
        mock_session.get = AsyncMock(return_value=_mock_response({}, status=404))

        with patch(
            "custom_components.simple_inventory.providers.upcitemdb.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await provider.async_lookup("0000000000000")

        assert result is None

    async def test_rate_limit_429_returns_none(self, provider: UPCItemDBProvider) -> None:
        mock_session = MagicMock()
        mock_session.get = AsyncMock(return_value=_mock_response({}, status=429))

        with patch(
            "custom_components.simple_inventory.providers.upcitemdb.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await provider.async_lookup("0000000000000")

        assert result is None

    async def test_http_error_returns_none(self, provider: UPCItemDBProvider) -> None:
        mock_session = MagicMock()
        mock_session.get = AsyncMock(side_effect=aiohttp.ClientError("Connection failed"))

        with patch(
            "custom_components.simple_inventory.providers.upcitemdb.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await provider.async_lookup("1234567890123")

        assert result is None

    async def test_empty_items_returns_none(self, provider: UPCItemDBProvider) -> None:
        data = {"code": "OK", "total": 0, "offset": 0, "items": []}
        mock_session = MagicMock()
        mock_session.get = AsyncMock(return_value=_mock_response(data))

        with patch(
            "custom_components.simple_inventory.providers.upcitemdb.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await provider.async_lookup("0000000000000")

        assert result is None

    async def test_non_ok_code_returns_none(self, provider: UPCItemDBProvider) -> None:
        data = {"code": "NOT_FOUND", "message": "No matched item"}
        mock_session = MagicMock()
        mock_session.get = AsyncMock(return_value=_mock_response(data))

        with patch(
            "custom_components.simple_inventory.providers.upcitemdb.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await provider.async_lookup("0000000000000")

        assert result is None

    async def test_empty_title_returns_none(self, provider: UPCItemDBProvider) -> None:
        data = {"code": "OK", "total": 1, "items": [{"title": ""}]}
        mock_session = MagicMock()
        mock_session.get = AsyncMock(return_value=_mock_response(data))

        with patch(
            "custom_components.simple_inventory.providers.upcitemdb.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await provider.async_lookup("1234567890123")

        assert result is None

    async def test_minimal_product_only_name(self, provider: UPCItemDBProvider) -> None:
        data = {"code": "OK", "total": 1, "items": [{"title": "Simple Item"}]}
        mock_session = MagicMock()
        mock_session.get = AsyncMock(return_value=_mock_response(data))

        with patch(
            "custom_components.simple_inventory.providers.upcitemdb.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await provider.async_lookup("1234567890123")

        assert result is not None
        assert result["name"] == "Simple Item"
        assert "brand" not in result
        assert "description" not in result
        assert "category" not in result
        assert "unit" not in result

    def test_provider_name(self, provider: UPCItemDBProvider) -> None:
        assert provider.provider_name == "upcitemdb"
