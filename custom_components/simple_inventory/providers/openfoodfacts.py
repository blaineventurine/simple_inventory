"""Open Food Facts barcode lookup provider."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .base import BarcodeProvider, ProductInfo

_LOGGER = logging.getLogger(__name__)

_FIELDS = "product_name,brands,categories,generic_name,quantity,image_url"
_USER_AGENT = "SimpleInventory/1.0 (HomeAssistant Integration)"
_TIMEOUT = aiohttp.ClientTimeout(total=10)
_MAX_CATEGORIES = 3


class OpenFoodFactsProvider(BarcodeProvider):
    """Barcode lookup via Open Food Facts API."""

    _API_BASE = "https://world.openfoodfacts.org"

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    @property
    def provider_name(self) -> str:
        return "openfoodfacts"

    async def async_lookup(self, barcode: str) -> ProductInfo | None:
        """Look up a barcode on Open Food Facts."""
        session = async_get_clientsession(self._hass)
        url = f"{self._API_BASE}/api/v2/product/{barcode}.json"

        try:
            resp = await session.get(
                url,
                params={"fields": _FIELDS},
                headers={"User-Agent": _USER_AGENT},
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            data: dict[str, Any] = await resp.json()
        except (aiohttp.ClientError, TimeoutError):
            _LOGGER.debug(
                "Lookup failed for barcode %s using provider %s", barcode, self.provider_name
            )
            return None

        if data.get("status") != 1:
            return None

        product = data.get("product", {})
        product_name = product.get("product_name", "").strip()
        if not product_name:
            return None

        result: ProductInfo = {"name": product_name}

        brand = product.get("brands", "").strip()
        if brand:
            result["brand"] = brand

        generic_name = product.get("generic_name", "").strip()
        if generic_name:
            result["description"] = generic_name

        raw_categories = product.get("categories", "").strip()
        if raw_categories:
            cats = [_strip_lang_prefix(c.strip()) for c in raw_categories.split(",")]
            cats = [c for c in cats if c][:_MAX_CATEGORIES]
            if cats:
                result["category"] = ", ".join(cats)

        unit = product.get("quantity", "").strip()
        if unit:
            result["unit"] = unit

        image_url = product.get("image_url", "").strip()
        if image_url:
            result["image_url"] = image_url

        return result


def _strip_lang_prefix(category: str) -> str:
    """Strip language prefix from a category (e.g. 'en:canned-foods' -> 'canned-foods')."""
    if ":" in category:
        parts = category.split(":", 1)
        if len(parts[0]) <= 3:
            return parts[1].strip()
    return category
