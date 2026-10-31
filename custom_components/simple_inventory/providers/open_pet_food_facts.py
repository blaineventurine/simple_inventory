"""Open Pet Food Facts barcode lookup provider."""

from __future__ import annotations

from .openfoodfacts import OpenFoodFactsProvider


class OpenPetFoodFactsProvider(OpenFoodFactsProvider):
    """Barcode lookup via Open Pet Food Facts API."""

    name = "openpetfoodfacts"
    _API_BASE = "https://world.openpetfoodfacts.org"
