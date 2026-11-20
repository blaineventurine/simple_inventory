"""Provider registry for barcode lookup."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from .base import BarcodeProvider
from .open_beauty_facts import OpenBeautyFactsProvider
from .open_pet_food_facts import OpenPetFoodFactsProvider
from .openfoodfacts import OpenFoodFactsProvider
from .upcitemdb import UPCItemDBProvider

PROVIDERS: tuple[type[BarcodeProvider], ...] = (
    OpenFoodFactsProvider,
    OpenBeautyFactsProvider,
    OpenPetFoodFactsProvider,
    UPCItemDBProvider,
)

PROVIDER_REGISTRY: dict[str, type[BarcodeProvider]] = {cls.name: cls for cls in PROVIDERS}


def create_provider(hass: HomeAssistant, provider_name: str) -> BarcodeProvider:
    """Create a barcode provider instance by name."""
    provider_cls = PROVIDER_REGISTRY.get(provider_name)
    if provider_cls is None:
        raise ValueError(f"Unknown barcode provider: {provider_name!r}")
    return provider_cls(hass)


def get_all_providers(hass: HomeAssistant) -> list[BarcodeProvider]:
    """Create instances of all registered providers."""
    return [cls(hass) for cls in PROVIDERS]
