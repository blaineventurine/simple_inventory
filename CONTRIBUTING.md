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
- **Field update pipeline**: any new updateable field must be added to **two** allowlists — `_UPDATEABLE_FIELDS` in `services/inventory_service.py` and `_get_allowed_update_fields()` in `coordinator/_core.py`. Missing either one silently drops the field.
- **Numeric types**: quantities, prices, and amounts are `float` throughout the stack. `expiry_alert_days` is `int`. Don't mix them.
- **Services**: adding a new service call requires updates in seven places: `const.py`, `schemas/service_schemas.py`, `services/__init__.py`, `__init__.py` (registration table + `_SERVICE_NAMES`), `services.yaml`, and all three translation files (`translations/en.json`, `es.json`, `fr.json`). See the existing services for the pattern.
- **Translation files**: all three locale files (`en.json`, `es.json`, `fr.json`) are structurally identical and must be kept in sync. Make the same structural change to all three.
- **`services.yaml`**: do not include `supports_response` — that key is only valid in the programmatic `hass.services.async_register()` call.
- **Coordinator pattern**: services call coordinator methods; nothing calls the repository directly.

## What makes a good PR

- Includes tests for new behavior.
- Updates `services.yaml` and all translation files if services are added or changed.
- Has a clear description of what changed and why.

## Running a subset of tests

```bash
# Single file
python -m pytest tests/test_coordinator.py

# By keyword
python -m pytest tests/ -k "barcode"
```
