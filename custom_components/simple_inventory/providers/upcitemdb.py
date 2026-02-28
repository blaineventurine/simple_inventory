"""UPC Item DB barcode lookup provider."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .base import BarcodeProvider, ProductInfo

_LOGGER = logging.getLogger(__name__)
_TIMEOUT = aiohttp.ClientTimeout(total=10)
_API_URL = "https://api.upcitemdb.com/prod/trial/lookup"


class UPCItemDBProvider(BarcodeProvider):
    """Barcode lookup via UPC Item DB API (trial tier)."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    @property
    def provider_name(self) -> str:
        return "upcitemdb"

    async def async_lookup(self, barcode: str) -> ProductInfo | None:
        """Look up a barcode on UPC Item DB."""
        session = async_get_clientsession(self._hass)

        try:
            resp = await session.get(
                _API_URL,
                params={"upc": barcode},
                timeout=_TIMEOUT,
            )
            if resp.status == 404:
                return None
            if resp.status == 429:
                _LOGGER.warning("UPC Item DB rate limit reached for barcode %s", barcode)
                return None
            resp.raise_for_status()
            data: dict[str, Any] = await resp.json()
        except (aiohttp.ClientError, TimeoutError):
            _LOGGER.debug(
                "Lookup failed for barcode %s using provider %s", barcode, self.provider_name
            )
            return None

        if data.get("code") != "OK" or not data.get("items"):
            return None

        item = data["items"][0]
        title = item.get("title", "").strip()
        if not title:
            return None

        result: ProductInfo = {"name": title}

        brand = item.get("brand", "").strip()
        if brand:
            result["brand"] = brand

        description = item.get("description", "").strip()
        if description:
            result["description"] = description

        category = item.get("category", "").strip()
        if category:
            result["category"] = category

        size = item.get("size", "").strip()
        if size:
            result["unit"] = size

        return result
