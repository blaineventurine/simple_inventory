"""Open Pet Food Facts barcode lookup provider."""

from __future__ import annotations

from .openfoodfacts import OpenFoodFactsProvider


class OpenPetFoodFactsProvider(OpenFoodFactsProvider):
    """Barcode lookup via Open Pet Food Facts API."""

    _API_BASE = "https://world.openpetfoodfacts.org"

    @property
    def provider_name(self) -> str:
        return "openpetfoodfacts"
