[← Back to README](../README.md)

# Diagnostics & Repairs

## Diagnostics

Download diagnostics from **Settings -> Devices & Services -> Simple Inventory -> (entry menu) -> Download diagnostics** and attach the file to bug reports. It contains:

- integration version, `api_version`, database schema version, and whether the legacy JSON store was migrated
- the entry's type, name, icon, whether it has a description, options, and load state
- counts: items, items out of stock, locations, categories, barcodes, aliases, history events
- auto-add: number of items with auto-add enabled, and each referenced todo list with its item count, whether it currently exists, and whether it supports item descriptions
- the selected barcode lookup provider (or `null`)
- `backups_count` and `newest_backup_age_seconds` (the newest [snapshot's](backups-and-restore.md#backups--restore) age; `null` if none exist) — never the snapshots' filenames
- on the global entry: every inventory entry and its load state

Item names, descriptions, barcodes, aliases, and prices are **never** included.

## Repairs

Problems the integration detects show up under **Settings -> System -> Repairs**:

| Issue | When | Fix |
|---|---|---|
| **To-do list no longer exists** (warning) | Items point at a `todo.*` entity that is gone — checked at startup/entry setup and whenever a todo entity is removed or renamed in the entity registry. | Pick a replacement to-do list for the affected items, or clear their list (this also turns auto-add off). Changes go through `update_item`, so the new list is synced right away. |
| **Database is from a newer version** (error) | The database was written by a newer Simple Inventory release (you downgraded). Setup fails instead of retrying; your data is not touched. | Install the release that created the database (or newer) and restart. |
| **Database upgrade failed** (error) | A schema migration to the current release failed partway through. Setup fails instead of retrying; a snapshot of the database was taken automatically right before the upgrade started. | Confirm to restore that snapshot (your data returns to its state just before the upgrade attempt) and reload every entry. |
| **Data for removed inventories** (warning) | The database still holds inventories whose config entry no longer exists. Lists each one with its item count. | Confirm to permanently delete that data. |
| **Inventory panel needs the Simple Inventory card** (warning) | The [sidebar panel](../README.md#sidebar-panel) is enabled but `<config>/www/community/simple-inventory-card/simple-inventory-panel.js` is missing. The panel is still registered, but cannot load. | Install or update the Simple Inventory card through HACS (or copy its files into that folder), then restart or save the global entry's options again. |
| **Voice sentences need updating** (warning) | An installed [custom-sentences](voice-and-ai-assistants.md#voice--ai-assistants) file is in an older format (any word could name an inventory in it) *and* has been edited, so it wasn't replaced automatically like an unedited one is. | Not auto-fixable: delete the file and reinstall the example voice commands from the integration's options, or bring your edits over to the current example file, then reload the entry. |

Issues are re-checked every time an inventory is set up; an issue whose condition no longer applies is removed automatically.
