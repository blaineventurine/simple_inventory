"""Provider registry for barcode lookup."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from .base import BarcodeProvider
from .open_beauty_facts import OpenBeautyFactsProvider
from .open_pet_food_facts import OpenPetFoodFactsProvider
from .openfoodfacts import OpenFoodFactsProvider

PROVIDER_REGISTRY: dict[str, type[BarcodeProvider]] = {
    "openfoodfacts": OpenFoodFactsProvider,
    "openbeautyfacts": OpenBeautyFactsProvider,
    "openpetfoodfacts": OpenPetFoodFactsProvider,
}

DEFAULT_PROVIDER = "openfoodfacts"


def create_provider(hass: HomeAssistant, provider_name: str | None = None) -> BarcodeProvider:
    """Create a barcode provider instance by name."""
    name = provider_name or DEFAULT_PROVIDER
    provider_cls = PROVIDER_REGISTRY.get(name)
    if provider_cls is None:
        raise ValueError(f"Unknown barcode provider: {name!r}")
    return provider_cls(hass)


def get_all_providers(hass: HomeAssistant) -> list[BarcodeProvider]:
    """Create instances of all registered providers."""
    return [cls(hass) for cls in PROVIDER_REGISTRY.values()]
