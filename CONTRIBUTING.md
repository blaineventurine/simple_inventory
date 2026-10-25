# Contributing to Simple Inventory

## Development setup

```bash
pip install -r requirements-dev.txt
pre-commit install
```

## Before opening a PR

All of the following must pass. CI enforces them automatically, but run them locally first.

### Lint

```bash
pre-commit run --all-files
```

This runs black (100-char lines), isort, flake8 (with flake8-simplify), and basic file checks.

### Type checking

```bash
mypy --explicit-package-bases custom_components/ tests/
```

Do **not** run mypy on `./` — the `mutants/` directory produces thousands of spurious errors.

### Tests

```bash
python -m pytest tests/
```

Coverage must stay at or above **80%**. New code needs tests. If you're touching existing behaviour, make sure the relevant tests still pass and update them if the behaviour intentionally changes.

## Code conventions

A few things that are easy to get wrong:

- **Field constants**: use `FIELD_*` constants from `const.py` as dict keys everywhere except `services.yaml` and voluptuous schema definitions.
- **Field update pipeline**: scalar item fields are declared once in `ITEM_FIELDS` (`item_fields.py`). The update allowlists, coercion sets, the repository column map and the import/export columns are derived from it. A new field needs a registry entry plus the explicit `ITEM_SCHEMA`, both service TypedDicts in `types.py`, `services.yaml` and the translation files; `tests/test_item_fields.py` fails if they disagree with the registry.
- **Numeric types**: quantities, prices, and amounts are `float` throughout the stack. `expiry_alert_days` is `int`. Don't mix them.
- **Services**: to add a service, add its `SERVICE_*` name to `const.py`; add its schema and one `ServiceSpec(name, schema[, SupportsResponse.OPTIONAL])` row to the `SERVICES` table in `schemas/service_schemas.py` (that table drives registration, unregistration and `ALL_SCHEMAS`); add an `async_<name>` method to `ServiceHandler` in `services/__init__.py`; add its fields to `services.yaml` and its name and descriptions to all four translation files. `tests/test_service_registry.py` fails until the names and fields agree with the schema; also extend the service-name sets asserted in `tests/test_init_module.py`.
- **Translation files**: all four locale files (`translations/en.json`, `es.json`, `fr.json`, `sl.json`) are structurally identical and must be kept in sync. Make the same structural change to all four. Quote placeholders with escaped double quotes (`\"{name}\"`), never apostrophes: HA's frontend renders translations as ICU MessageFormat, where `'{name}'` shows the raw `{name}` (`tests/test_translations.py` enforces this).
- **`services.yaml`**: structure only — `fields` with `required`, `example`, `default` and `selector`. Service and field `name`/`description` text lives only in the translation files (HA shows those; `tests/test_service_registry.py` rejects prose in `services.yaml` and requires a translated name and description for every service and field). Do not include `supports_response` — whether a service responds is set by the `response` column of its `ServiceSpec` row.
- **Coordinator pattern**: services call coordinator methods; nothing calls the repository directly.

## What makes a good PR

- Includes tests for new behavior.
- Updates `services.yaml` (fields) and all translation files (names and descriptions) if services are added or changed.
- Has a clear description of what changed and why.

## Running a subset of tests

```bash
# Single file
python -m pytest tests/test_coordinator.py

# By keyword
python -m pytest tests/ -k "barcode"
```
