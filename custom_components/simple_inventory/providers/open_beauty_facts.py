"""Open Beauty Facts barcode lookup provider."""

from __future__ import annotations

from .openfoodfacts import OpenFoodFactsProvider


class OpenBeautyFactsProvider(OpenFoodFactsProvider):
    """Barcode lookup via Open Beauty Facts API."""

    _API_BASE = "https://world.openbeautyfacts.org"

    @property
    def provider_name(self) -> str:
        return "openbeautyfacts"
