#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, Iterator, List, Mapping, Union, cast

JSONScalar = Union[str, int, float, bool, None]
JSONValue = Union[JSONScalar, "JSONObject", "JSONArray"]
JSONObject = Dict[str, JSONValue]
JSONArray = List[JSONValue]

ROOT = Path(__file__).resolve().parents[1]
TRANSLATIONS = ROOT / "custom_components" / "simple_inventory" / "translations"


def flatten(data: Mapping[str, JSONValue], prefix: str = "") -> Iterator[str]:
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, Mapping):
            yield from flatten(value, path)
        else:
            yield path


def load_json(path: Path) -> JSONObject:
    with path.open(encoding="utf-8") as fh:
        raw = json.load(fh)

    if not isinstance(raw, dict):
        raise TypeError(f"{path} must contain a JSON object at the root")

    if not all(isinstance(k, str) for k in raw):
        raise TypeError(f"{path} contains non-string keys, which are invalid in translations")

    return cast(JSONObject, raw)


def main() -> None:
    base_file = TRANSLATIONS / "en.json"
    base_keys = set(flatten(load_json(base_file)))

    errors: list[str] = []

    for file in TRANSLATIONS.glob("*.json"):
        if file.name == "en.json":
            continue
        keys = set(flatten(load_json(file)))
        missing = base_keys - keys
        extra = keys - base_keys
        if missing or extra:
            errors.append(f"{file.name} missing: {sorted(missing)} extra: {sorted(extra)}")

    if errors:
        print("Translation mismatches detected:")
        for err in errors:
            print(f"    • {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
