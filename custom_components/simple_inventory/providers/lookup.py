"""Parallel barcode lookup across all registered providers."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.core import HomeAssistant

from .registry import get_all_providers

_LOGGER = logging.getLogger(__name__)


async def async_lookup_barcode_all_providers(
    hass: HomeAssistant, barcode: str
) -> list[dict[str, Any]]:
    """Query all registered providers in parallel and return results."""
    providers = get_all_providers(hass)
    if not providers:
        return []

    async def _query_provider(provider: Any) -> dict[str, Any]:
        try:
            _LOGGER.debug("Querying provider %s for barcode %s", provider.provider_name, barcode)
            product = await provider.async_lookup(barcode)
            if product is None:
                return {"provider": provider.provider_name, "found": False}
            return {
                "provider": provider.provider_name,
                "found": True,
                "product": dict(product),
            }
        except Exception:
            _LOGGER.debug(
                "Provider %s failed for barcode %s",
                provider.provider_name,
                barcode,
            )
            return {"provider": provider.provider_name, "found": False}
        finally:
            await provider.async_close()

    tasks = [_query_provider(p) for p in providers]
    results: list[dict[str, Any]] = await asyncio.gather(*tasks)
    return results
