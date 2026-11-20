"""Abstract base class for barcode product lookup providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar, NotRequired, TypedDict

import aiohttp

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


def text_field(data: Mapping[str, Any], key: str) -> str:
    """Return a stripped string for an optional API field; null/missing/non-text → ''."""
    value = data.get(key)
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, int | float) and not isinstance(value, bool):
        return str(value)
    return ""


class ProductInfo(TypedDict):
    """Standardized product information returned by providers."""

    name: str
    description: NotRequired[str]
    category: NotRequired[str]
    brand: NotRequired[str]
    unit: NotRequired[str]
    image_url: NotRequired[str]


class ProviderResult(TypedDict):
    """One provider's answer for a barcode; ``product`` is present only when found."""

    provider: str
    found: bool
    product: NotRequired[ProductInfo]


class BarcodeProvider(ABC):
    """Abstract base class for barcode lookup providers."""

    name: ClassVar[str]
    """Registry key, stored by set_barcode_provider_config and reported in results."""

    _TIMEOUT: ClassVar[aiohttp.ClientTimeout] = aiohttp.ClientTimeout(total=10)
    _USER_AGENT: ClassVar[str] = "SimpleInventory/1.0 (HomeAssistant Integration)"

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize with a Home Assistant instance (for its shared HTTP session)."""
        self.hass = hass

    @abstractmethod
    async def async_lookup(self, barcode: str) -> ProductInfo | None:
        """Look up a barcode and return product info, or None if not found."""
