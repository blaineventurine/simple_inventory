"""The SERVICES table is the single list of services; everything else must match it."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import voluptuous as vol
from homeassistant.util.yaml import load_yaml_dict

from custom_components.simple_inventory.schemas.service_schemas import (
    ALL_SCHEMAS,
    SERVICES,
    ServiceSpec,
)
from custom_components.simple_inventory.services import ServiceHandler

COMPONENT = Path(__file__).parents[1] / "custom_components" / "simple_inventory"
LOCALES = ("en", "es", "fr", "sl")


def _services_yaml() -> dict[str, Any]:
    return dict(load_yaml_dict(str(COMPONENT / "services.yaml")))


def _translations(locale: str) -> dict[str, Any]:
    return dict(json.loads((COMPONENT / "translations" / f"{locale}.json").read_text()))


def _fields(service: dict[str, Any] | None) -> set[str]:
    return set((service or {}).get("fields", {}))


def test_service_names_are_unique() -> None:
    names = [spec.name for spec in SERVICES]
    assert len(names) == len(set(names))


def test_all_schemas_is_derived_from_the_table() -> None:
    assert ALL_SCHEMAS == {spec.name: spec.schema for spec in SERVICES}


def test_every_service_has_a_handler() -> None:
    for spec in SERVICES:
        assert callable(getattr(ServiceHandler, spec.handler, None)), spec.handler


def test_services_yaml_documents_exactly_the_registered_services() -> None:
    assert set(_services_yaml()) == {spec.name for spec in SERVICES}


@pytest.mark.parametrize("locale", LOCALES)
def test_translations_cover_exactly_the_registered_services(locale: str) -> None:
    services = _translations(locale)["services"]
    documented = _services_yaml()

    assert set(services) == {spec.name for spec in SERVICES}
    for name, service in documented.items():
        assert set(services[name].get("fields", {})) == _fields(service), name


def test_services_yaml_carries_no_prose() -> None:
    """The translation files are the only prose source; services.yaml is structure only."""
    prose = []
    for name, service in _services_yaml().items():
        prose += [f"{name}.{key}" for key in ("name", "description") if key in service]
        for field, spec in (service.get("fields") or {}).items():
            prose += [f"{name}.{field}.{key}" for key in ("name", "description") if key in spec]
    assert prose == []


@pytest.mark.parametrize("locale", LOCALES)
def test_every_service_and_field_has_a_name_and_description(locale: str) -> None:
    missing = []
    for name, service in _translations(locale)["services"].items():
        nodes = {name: service} | {
            f"{name}.{field}": spec for field, spec in service.get("fields", {}).items()
        }
        for path, node in nodes.items():
            missing += [f"{path}.{key}" for key in ("name", "description") if not node.get(key)]
    assert missing == []


@pytest.mark.parametrize("locale", ("es", "fr", "sl"))
def test_service_descriptions_are_translated(locale: str) -> None:
    """No English description is copied verbatim into another locale."""
    english = _translations("en")["services"]
    copied = []
    for name, service in _translations(locale)["services"].items():
        if service["description"] == english[name]["description"]:
            copied.append(name)
        for field, spec in service.get("fields", {}).items():
            if spec["description"] == english[name]["fields"][field]["description"]:
                copied.append(f"{name}.{field}")
    assert copied == []


def _schema_keys(schema: Any) -> set[str]:
    """Top-level keys of a service schema (unwraps vol.Schema and vol.All)."""
    if isinstance(schema, vol.Schema):
        return _schema_keys(schema.schema)
    if isinstance(schema, vol.All):
        return set().union(*(_schema_keys(v) for v in schema.validators))
    if isinstance(schema, dict):
        return {str(key) for key in schema}
    return set()


def test_service_specs_are_hashable() -> None:
    assert len(set(SERVICES)) == len(SERVICES)


@pytest.mark.parametrize("spec", SERVICES, ids=lambda spec: spec.name)
def test_schema_fields_match_services_yaml_and_translations(spec: ServiceSpec) -> None:
    keys = _schema_keys(spec.schema)
    assert keys == _fields(_services_yaml()[spec.name])
    for locale in LOCALES:
        services = _translations(locale)["services"]
        assert keys == set(services[spec.name].get("fields", {})), locale
