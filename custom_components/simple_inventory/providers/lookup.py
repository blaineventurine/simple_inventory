"""Parallel barcode lookup across the configured barcode providers."""

from __future__ import annotations

import asyncio
import logging

from homeassistant.core import HomeAssistant

from ..data import get_repository
from .base import BarcodeProvider, ProviderResult
from .registry import PROVIDER_REGISTRY, create_provider, get_all_providers

_LOGGER = logging.getLogger(__name__)


async def _async_configured_providers(hass: HomeAssistant) -> list[BarcodeProvider]:
    """Return the provider selected via set_barcode_provider_config, else all providers."""
    repository = get_repository(hass)
    if repository is not None:
        try:
            config = await repository.get_barcode_provider_config()
        except Exception:
            _LOGGER.debug("Could not read barcode provider config; querying all providers")
        else:
            provider_name = config.get("provider")
            if provider_name in PROVIDER_REGISTRY:
                return [create_provider(hass, provider_name)]
    return get_all_providers(hass)


async def async_lookup_barcode_all_providers(
    hass: HomeAssistant, barcode: str
) -> list[ProviderResult]:
    """Query the providers in parallel and return one result per provider.

    When a provider has been selected (set_barcode_provider_config) only that provider
    is queried; otherwise every registered provider is.
    """
    providers = await _async_configured_providers(hass)
    if not providers:
        return []

    async def _query_provider(provider: BarcodeProvider) -> ProviderResult:
        try:
            _LOGGER.debug("Querying provider %s for barcode %s", provider.name, barcode)
            product = await provider.async_lookup(barcode)
        except Exception:
            _LOGGER.debug("Provider %s failed for barcode %s", provider.name, barcode)
            return {"provider": provider.name, "found": False}
        if product is None:
            return {"provider": provider.name, "found": False}
        return {"provider": provider.name, "found": True, "product": product}

    return list(await asyncio.gather(*(_query_provider(p) for p in providers)))
