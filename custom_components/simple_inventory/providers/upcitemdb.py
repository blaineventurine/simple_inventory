"""UPC Item DB barcode lookup provider."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .base import BarcodeProvider, ProductInfo, text_field

_LOGGER = logging.getLogger(__name__)
_API_URL = "https://api.upcitemdb.com/prod/trial/lookup"


class UPCItemDBProvider(BarcodeProvider):
    """Barcode lookup via UPC Item DB API (trial tier)."""

    name = "upcitemdb"

    async def async_lookup(self, barcode: str) -> ProductInfo | None:
        """Look up a barcode on UPC Item DB."""
        session = async_get_clientsession(self.hass)

        try:
            resp = await session.get(
                _API_URL,
                params={"upc": barcode},
                timeout=self._TIMEOUT,
            )
            if resp.status == 404:
                return None
            if resp.status == 429:
                _LOGGER.warning("UPC Item DB rate limit reached for barcode %s", barcode)
                return None
            resp.raise_for_status()
            data: dict[str, Any] = await resp.json()
        except (aiohttp.ClientError, TimeoutError):
            _LOGGER.debug("Lookup failed for barcode %s using provider %s", barcode, self.name)
            return None

        items = data.get("items")
        if data.get("code") != "OK" or not isinstance(items, list) or not items:
            return None

        item = items[0]
        if not isinstance(item, dict):
            return None
        title = text_field(item, "title")
        if not title:
            return None

        result: ProductInfo = {"name": title}

        brand = text_field(item, "brand")
        if brand:
            result["brand"] = brand

        description = text_field(item, "description")
        if description:
            result["description"] = description

        category = text_field(item, "category")
        if category:
            result["category"] = category

        size = text_field(item, "size")
        if size:
            result["unit"] = size

        return result
