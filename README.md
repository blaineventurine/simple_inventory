[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)

# Simple Inventory

A Home Assistant custom integration for managing household inventories. Track items across multiple inventories with per-batch stock (expiry, location, purchase date, price), automatic todo list integration, barcode support, item aliases, locations, categories, and change history.

## Table of Contents

- [Upgrading to 0.11.0](#upgrading-to-0110)
- [Upgrading to 0.10.0](#upgrading-to-0100)
- [Upgrading to 0.8.0](#upgrading-to-080)
- [Installation](#installation)
- [Sidebar Panel](#sidebar-panel)
- [Configuration](#configuration)
- [Features](#features)
- [Sensors](#sensors)
- [Service Calls](#service-calls)
- [WebSocket API](#websocket-api)
- [Diagnostics & Repairs](#diagnostics--repairs)
- [Backups & Restore](#backups--restore)
- [Voice & AI Assistants](#voice--ai-assistants)
- [Automation Examples](#automation-examples)

## Upgrading to 0.11.0

0.11.0 adds [item images](#item-images). On first start the database moves to schema v6: every existing item gets an empty `image` (no photo). Photos are stored in `<config>/simple_inventory/images/`, so they are part of Home Assistant backups. No manual steps are needed; like every schema upgrade it cannot be undone by downgrading. `simple_inventory/get_info` now also reports the `item_images` feature; `api_version` stays `3`.

## Upgrading to 0.10.0

0.10.0 adds a per-item [`icon`](#items). On first start the database moves to schema v5: every existing item gets an empty icon (the card shows its default icon). No manual steps are needed; like every schema upgrade it cannot be undone by downgrading. `simple_inventory/get_info` now also reports the `item_icons` feature; `api_version` stays `3`.

## Upgrading to 0.8.0

0.8.0 introduces [batches](#batches). Before upgrading, note:

- **Automatic database upgrade** — on first start the database moves to schema v4. Each item that has stock becomes one batch carrying its quantity, expiry date, first location, and price; out-of-stock items get no batch and their expiry date is cleared. No manual steps are needed, but the upgrade cannot be undone by downgrading.
- **Update the [Simple Inventory Card](https://github.com/blaineventurine/simple-inventory-card)** to its batches-aware release. Older cards keep working but cannot edit individual batches. A plain restock (e.g. the card's `+` button) of an item that has an expiry date creates a separate batch without an expiry; once an item has several batches, its expiry can only be changed per batch, which needs the batch editor of the new card (or the [`update_batch`](#simple_inventoryupdate_batch) service).
- **Expiry sensors count batches** — the expiring-soon and expired sensors count each expiring batch, so one item with two expiring batches counts twice.
- **Stricter dates** — `expiry_date` and `purchased_at` must be `YYYY-MM-DD` in every service.
- **API version 3** — `simple_inventory/get_info` reports `api_version: 3` (with the `batches` feature).

## Installation

### Via HACS (Recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=blaineventurine&repository=simple_inventory)

or:

1. Add this repository to HACS
2. Install "Simple Inventory"
3. Install the companion card: [Simple Inventory Card](https://github.com/blaineventurine/simple-inventory-card)
4. Restart Home Assistant

### Manual Installation

1. Copy `custom_components/simple_inventory/` to your Home Assistant `custom_components/` directory
2. Restart Home Assistant

## Frontend Card

This integration works best with the companion Lovelace card:
**[Simple Inventory Card](https://github.com/blaineventurine/simple-inventory-card)**

## Sidebar Panel

An optional full-page **Inventory** panel in the Home Assistant sidebar, with one tab per inventory (sorted by name). Each tab shows the same list as the Simple Inventory card.

- **Enable it:** Settings -> Devices & Services -> Simple Inventory -> the **All Items Expiring Soon** (global) entry -> **Configure** -> check **Show the Inventory panel in the sidebar**. Saving the options adds or removes the sidebar entry right away.
- **Admins only:** in the same dialog, check **Only administrators can see the panel** to hide it from non-admin users (default: every user sees it).
- **Requirements:** the panel's code ships with the [Simple Inventory Card](https://github.com/blaineventurine/simple-inventory-card) (`simple-inventory-panel.js`). Install the card through HACS, or copy its release files into `<config>/www/community/simple-inventory-card/` by hand. The panel loads `/api/simple_inventory/panel-loader.js` (no login needed, never cached), which imports `/local/community/simple-inventory-card/simple-inventory-panel.js` stamped with the file's modification time, so a card update reaches the browser on the next page load without restarting Home Assistant.
- **Missing file:** while the panel is enabled but that file is missing, the **Inventory panel needs the Simple Inventory card** repair issue is raised (see [Repairs](#repairs)). It clears on the next restart or options save after the file appears.
- **No global entry, no panel:** the setting lives on the global entry. If you deleted that entry, there is no panel (the global entry is not recreated).

## Configuration

Add via Home Assistant UI: **Settings -> Devices & Services -> Add Integration -> Simple Inventory**

When you create your first inventory, a global device is also created automatically. Each inventory becomes a device with three sensors.

You can edit inventory names, icons, and descriptions in the integration options flow after creation.

## Features

### Items

Each item has a **name** (required) and these optional fields:

| Field | Description |
|---|---|
| `quantity` | Current stock level (supports decimals, e.g. 2.5). Derived: the sum of the item's [batches](#batches) |
| `unit` | Unit of measurement (e.g. "boxes", "L", "kg") |
| `description` | Free-text description |
| `icon` | Icon the card shows for the item, in Home Assistant's `prefix:name` form (e.g. `mdi:apple`). `""` (the default) means the card's default icon |
| `image` | Read-only. `""` when the item has no [photo](#item-images), otherwise a version stamp that changes whenever the photo changes |
| `barcode` | UPC/EAN barcode for scanning |
| `aliases` | Alternate names for the item, usable anywhere the name is accepted (comma-separated) |
| `location` | Where the item is usually stored (supports multiple, comma-separated). Each batch has its own actual location |
| `category` | Item category (supports multiple, comma-separated) |
| `price` | Last known unit price (updated when restocking at a price or editing; survives running out) |
| `expiry_date` | Expiration date (YYYY-MM-DD). Derived: the earliest batch expiry (`""` if none) |
| `expiry_alert_days` | Days before expiry to trigger alerts (applies to every batch of the item) |

### Item Images

Each item can have one photo. Every source is copied into the integration: the photo is decoded, turned upright (EXIF orientation), stripped of metadata and stored as WebP in `<config>/simple_inventory/images/` — `<item_id>.webp` (long edge at most 1024 px), `<item_id>_tile.webp` (at most 384 px, for tile layouts) and `<item_id>_thumb.webp` (at most 128 px). JPEG, PNG, WebP and GIF (first frame) up to 10 MB are accepted; HEIC/AVIF only when the Home Assistant installation's Pillow can open them. Ways to set a photo:

- **Upload** — `POST /api/simple_inventory/image/<item_id>` (below); the card uses it for "Take or choose photo".
- **Product photo** — [`set_item_image_from_barcode`](#simple_inventoryset_item_image_from_barcode) downloads the photo the barcode lookup returns.
- **Media** — [`set_item_image_from_media`](#simple_inventoryset_item_image_from_media) copies a file from Home Assistant's local media folders or an image uploaded to Home Assistant.

[`clear_item_image`](#simple_inventoryclear_item_image) (or `DELETE`) removes the photo. Removing an item or an inventory deletes its photos, and files that no longer belong to an item are cleaned up at startup. Exports only say whether an item has a photo (`image: true/false`); photos are not exported and imports ignore `image`.

The item's `image` field is a version stamp, so clients can cache photos forever and refetch only when the stamp changes. The HTTP endpoints need a Home Assistant access token (`Authorization: Bearer <token>`) but no admin rights:

| Request | Result |
|---|---|
| `GET /api/simple_inventory/image/<item_id>` | The photo (`image/webp`). `?tile=1` returns the tile size (built from the full photo on first request for photos saved before tiles existed). `?thumb=1` returns the thumbnail and wins over `tile`. Any `v` parameter is ignored (use `v=<image stamp>` to bust caches). Sent with `Cache-Control: private, max-age=31536000, immutable`. `404 {"code": "image_not_found"}` when the item has no photo |
| `POST /api/simple_inventory/image/<item_id>` | Multipart form with the file in field `file`. `200 {"image": "<stamp>"}`; `400 {"code": "image_invalid"}` (not a supported image, or no `file` field); `413 {"code": "image_too_large"}` (over 10 MB); `404 {"code": "item_not_found"}` |
| `DELETE /api/simple_inventory/image/<item_id>` | `200 {"image": ""}`, also when there was no photo; `404 {"code": "item_not_found"}` for an unknown item |

### Batches

An item's stock is held in **batches**. A batch is one lot of the item with its own **quantity**, **expiry date**, **location**, **purchase date** (`purchased_at`), and **unit price** — e.g. two cartons of milk bought last week that expire on the 3rd sitting in the Fridge, and one bought today that expires on the 10th in the Garage fridge. The item's `quantity` is the sum of its batches and its `expiry_date` is the earliest batch expiry; both remain in the API for compatibility.

- **Restocking** (`add_item`, `increment_item`, `scan_barcode` increment, voice "add") adds stock as a batch. It **merges** into an existing batch when the expiry date, location, and unit price all match (the merged batch keeps the earliest purchase date); otherwise a new batch is created. Unspecified values default to: location = the given `location`, else the item's first usual location; expiry = none; unit price = the item's last known price (a positive `price` updates it).
- **Consuming** (`decrement_item`, `scan_barcode` decrement, voice "remove") takes from the batch expiring **soonest first**; ties go to the oldest purchase date, and batches without an expiry date are used last. A larger amount continues into the next batch in the same order.
  - `location` restricts consumption to batches stored there (`no_stock_at_location` error if there are none; nothing is changed).
  - `batch_id` consumes from exactly that batch (`batch_not_found` error if it doesn't exist) and takes precedence over `location`.
- A batch that reaches 0 is **deleted**; the item remains with quantity 0. History keeps the record.
- **Editing** a batch is done with [`update_batch`](#simple_inventoryupdate_batch) (quantity, expiry, location, unit price, purchase date) and [`remove_batch`](#simple_inventoryremove_batch).
- **Moving** stock to another location of the same inventory is done with [`transfer_item`](#simple_inventorytransfer_item) (0.9.0+): part of a batch, a whole batch, everything at one location, or the soonest-expiring stock wherever it is. Moved stock keeps its expiry date, unit price and purchase date.
- **Expiry** is evaluated per batch: each expiring or expired batch is its own entry on the [expiry sensors](#sensors), so an item with one batch expiring tomorrow and one next month is only partly "expiring soon".
- **Value**: `total_value` is the sum of each batch's quantity × its unit price.
- `update_item` still accepts scalar `quantity`, `expiry_date` and `price` — see [`update_item`](#simple_inventoryupdate_item) for how they map onto batches.

Item responses (`get_items`, WebSocket `list_items`/`get_item`/`subscribe`) include a `batches` list (in consumption order) and `stocked_locations` (the distinct locations that currently hold stock, in the same order).

### Multi-Value Locations and Categories

Items can belong to multiple locations and categories. Pass comma-separated values:

```yaml
location: "Pantry, Kitchen"
category: "Snacks, Bulk Items"
```

The API returns both scalar fields (`location`, `category` with the first value) and array fields (`locations`, `categories` with all values) for backward compatibility.

### Expiration Tracking

Set an `expiry_date` and `expiry_alert_days` on any item. Expiry dates belong to [batches](#batches): each batch is checked against the item's `expiry_alert_days`, and when its remaining days are at or below that threshold the batch appears on the expiry sensors (one entry per batch). Empty batches don't exist, so out-of-stock items never alert. Days until expiry are counted from today's date in Home Assistant's configured time zone, and the expiry sensors recompute at local midnight, so batches move to "expiring" or "expired" on date rollover without any other inventory change.

### Auto-Add to Todo List

Automatically add items to a Home Assistant todo list when stock drops below a threshold. Configure these fields:

| Field | Description |
|---|---|
| `auto_add_enabled` | Enable/disable auto-add for this item |
| `auto_add_to_list_quantity` | Quantity threshold that triggers adding to the list |
| `desired_quantity` | Target stock level (controls how much to buy) |
| `todo_list` | Target todo list entity (e.g. `todo.shopping_list`); must be a `todo.*` entity or empty |
| `todo_quantity_placement` | Where to show the needed quantity: `"name"` (e.g. "Milk (x4)"), `"description"`, or `"none"` |

**How it works:**

- When `quantity` (the total across all batches) drops to or below `auto_add_to_list_quantity`, the item is added to your todo list. A threshold of `0` means "add when empty".
- When `desired_quantity > 0` (fixed mode): the todo shows the desired quantity, and the item is removed from the list when `quantity >= desired_quantity`. Changing `desired_quantity` refreshes the existing entry.
- When `desired_quantity = 0` (threshold mode): the todo shows `threshold - quantity + 1`, updates live on each change, and the item is removed when `quantity > threshold`
- Every change re-checks the item against its current stock, whichever way it went: an item still at or below its threshold after a restock goes back on the list if its entry was deleted, and a stocked item's leftover entry is removed on its next change
- Removing the item, renaming it, moving it to another `todo_list`, or disabling auto-add removes its existing todo entry
- Imports sync the todo entries of the items they add or change, like the services do
- When a todo list cannot be read (its `todo.get_items` call fails), that sync is skipped with one warning in the log, so no duplicate entry is added and nothing is removed. A skipped add or refresh is redone by the item's next change; a skipped removal of an old entry (item removed, renamed, moved to another list, or auto-add disabled) is not retried, so remove that entry by hand (the warning names it)
- Notes you type on a todo entry are preserved, unless `todo_quantity_placement` is `"description"` (the integration then owns the description)

**Note:** The core Shopping List integration does not support item descriptions, so description-based features only work with todo lists that do (for example Local To-do). The integration checks each list's supported features, not its entity id.

### Description with Inventory ID

Enable `auto_add_id_to_description_enabled` to append the inventory ID to item descriptions. This is useful when scanning barcodes from todo lists — the ID lets automations route the item back to the correct inventory. See [this issue](https://github.com/blaineventurine/simple_inventory/issues/19) for the use case. It also keeps same-named items from different inventories as separate entries on a shared todo list.

### Barcodes

Items can have multiple barcodes associated with them (comma-separated in the API). Most service calls accept either `name` or `barcode` to identify an item. Two dedicated barcode services make scanning workflows easy:

- **`lookup_by_barcode`** — Search for an item by barcode across all inventories
- **`scan_barcode`** — Scan a barcode and perform an action (increment, decrement, or lookup) with automatic cross-inventory resolution

> **Important:** Barcodes with leading zeros (e.g. `0123456`) **must be quoted** in YAML automations and scripts. Unquoted values like `barcode: 0123456` are interpreted as integers by YAML, stripping the leading zero and matching the wrong item. Always use `barcode: "0123456"`. This does not affect the HA service call UI or the WebSocket API, which handle strings correctly.

### Item Aliases

Items can have alternate names ("oats", "steel-cut oats", "hot cereal" for
an item stored as "Oatmeal") that resolve to the same item wherever a name
is accepted — service calls, voice commands, and LLM tool calls. Set them
via the `aliases` field on `add_item`/`update_item` (comma-separated, e.g.
`"oats, steel-cut oats, hot cereal"`); passing an empty string clears all
aliases.

Every service call and voice/LLM command that looks up an *existing* item
by name (`increment_item`, `decrement_item`, `update_item`'s `old_name`)
resolves aliases automatically, using the same typo-tolerant matching
already used for real names (exact match, then substring, then
closest-match) — no per-command setup needed. `remove_item` is stricter:
it only accepts an exact name or alias (case-insensitive), so a typo can
never delete a different item.

`add_item`'s own `name` field is never alias-resolved. Adding an item whose
name already exists in the inventory (case-insensitive with Unicode case
folding, so "čokolada" clashes with "Čokolada" and "STRASSE" with "Straße")
is rejected with an
error — use `increment_item` or `update_item` instead. Renaming an item onto
another item's name is rejected too.

Names and aliases must not clash within an inventory, compared
case-insensitively (Unicode case folding) exactly as lookups, todo-list
matching and [search](#simple_inventorysearch) compare them. An alias already used by another
item as an alias or as its name is rejected, and so is an item name (when
adding, renaming or importing) that is already another item's alias, e.g.
"Oats" while "Oatmeal" has the alias "oats". An alias equal to the item's own
name is allowed. Data stored before this check existed can still clash: then a lookup
reports the match as ambiguous (listing the items) rather than silently
picking one, and editing the item only re-checks the aliases you add.

### Change History

Every add, increment, decrement, and quantity change made via `update_item`, `update_batch`, or `remove_batch` (event type `update`) is recorded with before/after quantities and timestamps. Imports record `import` events. A change that touches several batches records **one row per batch**, each carrying that batch's `batch_id` and location (`location_from` for consumption, `location_to` for restocks). The recorded `amount` is the change actually applied (a decrement clamped at zero records only what was removed; a no-op records nothing). Removing an item deletes its history with it. Query history via the WebSocket API. Moves made with [`transfer_item`](#simple_inventorytransfer_item) are recorded as `transfer` events, one per source batch, with that batch's `batch_id`, `location_from` and the destination as `location_to`; they don't change the item's quantity (`quantity_before` equals `quantity_after`) and consumption analytics ignore them.

### Consumption Analytics

Track how fast you consume items. The integration calculates consumption rates based on decrement history:

- **Daily / weekly consumption rate** — How much you use per day or week
- **Days until depletion** — Estimated days before the item runs out at the current rate
- **Average restock interval** — How often you typically restock the item
- **Total consumed / events tracked** — Lifetime consumption totals. Events are counted per history row, and history is recorded per batch, so one decrement that consumes from two batches counts as two events (`decrement_count: 2`)

Rates can be calculated over a configurable time window (e.g. last 30, 60, or 90 days) or across all history. With a window, rates are divided by the shorter of the window and the time since the first decrement inside it (minimum one day), so a short history isn't diluted by an empty window. Spend rates are measured from the first priced restock. The companion card shows this data in a "Consumption" tab in the item history modal. You can also query rates via the service call or WebSocket API for use in automations.

### Pricing

Track item prices to see inventory value and spending trends. Each item has an optional `price` field holding the last known unit price, and every [batch](#batches) records the unit price it was bought at.

- **Unit price**: Set when adding or editing an item. Update it whenever the price changes (e.g. at the next purchase).
- **Price on restock**: `increment_item`, `decrement_item`, and `scan_barcode` accept an optional `price` parameter. When provided, it updates the item's stored unit price and records the price on the history event; on a restock it is also the new batch's unit price. A positive `unit_price` set via `update_batch` also becomes the item's price.
- **Total value**: Retrievable via the `get_items` service call. Computed per batch as quantity × the batch's unit price; batches with a unit price of 0 are excluded.
- **Spend analytics**: The consumption tab shows spend data computed from restocking (increment/add) events that have a price recorded:
  - **Daily Spend** — Average daily purchasing cost over the observation window
  - **Weekly Spend** — Average weekly purchasing cost
  - **Total Spend** — Total money spent purchasing the item

> **Note:** A price of 0 means "no price set", not "free". Items with no price are excluded from value and spend calculations.

### Events

The integration fires Home Assistant events on key inventory transitions, enabling automations without polling sensor state.

| Event | When it fires |
|---|---|
| `simple_inventory_item_added` | A new item is added to an inventory |
| `simple_inventory_item_removed` | An item is deleted from an inventory |
| `simple_inventory_item_quantity_changed` | Any increment or decrement |
| `simple_inventory_item_depleted` | Quantity drops to 0 (was > 0) |
| `simple_inventory_item_restocked` | Quantity rises above 0 (was 0) |
| `simple_inventory_item_transferred` | Stock is moved to another location (`transfer_item`, voice "move"). Moving never fires the quantity, depleted or restocked events |
| `simple_inventory_item_added_to_list` | Item is added to a todo list, or its quantity-needed display is updated while already on the list |
| `simple_inventory_item_removed_from_list` | Item is removed from a todo list |
| `simple_inventory_updated`, `simple_inventory_updated_<inventory_id>` | Internal refresh signals after any change (general, and per inventory); no payload. The sensors refresh on them and the `simple_inventory/subscribe` WebSocket command forwards them |

**Event payloads:**

`item_added`: `item_name`, `inventory_id`, `quantity`
`item_removed`: `item_name`, `inventory_id`
`item_quantity_changed`: `item_name`, `inventory_id`, `quantity_before`, `quantity_after`, `amount`, `direction` (`"increment"` or `"decrement"`)
`item_depleted`: `item_name`, `inventory_id`, `previous_quantity`
`item_restocked`: `item_name`, `inventory_id`, `quantity`
`item_transferred`: `item_name`, `inventory_id`, `amount`, `from_location` (`""` when the stock came from several locations), `to_location`
`item_added_to_list`: `item_name`, `inventory_id`, `quantity`, `todo_list`, `quantity_needed`
`item_removed_from_list`: `item_name`, `inventory_id`, `quantity`, `todo_list`

### Import and Export

Export your inventory to JSON or CSV, and import data back with configurable merge strategies (`skip`, `overwrite`, or `merge_quantities`). Available via the WebSocket API, or the [`export`](#simple_inventoryexport) service for automation-triggered exports. Exports include every field, including all locations, categories, barcodes, aliases, and [batches](#batches), so an export can be re-imported without loss. Photos are the exception: `image` is exported as `true`/`false` (CSV: `1`/`0`) and ignored on import. Older exports without batches still import: their scalar quantity becomes one batch. See [`simple_inventory/import`](#simple_inventoryimport) for validation and merge details. Pass `dry_run: true` to the WebSocket `import` command to preview a file's effect (added/updated/skipped counts and any errors) without writing anything.

## Sensors

### Per-Inventory Sensors

Each inventory creates three sensors:

**`sensor.<name>_inventory`** — Main inventory sensor
- **State**: Total quantity across all items
- **Attributes**:
  - `inventory_id` — The config entry ID
  - `description` — The inventory description
  - `total_items` — Number of distinct items
  - `total_quantity` — Sum of all quantities
  - `below_threshold` — Items that need restocking, each with `name`, `quantity`, `threshold`, `desired_quantity`, `quantity_needed`, `unit`, `category`. An item is included when its quantity is at or below its auto-add threshold; a threshold of `0` only counts when auto-add is enabled.
  - `expiring_soon` — Count of batches within their item's alert threshold, expired batches included

**`sensor.<name>_items_expiring_soon`** — Expiry alert sensor
- **State**: Count of batches within their item's alert threshold but not yet expired
- **Icon**: Progressive severity by the soonest-expiring batch: `mdi:calendar-alert` (expires within 1 day), `mdi:calendar-clock` (within 3 days), `mdi:calendar-week` (later), `mdi:calendar-check` when none are expiring
- **Attributes**:
  - `expiring_items` — One entry per batch expiring soon (days_until_expiry ≥ 0), soonest first, with the item's details plus `inventory_id`, `inventory` (the inventory's name), `batch_id`, `quantity` (of that batch), `location` (of that batch), `expiry_date`, `days_until_expiry`, `threshold` (the item's alert days)
  - `total_expiring` — Count of batches
  - `inventory_id`, `inventory_name`

**`sensor.<name>_expired_items`** — Expired items sensor
- **State**: Count of batches past their expiration date
- **Icon**: `mdi:calendar-remove` (fixed)
- **Attributes**:
  - `expired_items` — One entry per expired batch, most overdue first (same fields as above)
  - `total_expired` — Count of batches
  - `inventory_id`, `inventory_name`

### Global Sensors

"All inventories" means every enabled inventory entry, here and everywhere else (voice and AI answers, `lookup_by_barcode`, `scan_barcode`, `get_items_from_all_inventories`, search and the panel's Home tab). A disabled inventory, and data left behind by a deleted one, are never counted or listed.

**`sensor.all_items_expiring_soon`** — Aggregates expiring-soon batches across ALL inventories
- **State**: Count of batches within their item's alert threshold but not yet expired
- **Icon**: Progressive severity, as for the per-inventory sensor (`mdi:calendar-alert` → `mdi:calendar-clock` → `mdi:calendar-week` → `mdi:calendar-check`)
- **Attributes**:
  - `expiring_items`, `expired_items` — Aggregated per-batch lists (same fields as the per-inventory sensors; `inventory` is the batch's inventory name)
  - `total_expiring`, `total_expired` — Counts of those batches
  - `next_expiring` — The soonest-expiring entry (`null` when none)
  - `oldest_expired` — The most overdue entry (`null` when none)
  - `inventories_count` — Number of inventories with expiring or expired batches

**`sensor.all_expired_items`** — Aggregates expired batches across ALL inventories
- **State**: Count of batches past their expiration date across all inventories
- **Icon**: `mdi:calendar-remove` (fixed)
- **Attributes**:
  - `expired_items` — Aggregated per-batch list of expired entries, most overdue first
  - `total_expired` — Count of batches
  - `oldest_expired` — The most overdue entry (`null` when none)
  - `inventories_count` — Number of inventories with expired batches

## Service Calls

All services are under the `simple_inventory` domain. You can find your inventory ID by going to **Developer Tools -> States** and filtering for "inventory" — the ID is shown in the sensor attributes.

### `simple_inventory.add_item`

Add a new item to an inventory.

```yaml
service: simple_inventory.add_item
data:
  inventory_id: "01JYFPCDMBRBRK4MB3C26S2FKH"
  name: "Frozen Pizza"
  icon: "mdi:pizza"
  quantity: 5
  unit: "boxes"
  category: "Frozen Foods"
  location: "Basement Freezer"
  price: 8.99
  barcode: "012345678901"
  aliases: "pizza, pepperoni pizza"
  expiry_date: "2026-06-15"
  expiry_alert_days: 7
  auto_add_enabled: true
  auto_add_to_list_quantity: 2
  desired_quantity: 5
  todo_list: "todo.grocery_list"
  todo_quantity_placement: "name"
  description: "Family size pepperoni"
```

Only `inventory_id` and `name` are required. All other fields are optional. A non-zero `quantity` becomes the item's first [batch](#batches), using `expiry_date`, the first `location`, and `price`.

### `simple_inventory.remove_item`

Remove an item. Specify either `name` or `barcode`. `name` must match the item's name or one of its aliases exactly (case-insensitive); no fuzzy matching is applied.

```yaml
service: simple_inventory.remove_item
data:
  inventory_id: "01JYFPCDMBRBRK4MB3C26S2FKH"
  name: "Frozen Pizza"
```

### `simple_inventory.increment_item`

Increase an item's quantity by adding a [batch](#batches) (or merging into a matching one). Supports decimal amounts. Optionally pass `price` to update the item's unit price (e.g. when restocking at a new price).

```yaml
service: simple_inventory.increment_item
data:
  inventory_id: "01JYFPCDMBRBRK4MB3C26S2FKH"
  name: "Frozen Pizza"
  amount: 3
  price: 9.49
  expiry_date: "2026-09-30"
  location: "Garage Freezer"
  purchased_at: "2026-07-01"
```

| Field | Description |
|---|---|
| `amount` | Amount to add (default 1) |
| `price` | Unit price of this stock; also becomes the item's price |
| `expiry_date` | Expiry of the new stock (default: none) |
| `location` | Where the new stock is stored (default: the item's first usual location) |
| `purchased_at` | Purchase date `YYYY-MM-DD` (default: today) |

The stock merges into an existing batch with the same expiry date, location, and unit price; otherwise a new batch is created.

You can also use `barcode` instead of `name`:

```yaml
service: simple_inventory.increment_item
data:
  inventory_id: "01JYFPCDMBRBRK4MB3C26S2FKH"
  barcode: "012345678901"
  amount: 1
```

### `simple_inventory.decrement_item`

Decrease an item's quantity. Stock is taken from the batch expiring soonest (see [Batches](#batches)). Accepts `name`/`barcode`, `amount`, and `price` like `increment_item`, plus:

| Field | Description |
|---|---|
| `location` | Only consume batches stored at this location (`no_stock_at_location` if none) |
| `batch_id` | Consume from exactly this batch (`batch_not_found` if it doesn't exist); takes precedence over `location` |

```yaml
service: simple_inventory.decrement_item
data:
  inventory_id: "01JYFPCDMBRBRK4MB3C26S2FKH"
  name: "Frozen Pizza"
  amount: 1
  location: "Garage Freezer"
```

### `simple_inventory.update_item`

Update any fields on an existing item. Use `old_name` to identify the item (also matches aliases) and `name` for the (possibly new) name. Pass `aliases` to replace all of the item's aliases (empty string clears them). Pass `icon: ""` to go back to the default icon.

```yaml
service: simple_inventory.update_item
data:
  inventory_id: "01JYFPCDMBRBRK4MB3C26S2FKH"
  old_name: "Frozen Pizza"
  name: "Frozen Pizza"
  icon: "mdi:pizza"
  aliases: "pizza night, pepperoni pizza"
  category: "Frozen Foods, Quick Meals"
  location: "Kitchen Freezer"
  expiry_date: "2026-08-01"
```

`location` here sets the item's usual storage places; it does not move existing batches (use `update_batch`). The scalar stock fields map onto [batches](#batches):

- `quantity` — an increase adds a batch (with the requested `expiry_date`, the item's price, and the item's first usual location); a decrease consumes batches in soonest-expiry order. Recorded as `update` events.
- `expiry_date` / `price` — applied to the batch when the item has exactly one. A value equal to the current one is ignored, so re-saving an unchanged form is a no-op. Changing them on an item with several batches is rejected with `batch_required` — edit the batch with `update_batch` instead. Changing `expiry_date` on an item with no stock is rejected with `no_stock_for_expiry` — restock it with an expiry date instead (a `price` change there only sets the item's price).

### `simple_inventory.update_batch`

Edit one batch. `batch_id` comes from the item's `batches` list. Specify the inventory by `inventory_id` or `inventory_name`.

```yaml
service: simple_inventory.update_batch
data:
  inventory_id: "01JYFPCDMBRBRK4MB3C26S2FKH"
  batch_id: "6f1c2e0a-3b7d-4f5e-9a12-0c4d8e7b9a31"
  quantity: 2
  expiry_date: "2026-09-15"
  location: "Kitchen Freezer"
  unit_price: 8.49
  purchased_at: "2026-07-01"
```

All fields other than the inventory and `batch_id` are optional; only the ones given change. `quantity: 0` deletes the batch. A positive `unit_price` also becomes the item's price. An empty `location` clears the batch's location; `purchased_at`, when given, must be a `YYYY-MM-DD` date (a blank value is rejected). Quantity changes are recorded as `update` history events. Unknown batches (or batches from another inventory) raise `batch_not_found`.

### `simple_inventory.remove_batch`

Delete one batch (recorded as an `update` event taking its quantity away).

```yaml
service: simple_inventory.remove_batch
data:
  inventory_id: "01JYFPCDMBRBRK4MB3C26S2FKH"
  batch_id: "6f1c2e0a-3b7d-4f5e-9a12-0c4d8e7b9a31"
```

### `simple_inventory.transfer_item`

Move stock of an item to another location in the same inventory (0.9.0+). Identify the item by `name` (or alias) or `barcode`, and the inventory by `inventory_id` or `inventory_name`.

| Field | Description |
|---|---|
| `to_location` | **Required.** Where the stock goes. A new name creates the location, and the destination is added to the item's usual locations if missing (the first usual location stays first) |
| `amount` | How much to move (greater than 0). Omit it to move everything at the source |
| `batch_id` | Move from exactly this batch (`batch_not_found` if it isn't one of the item's batches); takes precedence over `from_location` |
| `from_location` | Move only stock stored here, soonest expiry first (`no_stock_at_location` if there is none) |

Without `batch_id` or `from_location`, the soonest-expiring stock that is **not already at the destination** is moved, continuing into the next batch in [consumption order](#batches).

```yaml
service: simple_inventory.transfer_item
data:
  inventory_id: "01JYFPCDMBRBRK4MB3C26S2FKH"
  name: "Milk"
  amount: 2
  from_location: "Fridge"
  to_location: "Garage Fridge"
```

Moved stock keeps its expiry date, unit price and purchase date. At the destination it joins a batch with the same expiry date and unit price (keeping the earliest purchase date); a source batch that is emptied is deleted. The item's total quantity doesn't change, so no quantity, depleted or restocked events fire and todo lists are left alone; one [`simple_inventory_item_transferred`](#events) event fires instead, and each source batch gets a `transfer` history row.

Nothing is changed when the move can't be made:

- `insufficient_stock` — the source holds less than `amount` (or nothing at all)
- `same_location` — the source is already the destination
- `batch_not_found`, `no_stock_at_location`, `item_not_found` — as for `decrement_item`

### `simple_inventory.set_item_image_from_barcode`

Use the product photo of a barcode lookup as the item's [photo](#item-images) (0.11.0+). Identify the item by `name` (or alias, exact match) or `barcode`, and the inventory by `inventory_id` or `inventory_name`. `lookup_barcode` picks the barcode to look up; it must be one of the item's barcodes and defaults to its first one (sorted). The lookup uses the [configured provider](#simple_inventoryset_barcode_provider_config) (or all of them); the first result with a photo wins. Only that photo URL is fetched (`http`/`https`, at most 10 MB within 10 seconds) — the service never takes a URL from the caller.

```yaml
service: simple_inventory.set_item_image_from_barcode
data:
  inventory_id: "01JYFPCDMBRBRK4MB3C26S2FKH"
  name: "Milk"
```

Errors: `image_not_found` (the item has no barcode, or the lookup has no photo), `barcode_not_on_item`, `image_download_failed`, `image_too_large`, `image_invalid`.

### `simple_inventory.set_item_image_from_media`

Copy an image from Home Assistant's local media folders (`media_dirs`, e.g. `/media`) or one uploaded through Home Assistant's own image upload (`media-source://image_upload/<id>`, stored as `<config>/image/<id>/original`) as the item's [photo](#item-images) (0.11.0+). Other media sources (cameras, TTS, add-ons) are rejected with `unsupported_media_source`, as is anything outside those folders and any image upload id that isn't 32 lowercase hex characters.

```yaml
service: simple_inventory.set_item_image_from_media
data:
  inventory_id: "01JYFPCDMBRBRK4MB3C26S2FKH"
  name: "Milk"
  media_content_id: "media-source://media_source/local/pantry/milk.jpg"
```

### `simple_inventory.clear_item_image`

Remove the item's [photo](#item-images) (0.11.0+); does nothing when it has none.

```yaml
service: simple_inventory.clear_item_image
data:
  inventory_id: "01JYFPCDMBRBRK4MB3C26S2FKH"
  barcode: "012345678901"
```

### `simple_inventory.get_items`

Retrieve all items for a specific inventory. Supports `response_variable` for use in automations and scripts.

Specify the inventory by ID or name, but not both.

**By ID** (recommended — unambiguous):

```yaml
service: simple_inventory.get_items
data:
  inventory_id: "01JYFPCDMBRBRK4MB3C26S2FKH"
response_variable: result
```

Find your inventory ID in **Developer Tools → States**: filter for your inventory sensor and read the `inventory_id` attribute.

**By name** (case-insensitive match against the name you gave during setup):

```yaml
service: simple_inventory.get_items
data:
  inventory_name: "Freezer"
response_variable: result
```

This matches the inventory's creation name — **not** the sensor entity ID or its friendly name. If your sensor is `sensor.freezer_inventory`, the inventory name is `Freezer`, not `freezer_inventory` or `Freezer Inventory` (the sensor appends " Inventory" to the display name automatically).

Example response:

```json
{
  "items": [
    {
      "name": "Frozen Pizza",
      "icon": "mdi:pizza",
      "quantity": 5.0,
      "unit": "boxes",
      "category": "Frozen Foods",
      "categories": ["Frozen Foods", "Quick Meals"],
      "location": "Kitchen Freezer",
      "locations": ["Kitchen Freezer"],
      "expiry_date": "2026-06-15",
      "expiry_alert_days": 7,
      "auto_add_enabled": true,
      "auto_add_to_list_quantity": 2.0,
      "desired_quantity": 5.0,
      "todo_list": "todo.grocery_list",
      "todo_quantity_placement": "name",
      "price": 8.99,
      "description": "Family size pepperoni",
      "barcode": "012345678901",
      "barcodes": ["012345678901"],
      "aliases": ["pepperoni pizza", "pizza"],
      "batches": [
        {
          "id": "6f1c2e0a-3b7d-4f5e-9a12-0c4d8e7b9a31",
          "quantity": 3.0,
          "expiry_date": "2026-06-15",
          "location": "Kitchen Freezer",
          "unit_price": 8.99,
          "purchased_at": "2026-05-01"
        },
        {
          "id": "a0b9c8d7-1e2f-4a3b-8c4d-5e6f7a8b9c0d",
          "quantity": 2.0,
          "expiry_date": "",
          "location": "Basement Freezer",
          "unit_price": 9.49,
          "purchased_at": "2026-05-20"
        }
      ],
      "stocked_locations": ["Kitchen Freezer", "Basement Freezer"]
    }
  ]
}
```

Note the dual fields: `category`/`categories` and `location`/`locations`. The singular fields contain only the first value for backward compatibility. Prefer the array fields. `locations` are the item's usual storage places; `stocked_locations` are where its batches actually are.

`quantity` and `expiry_date` are derived from `batches` (sum and earliest expiry). `batches` are listed in consumption order (soonest expiry first, then oldest purchase, no-expiry last); a batch without an expiry has `expiry_date: ""` and one without a location has `location: ""`.

### `simple_inventory.get_items_from_all_inventories`

Retrieve items from every inventory at once. Supports `response_variable` for use in automations and scripts.

```yaml
service: simple_inventory.get_items_from_all_inventories
response_variable: result
```

Example response:

```json
{
  "inventories": [
    {
      "inventory_id": "01JYFPCDMBRBRK4MB3C26S2FKH",
      "inventory_name": "Kitchen Freezer",
      "description": "Frozen items",
      "items": [
        {
          "name": "Frozen Pizza",
          "quantity": 5.0,
          "unit": "boxes"
        }
      ]
    }
  ]
}
```

### `simple_inventory.get_inventory_consumption_rates`

Get consumption analytics for every item in an inventory at once, plus a summary. Supports `response_variable` for use in automations and scripts.

```yaml
service: simple_inventory.get_inventory_consumption_rates
data:
  inventory_id: "01JYFPCDMBRBRK4MB3C26S2FKH"
  window_days: 30
response_variable: rates
```

Only `inventory_id` is required (this service does not accept `inventory_name`). Omit `window_days` to use all history.

Example response:

```json
{
  "inventory_id": "01JYFPCDMBRBRK4MB3C26S2FKH",
  "window_days": 30,
  "items": [
    {
      "item_name": "Frozen Pizza",
      "current_quantity": 3.0,
      "unit": "boxes",
      "decrement_count": 12,
      "total_consumed": 18.0,
      "window_days": 30,
      "daily_rate": 0.6,
      "weekly_rate": 4.2,
      "days_until_depletion": 5.0,
      "avg_restock_days": 14.0,
      "has_sufficient_data": true,
      "total_spend": 53.94,
      "daily_spend_rate": 1.8,
      "weekly_spend_rate": 12.6
    }
  ],
  "summary": {
    "total_items_tracked": 1,
    "total_consumed": 18.0,
    "most_consumed": [
      { "item_name": "Frozen Pizza", "total_consumed": 18.0, "daily_rate": 0.6 }
    ],
    "running_out_soonest": [
      { "item_name": "Frozen Pizza", "days_until_depletion": 5.0, "current_quantity": 3.0 }
    ]
  }
}
```

`items` has one entry per item in the inventory (sorted by name, including items with no history), with the same fields as [`get_item_consumption_rates`](#simple_inventoryget_item_consumption_rates). In `summary`, `total_items_tracked` counts items with at least one decrement in the window, `most_consumed` lists the top five of those by `total_consumed`, and `running_out_soonest` lists the five items with the smallest `days_until_depletion`.

### `simple_inventory.get_item_consumption_rates`

Get consumption analytics for a specific item. Requires at least 2 decrement events to produce meaningful data. Supports `response_variable` for use in automations and scripts.

```yaml
service: simple_inventory.get_item_consumption_rates
data:
  inventory_id: "01JYFPCDMBRBRK4MB3C26S2FKH"
  name: "Frozen Pizza"
  window_days: 30
response_variable: rates
```

Only `inventory_id` and `name` are required. Omit `window_days` to use all history.

Example response:

```json
{
  "item_name": "Frozen Pizza",
  "current_quantity": 3.0,
  "unit": "boxes",
  "decrement_count": 12,
  "total_consumed": 18.0,
  "window_days": 30,
  "daily_rate": 0.6,
  "weekly_rate": 4.2,
  "days_until_depletion": 5,
  "avg_restock_days": 14.0,
  "has_sufficient_data": true,
  "total_spend": 53.94,
  "daily_spend_rate": 1.80,
  "weekly_spend_rate": 12.58
}
```

| Field | Description |
|---|---|
| `daily_rate` | Average units consumed per day (null if insufficient data) |
| `weekly_rate` | Average units consumed per week (null if insufficient data) |
| `days_until_depletion` | Estimated days until quantity reaches 0 (null if rate is 0 or insufficient data) |
| `avg_restock_days` | Average days between increment events (null if fewer than 2 restocks) |
| `has_sufficient_data` | `true` if there are at least 2 decrement events to calculate rates |
| `total_spend` | Total money spent purchasing this item (null if no priced restock events) |
| `daily_spend_rate` | Average daily purchasing cost (null if no priced restock events) |
| `weekly_spend_rate` | Average weekly purchasing cost (null if no priced restock events) |

### `simple_inventory.lookup_by_barcode`

Search for an item by barcode across all inventories. Useful for finding which inventory contains a scanned item. Supports `response_variable` for use in automations and scripts.

```yaml
service: simple_inventory.lookup_by_barcode
data:
  barcode: "012345678901"
response_variable: result
```

Example response:

```json
{
  "items": [
    {
      "name": "Frozen Pizza",
      "quantity": 5.0,
      "inventory_id": "01JYFPCDMBRBRK4MB3C26S2FKH",
      "inventory_name": "Kitchen Freezer"
    }
  ]
}
```

Returns an empty list if no match is found. If the same barcode exists in multiple inventories, all matches are returned.

### `simple_inventory.lookup_barcode_product`

Look up product information for a barcode, for example to pre-fill a new item. Supports `response_variable` for use in automations and scripts.

```yaml
service: simple_inventory.lookup_barcode_product
data:
  barcode: "012345678901"
response_variable: product
```

If an item in any inventory already has the barcode, only that item is reported (as provider `inventory`, with its `name` and, when set, `description`, `category` and `unit`) and no external database is queried. Otherwise the external providers are queried in parallel: only the one selected with [`simple_inventory/set_barcode_provider_config`](#simple_inventoryset_barcode_provider_config), or all of `openfoodfacts`, `openbeautyfacts`, `openpetfoodfacts` and `upcitemdb` when none is selected.

Example response:

```json
{
  "barcode": "012345678901",
  "results": [
    {
      "provider": "openfoodfacts",
      "found": true,
      "product": {
        "name": "Frozen Pizza",
        "brand": "Acme",
        "category": "Frozen Foods, Pizzas",
        "unit": "400 g",
        "image_url": "https://images.openfoodfacts.org/..."
      }
    },
    { "provider": "upcitemdb", "found": false }
  ]
}
```

There is one result per queried provider; a provider that does not know the barcode, or fails, reports `"found": false`. `product` always has `name`; `description`, `category`, `brand`, `unit` and `image_url` appear when the provider supplies them.

### `simple_inventory.scan_barcode`

Scan a barcode and perform an action on the matched item. Automatically resolves which inventory contains the barcode. Supports `response_variable` for use in automations and scripts.

```yaml
service: simple_inventory.scan_barcode
data:
  barcode: "012345678901"
  action: "increment"
  amount: 1
response_variable: result
```

| Field | Required | Description |
|---|---|---|
| `barcode` | Yes | The barcode to scan |
| `action` | Yes | `"increment"`, `"decrement"`, or `"lookup"` |
| `amount` | No | Amount to increment/decrement (default: 1, ignored for lookup) |
| `price` | No | Unit price to record for this transaction (updates the item's stored price) |
| `inventory_id` | No | Scope the search to a specific inventory. Required if the barcode exists in multiple inventories. |
| `expiry_date` | No | Increment only: expiry of the new stock |
| `location` | No | Increment: where the new stock is stored. Decrement: only consume batches there |
| `purchased_at` | No | Increment only: purchase date `YYYY-MM-DD` |
| `batch_id` | No | Decrement only: consume from exactly this batch |

Increments and decrements follow the [batch rules](#batches). They need the item's inventory to be loaded (`inventory_not_loaded` otherwise, e.g. for a disabled inventory); a `lookup` without `inventory_id` answers for an item in any inventory, like [`lookup_by_barcode`](#simple_inventorylookup_by_barcode).

Example response (increment/decrement):

```json
{
  "action": "increment",
  "success": true,
  "item_name": "Frozen Pizza",
  "inventory_id": "01JYFPCDMBRBRK4MB3C26S2FKH",
  "amount": 1.0
}
```

Example response (lookup):

```json
{
  "action": "lookup",
  "item": {
    "name": "Frozen Pizza",
    "quantity": 5.0,
    "inventory_id": "01JYFPCDMBRBRK4MB3C26S2FKH",
    "inventory_name": "Kitchen Freezer"
  },
  "inventory_id": "01JYFPCDMBRBRK4MB3C26S2FKH"
}
```

**Error cases:**
- Barcode not found in any inventory: raises an error
- Barcode found in multiple inventories without `inventory_id`: raises an error listing the inventories

### `simple_inventory.backup_database`

Take an on-demand snapshot of the shared database, in addition to the automatic pre-migration one. Snapshots live in `<config>/simple_inventory/backups/`; only the 3 most recent (automatic or manual) are kept.

```yaml
service: simple_inventory.backup_database
response_variable: result
```

Example response:

```json
{
  "snapshot": "manual_1731082013456789012.db"
}
```

### `simple_inventory.restore_database`

Restore the database from a snapshot, replacing all current data, then reload every Simple Inventory config entry. Omit `snapshot` to restore the most recent one (automatic or manual).

```yaml
service: simple_inventory.restore_database
data:
  snapshot: "manual_1731082013456789012.db"
response_variable: result
```

| Field | Required | Description |
|---|---|---|
| `snapshot` | No | A filename as returned by `backup_database` (default: the most recent snapshot) |

Example response:

```json
{
  "restored_from": "manual_1731082013456789012.db"
}
```

**Error cases:**
- `snapshot` does not match any snapshot file: raises an error
- The snapshot copies in but the database fails to reopen (e.g. a corrupt or incompatible file): raises an error and reloads every entry anyway

### `simple_inventory.export`

Export one inventory's data as JSON or CSV — a service-call equivalent of the WebSocket `simple_inventory/export` command, for automation-triggered exports (e.g. writing the result to a file on a schedule). Supports `response_variable` for use in automations and scripts.

```yaml
service: simple_inventory.export
data:
  inventory_id: "01JYFPCDMBRBRK4MB3C26S2FKH"
  format: "csv"
response_variable: result
```

| Field | Required | Description |
|---|---|---|
| `inventory_id` | Yes | The inventory to export |
| `format` | No | `"json"` or `"csv"` (default: `"json"`) |

The response shape matches the WebSocket `simple_inventory/export` command: `{"data": ..., "format": ...}`.

## WebSocket API

The integration provides WebSocket commands for real-time communication. These are used by the companion card and can also be used by custom panels or scripts.

### `simple_inventory/get_info`

Version handshake. No arguments, available to every authenticated user.

```json
{
  "type": "simple_inventory/get_info"
}
```

Returns: `{ "version": "0.11.0", "api_version": 3, "features": ["batches", "transfers", "item_icons", "item_images", "panel", "tile_images", "search", "overview"] }`

- `version` — the installed integration version (from `manifest.json`).
- `api_version` — the frontend contract version. It is bumped **only** for breaking changes (0.7.0 introduced `2`; 0.8.0 introduced `3` with batches). Clients should compare against the minimum they support; additive changes never bump it.
- `features` — optional capability strings. Gate optional UI on these rather than on `version` string comparisons. `"batches"` (0.8.0+): items carry `batches`/`stocked_locations`, and the batch services and fields described above are available. `"transfers"` (0.9.0+): the [`transfer_item`](#simple_inventorytransfer_item) service is available. `"item_icons"` (0.10.0+): items carry `icon`, and `add_item`/`update_item` accept it. `"item_images"` (0.11.0+): items carry `image`, the [image endpoints](#item-images) exist, and `set_item_image_from_barcode`, `set_item_image_from_media` and `clear_item_image` are available. `"panel"`: the [`list_inventories`](#simple_inventorylist_inventories) command exists and the integration can register the [sidebar panel](#sidebar-panel). `"tile_images"`: the [image endpoint](#item-images) accepts `?tile=1` (at most 384 px). `"search"`: the [`search`](#simple_inventorysearch) command exists. `"overview"`: the [`overview`](#simple_inventoryoverview) command exists.

A backend older than 0.7.0 answers `get_info` with an `unknown_command` error.

### `simple_inventory/list_inventories`

Every inventory (the global entry excluded), sorted by name (case-insensitive). No arguments. Used by the [sidebar panel](#sidebar-panel) to build its tabs.

```json
{
  "type": "simple_inventory/list_inventories"
}
```

Returns:

```json
{
  "inventories": [
    {
      "id": "01JYFPCDMBRBRK4MB3C26S2FKH",
      "name": "Kitchen",
      "icon": "mdi:fridge",
      "description": "",
      "entity_id": "sensor.kitchen_inventory"
    }
  ]
}
```

`id` is the config entry id (the `inventory_id` of the other commands). `entity_id` is the inventory's sensor, resolved through the entity registry (so a renamed entity id is reported correctly), or `null` when the sensor does not exist.

### Error codes

User-facing errors raised by services (and forwarded by `simple_inventory/scan_barcode`) carry a stable `translation_key` alongside the human-readable `message`. Match on `translation_key`, never on message text — the message is localized and may change.

```json
{
  "id": 7,
  "type": "result",
  "success": false,
  "error": {
    "code": "service_validation_error",
    "message": "Validation error: No item found for barcode \"012345678901\"",
    "translation_domain": "simple_inventory",
    "translation_key": "barcode_not_found",
    "translation_placeholders": { "barcode": "012345678901" }
  }
}
```

Service calls report `code: "service_validation_error"`; the `scan_barcode` WebSocket command reports `code: "scan_failed"` with the same translation fields.

| `translation_key` | Placeholders | Raised when |
|---|---|---|
| `alias_conflict` | `aliases` | An alias already belongs to another item in the inventory (case-insensitive) |
| `alias_is_item_name` | `aliases`, `inventory` | An alias is already another item's name in the inventory (case-insensitive) |
| `ambiguous_barcode` | `barcode`, `inventories` | A barcode matches items in several inventories and no `inventory_id` was given |
| `ambiguous_inventory` | `name`, `matches` | An `inventory_name` matches several inventories |
| `ambiguous_item` | `name`, `inventory`, `matches` | An item name/alias matches several items |
| `barcode_conflict` | `barcodes` | A barcode already belongs to another item in the inventory |
| `barcode_not_found` | `barcode` | No item has the barcode (in the given inventory, or in any inventory) |
| `barcode_not_on_item` | `barcode`, `name` | `set_item_image_from_barcode`'s `lookup_barcode` is not one of the item's barcodes |
| `batch_not_found` | `batch_id` | `batch_id` does not name a batch of the item / inventory (`decrement_item`, `scan_barcode`, `update_batch`, `remove_batch`, `transfer_item`) |
| `batch_required` | `name`, `count`, `field` | `update_item` (or an `overwrite` import) changes `expiry_date` or `price` on an item with more than one batch, so the target batch is ambiguous; edit the batch instead |
| `category_assignment_failed` | `categories` | Categories could not be linked to the item |
| `duplicate_item_name` | `name`, `inventory` | Adding, or renaming onto, a name already used in the inventory (case-insensitive) |
| `empty_item_name` | `inventory` | The item name is empty or whitespace |
| `image_download_failed` | `name` | The product photo could not be downloaded (HTTP error, timeout, or not an `http`/`https` URL) |
| `image_invalid` | — | The file is not a supported image (JPEG, PNG, WebP, GIF; HEIC/AVIF when Pillow supports them) |
| `image_not_found` | `name` | `set_item_image_from_barcode` found no product photo (or the item has no barcode) |
| `image_too_large` | — | The image is over 10 MB (or over 64 megapixels) |
| `insufficient_stock` | `name`, `location`, `available` | `transfer_item` asks for more than the source holds (`location` lists the source locations, or the inventory name when none); nothing is moved |
| `inventory_identifier_required` | — | Neither `inventory_id` nor `inventory_name` was given |
| `inventory_not_found` | `name` | No inventory matches `inventory_name` |
| `inventory_not_loaded` | `inventory` | The inventory exists but is not currently loaded (or the id is unknown) |
| `invalid_amount` | `amount` | `transfer_item`'s `amount` rounds to zero or less; nothing is moved |
| `invalid_auto_add_config` | `name`, `inventory` | `add_item` with auto-add enabled but no todo list (or an invalid auto-add quantity) |
| `invalid_scan_action` | `action` | `scan_barcode` action is not `increment`, `decrement` or `lookup` |
| `item_identifier_required` | `inventory` | Neither `name` nor `barcode` identifies the item |
| `item_not_found` | `name`, `inventory` | No item with that name or alias exists in the inventory |
| `location_assignment_failed` | `locations`, `inventory` | Locations could not be linked to the item |
| `location_required` | — | A transfer's destination is blank; nothing is moved |
| `name_is_alias` | `name`, `item`, `inventory` | Adding, renaming or importing an item with a name that is already an alias of `item` (case-insensitive) |
| `no_inventories_configured` | — | No inventory is set up |
| `no_stock_at_location` | `name`, `location` | A decrement's `location` (or a transfer's `from_location`) holds no batch of the item; nothing is changed |
| `no_stock_for_expiry` | `name` | `update_item` changes `expiry_date` on an item with no stock (no batches); restock it with an expiry date instead |
| `restore_reopen_failed` | `error` | `restore_database` copied in the snapshot, but reopening the database failed; every entry reloads anyway |
| `same_location` | `location` | `transfer_item`'s source is already the destination (same `from_location`, a `batch_id` already there, or all stock already there); nothing is moved |
| `snapshot_not_found` | `snapshot` | `restore_database`'s `snapshot` does not match any snapshot file |
| `unsupported_media_source` | `media_content_id` | `set_item_image_from_media` got an id that is not a file in a local media folder or an uploaded image |
| `update_item_failed` | `name`, `inventory` | `update_item` could not apply the change (e.g. auto-add enabled without a todo list) |

### `simple_inventory/list_items`

Fetch all items for an inventory.

```json
{
  "type": "simple_inventory/list_items",
  "inventory_id": "01JYFPCDMBRBRK4MB3C26S2FKH"
}
```

Returns: `{ "items": [...] }` — each item includes `batches` and `stocked_locations` (see [`get_items`](#simple_inventoryget_items)).

### `simple_inventory/get_item`

Fetch a single item by name.

```json
{
  "type": "simple_inventory/get_item",
  "inventory_id": "01JYFPCDMBRBRK4MB3C26S2FKH",
  "name": "Frozen Pizza"
}
```

Returns: `{ "item": { ... } }` — including `batches` and `stocked_locations`.

### `simple_inventory/search`

Find items across every enabled inventory, best match first.

```json
{
  "type": "simple_inventory/search",
  "query": "butter",
  "limit": 50
}
```

- `query` — required. Leading and trailing whitespace is stripped; at most 100 characters. A blank query returns no items.
- `limit` — optional, 1–200, default 50.

A longer `query` or a `limit` out of range is rejected with `code: "invalid_format"`.

Returns:

```json
{
  "items": [
    {
      "id": "…",
      "name": "Butter",
      "quantity": 2.0,
      "inventory_id": "01JYFPCDMBRBRK4MB3C26S2FKH",
      "inventory_name": "Kitchen",
      "matched": "name"
    }
  ],
  "truncated": false
}
```

Each item is the same dict as in [`list_items`](#simple_inventorylist_items) (with `batches`, `stocked_locations`, `aliases`, `barcodes` and so on), plus `inventory_id`, `inventory_name` (the inventory's display name) and `matched`. `truncated` is `true` when more items matched than `limit`.

An item matches when the query is a substring of one of the fields below. Results are ordered by the best field matched, then by item name, then by inventory name; an item matching several fields appears once.

| Rank (best first) | Field | `matched` |
|---|---|---|
| 0 | Name equals the query | `name` |
| 1 | Name starts with the query | `name` |
| 2 | Name contains the query | `name` |
| 3 | An alias | `alias` |
| 4 | A barcode | `barcode` |
| 5 | A category | `category` |
| 6 | A location of the item, or of one of its batches | `location` |
| 7 | Description | `description` |
| 8 | Unit | `unit` |

Matching is case-insensitive (Unicode case folding, so `STRASSE` finds "Straße") but not accent-insensitive (`creme` does not find "Crème"). `%` and `_` are literal characters. Only enabled inventories are searched; the global entry has no items. To refresh results live, [subscribe](#simple_inventorysubscribe) without `inventory_id`.

### `simple_inventory/overview`

A summary of every enabled inventory and what needs attention across them. No arguments; any authenticated user can call it. Used by the panel's Home tab.

```json
{
  "type": "simple_inventory/overview"
}
```

Returns:

```json
{
  "inventories": [
    {
      "id": "01JYFPCDMBRBRK4MB3C26S2FKH",
      "name": "Kitchen",
      "icon": "mdi:fridge",
      "total_items": 24,
      "total_value": 84.12,
      "attention": { "expired": 1, "expiring_soon": 2, "out_of_stock": 3, "low_stock": 1 }
    }
  ],
  "expired": [ ... ],
  "expiring_soon": [ ... ],
  "out_of_stock": [ ... ],
  "low_stock": [ ... ]
}
```

- `inventories` — one summary per enabled inventory (the global entry excluded), sorted by display name (case-insensitive). `total_items` and `total_value` are the same numbers as [`get_inventory_statistics`](#simple_inventoryget_inventory_statistics) reports. `attention` counts the inventory's items in each section below.
- Each section entry is the item's [`list_items`](#simple_inventorylist_items) dict plus `inventory_id`, `inventory_name` (the inventory's display name) and `reason`.

| Section | `reason` | Sorted by |
|---|---|---|
| `expired` | `days_overdue` (of the oldest expired batch), `batches` and `quantity` (count and total quantity of the expired batches) | most overdue first, then item name, then inventory name |
| `expiring_soon` | `days_until_expiry` (of the soonest batch), `batches` and `quantity` (count and total quantity of the batches expiring within the item's `expiry_alert_days`) | soonest first, then item name, then inventory name |
| `out_of_stock` | `{}` | item name, then inventory name |
| `low_stock` | `threshold` (the item's `auto_add_to_list_quantity`) and `quantity_needed` (see [Auto-Add to Todo List](#auto-add-to-todo-list)) | item name, then inventory name |

Names sort case-insensitively. Each item is listed once, in its most urgent section: expired, then expiring soon, then out of stock (quantity 0 or less), then low stock (in stock, but at or below a positive auto-add threshold). The `attention` counts follow the same rule. Expiry is per batch with each item's own alert window, exactly as the [expiry sensors](#per-inventory-sensors) count it, so a batch expiring today is "expiring soon" and one that expired yesterday is "expired". To refresh live, [subscribe](#simple_inventorysubscribe) without `inventory_id` and fetch the overview again on each event.

### `simple_inventory/subscribe`

Subscribe to real-time inventory updates. When any item changes, you receive the full updated item list.

```json
{
  "type": "simple_inventory/subscribe",
  "inventory_id": "01JYFPCDMBRBRK4MB3C26S2FKH"
}
```

Omit `inventory_id` to subscribe to updates from all inventories:

```json
{
  "type": "simple_inventory/subscribe"
}
```

When subscribed to a specific inventory, each event delivers `{ "items": [...] }` with the full item list. When subscribed globally, events deliver `{ "event": "updated" }`.

### `simple_inventory/get_history`

Query change history for an inventory or a specific item.

```json
{
  "type": "simple_inventory/get_history",
  "inventory_id": "01JYFPCDMBRBRK4MB3C26S2FKH",
  "item_name": "Frozen Pizza",
  "event_type": "decrement",
  "start_date": "2026-01-01",
  "end_date": "2026-02-15",
  "limit": 50,
  "offset": 0
}
```

All fields except `inventory_id` are optional. Supported `event_type` values: `add`, `increment`, `decrement`, `update`, `import`. An `end_date` given as `YYYY-MM-DD` includes that whole day; a full ISO timestamp is an inclusive upper bound. `limit` and `offset` must be ≥ 0.

Returns: `{ "events": [...] }` where each event has:
- `event_type` — What happened
- `amount` — How much changed
- `quantity_before`, `quantity_after` — Item stock levels (one event per touched batch, with running totals)
- `batch_id` — The batch the event touched
- `location_from`, `location_to` — The batch's location for consumption / restock
- `timestamp` — When it happened

### `simple_inventory/get_item_consumption_rates`

Get consumption analytics for a specific item. Requires at least 2 decrement events to produce meaningful data.

```json
{
  "type": "simple_inventory/get_item_consumption_rates",
  "inventory_id": "01JYFPCDMBRBRK4MB3C26S2FKH",
  "item_name": "Frozen Pizza",
  "window_days": 30
}
```

`window_days` is optional — omit it to calculate rates across all history.

Returns:

```json
{
  "item_name": "Frozen Pizza",
  "current_quantity": 3.0,
  "unit": "boxes",
  "decrement_count": 12,
  "total_consumed": 18.0,
  "window_days": 30,
  "daily_rate": 0.6,
  "weekly_rate": 4.2,
  "days_until_depletion": 5,
  "avg_restock_days": 14.0,
  "has_sufficient_data": true,
  "total_spend": 53.94,
  "daily_spend_rate": 1.80,
  "weekly_spend_rate": 12.58
}
```

| Field | Description |
|---|---|
| `daily_rate` | Average units consumed per day (null if insufficient data) |
| `weekly_rate` | Average units consumed per week (null if insufficient data) |
| `days_until_depletion` | Estimated days until quantity reaches 0 (null if rate is 0 or insufficient data) |
| `avg_restock_days` | Average days between increment events (null if fewer than 2 restocks) |
| `has_sufficient_data` | `true` if there are at least 2 decrement events to calculate rates |
| `total_spend` | Total money spent purchasing this item (null if no priced restock events) |
| `daily_spend_rate` | Average daily purchasing cost (null if no priced restock events) |
| `weekly_spend_rate` | Average weekly purchasing cost (null if no priced restock events) |

### `simple_inventory/get_inventory_consumption_rates`

Get consumption analytics for every item in an inventory, plus a summary.

```json
{
  "type": "simple_inventory/get_inventory_consumption_rates",
  "inventory_id": "01JYFPCDMBRBRK4MB3C26S2FKH",
  "window_days": 30
}
```

`window_days` is optional (≥ 1) — omit it to calculate rates across all history.

Returns the same shape as the [`get_inventory_consumption_rates` service](#simple_inventoryget_inventory_consumption_rates): `{ "inventory_id": "...", "window_days": 30, "items": [...], "summary": { ... } }`.

### `simple_inventory/get_inventory_statistics`

Get aggregate statistics for an inventory.

```json
{
  "type": "simple_inventory/get_inventory_statistics",
  "inventory_id": "01JYFPCDMBRBRK4MB3C26S2FKH"
}
```

Returns:

```json
{
  "total_items": 12,
  "total_quantity": 37.5,
  "total_value": 84.12,
  "categories": { "Frozen Foods": 4, "Snacks": 3 },
  "locations": { "Kitchen Freezer": 5, "Pantry": 7 },
  "below_threshold": [ ... ],
  "expiring_items": [ ... ]
}
```

- `total_value` — Sum of quantity × unit price over all batches with a unit price
- `categories`, `locations` — Number of items per category / location (an item with several counts once under each)
- `below_threshold` — Same entries as the inventory sensor's [`below_threshold`](#per-inventory-sensors) attribute
- `expiring_items` — One entry per batch within its item's alert threshold, expired batches included, soonest first (same fields as the [expiry sensors'](#per-inventory-sensors) entries)

### `simple_inventory/lookup_by_barcode`

Search for an item by barcode across all inventories.

```json
{
  "type": "simple_inventory/lookup_by_barcode",
  "barcode": "012345678901"
}
```

Returns: `{ "items": [...] }` — each item includes `inventory_id` and `inventory_name`.

### `simple_inventory/lookup_barcode_product`

Look up product information for a barcode.

```json
{
  "type": "simple_inventory/lookup_barcode_product",
  "barcode": "012345678901"
}
```

Returns `{ "barcode": "...", "results": [...] }`, the same shape and provider rules as the [`lookup_barcode_product` service](#simple_inventorylookup_barcode_product).

### `simple_inventory/scan_barcode`

Scan a barcode and perform an action on the matched item.

```json
{
  "type": "simple_inventory/scan_barcode",
  "barcode": "012345678901",
  "action": "increment",
  "amount": 1.0,
  "inventory_id": "01JYFPCDMBRBRK4MB3C26S2FKH"
}
```

Only `barcode` and `action` are required. `amount` defaults to 1 and must be greater than 0 (whole numbers are accepted); `price` must be ≥ 0. `inventory_id` is optional unless the barcode exists in multiple inventories. The batch fields `expiry_date`, `location`, `purchased_at` (increment) and `location`, `batch_id` (decrement) behave as in the [`scan_barcode` service](#simple_inventoryscan_barcode).

Returns: `{ "action": "increment", "success": true, "item_name": "...", "inventory_id": "...", "amount": 1.0 }`

### `simple_inventory/export`

Export inventory data.

```json
{
  "type": "simple_inventory/export",
  "inventory_id": "01JYFPCDMBRBRK4MB3C26S2FKH",
  "format": "json"
}
```

Supported formats: `json`, `csv`

Each exported item includes its `icon` and its `batches` (`quantity`, `expiry_date`, `location`, `unit_price`, `purchased_at`). In CSV, `batches` is a column holding the list as a JSON string.

### `simple_inventory/import`

Import inventory data with a merge strategy.

```json
{
  "type": "simple_inventory/import",
  "inventory_id": "01JYFPCDMBRBRK4MB3C26S2FKH",
  "data": [{"name": "New Item", "quantity": 3}],
  "format": "json",
  "merge_strategy": "skip"
}
```

`data` is an object or list for `format: "json"` (a JSON string is also accepted), and a CSV string for `format: "csv"`.

A record matches an existing item when their names are equal under Unicode case folding ("čokolada" matches "Čokolada", "STRASSE" matches "Straße"). A record is listed in `errors` and skipped when it would make a name ambiguous: a new item whose name or aliases clash with another item's name or aliases, or an `overwrite` that adds an alias already used as another item's name or alias. Earlier records of the same import count.

Merge strategies:
- `skip` — Skip items that already exist (default)
- `overwrite` — Replace only the fields present in each record — scalar fields and locations/categories/barcodes/aliases. An empty list clears that relation; fields absent from the record are left untouched. When the record has `batches` (or a `quantity`), the item's stock is replaced with them. An `expiry_date`/`price` without stock follows the [`update_item` rules](#simple_inventoryupdate_item).
- `merge_quantities` — Add the record's quantity to the existing stock, merging it into a batch with the same expiry date, location, and unit price, otherwise as a new batch (a record with a price also updates the item's price); records with no or zero quantity count as skipped

Records with a `batches` list (JSON list, or JSON string in CSV) restore those batches; records without one (older exports, hand-written CSVs) import their scalar `quantity` as a single batch. Imported stock is recorded in history as `import` events. Imports fire no item lifecycle events (added, quantity changed, depleted, restocked); only the todo-list events (`simple_inventory_item_added_to_list` / `simple_inventory_item_removed_from_list`) fire, when an imported item's todo entry is added, refreshed or removed.

Each record is validated like `add_item` (non-negative numbers, `YYYY-MM-DD` dates, valid `todo_quantity_placement`, valid auto-add configuration, `icon` empty or `prefix:name`). Invalid records are listed in `errors` (`Item N (...)` for JSON, `Row N (...)` for CSV) and skipped; a record that fails part-way leaves no changes. Files without `icon` (exports from before 0.10.0) import with the default icon, and an `overwrite` import without it keeps the item's icon.

CSV cells beginning with `=`, `+`, `-`, `@`, tab, or carriage return are prefixed with `'` on export so spreadsheets don't evaluate them as formulas; the prefix is removed on import. Exported descriptions omit the `(inventory_id)` tag; it is re-applied for the target inventory on import.

Returns: `{ "added": 1, "updated": 0, "skipped": 0, "errors": [] }`

Pass `"dry_run": true` to run the identical validation and merge-strategy decisions and get the same summary shape back, without writing anything or syncing the todo list — use it to preview a file's effect first.

### `simple_inventory/get_barcode_provider_config`

Read the barcode provider selection.

```json
{
  "type": "simple_inventory/get_barcode_provider_config"
}
```

Returns `{ "provider": "openfoodfacts" }` once a provider has been selected, or `{}` when none is (all providers are queried).

### `simple_inventory/set_barcode_provider_config`

Admin only. Select which product-lookup provider barcode lookups query.

```json
{
  "type": "simple_inventory/set_barcode_provider_config",
  "provider": "openfoodfacts"
}
```

`provider` must be one of `openfoodfacts`, `openbeautyfacts`, `openpetfoodfacts`, `upcitemdb`. Once set, product lookups query only that provider; with nothing set, all four are queried. Read the current value with `simple_inventory/get_barcode_provider_config`.

## Diagnostics & Repairs

### Diagnostics

Download diagnostics from **Settings -> Devices & Services -> Simple Inventory -> (entry menu) -> Download diagnostics** and attach the file to bug reports. It contains:

- integration version, `api_version`, database schema version, and whether the legacy JSON store was migrated
- the entry's type, name, icon, whether it has a description, options, and load state
- counts: items, items out of stock, locations, categories, barcodes, aliases, history events
- auto-add: number of items with auto-add enabled, and each referenced todo list with its item count, whether it currently exists, and whether it supports item descriptions
- the selected barcode lookup provider (or `null`)
- on the global entry: every inventory entry and its load state

Item names, descriptions, barcodes, aliases, and prices are **never** included.

### Repairs

Problems the integration detects show up under **Settings -> System -> Repairs**:

| Issue | When | Fix |
|---|---|---|
| **To-do list no longer exists** (warning) | Items point at a `todo.*` entity that is gone — checked at startup/entry setup and whenever a todo entity is removed or renamed in the entity registry. | Pick a replacement to-do list for the affected items, or clear their list (this also turns auto-add off). Changes go through `update_item`, so the new list is synced right away. |
| **Database is from a newer version** (error) | The database was written by a newer Simple Inventory release (you downgraded). Setup fails instead of retrying; your data is not touched. | Install the release that created the database (or newer) and restart. |
| **Database upgrade failed** (error) | A schema migration to the current release failed partway through. Setup fails instead of retrying; a snapshot of the database was taken automatically right before the upgrade started. | Confirm to restore that snapshot (your data returns to its state just before the upgrade attempt) and reload every entry. |
| **Data for removed inventories** (warning) | The database still holds inventories whose config entry no longer exists. Lists each one with its item count. | Confirm to permanently delete that data. |
| **Inventory panel needs the Simple Inventory card** (warning) | The [sidebar panel](#sidebar-panel) is enabled but `<config>/www/community/simple-inventory-card/simple-inventory-panel.js` is missing. The panel is still registered, but cannot load. | Install or update the Simple Inventory card through HACS (or copy its files into that folder), then restart or save the global entry's options again. |

Issues are re-checked every time an inventory is set up; an issue whose condition no longer applies is removed automatically.

## Backups & Restore

The database (`<config>/simple_inventory.db`) and item photos (`<config>/simple_inventory/images/`) already live under Home Assistant's config directory, so a full HA backup (Settings -> System -> Backups) captures and restores them automatically. Simple Inventory checkpoints its write-ahead log before every HA backup runs, so that capture is always consistent.

On top of that, Simple Inventory keeps its own lightweight snapshots in `<config>/simple_inventory/backups/` (the 3 most recent are kept):

- **Automatic**: right before a database schema upgrade runs (on update to a release with a newer schema), a snapshot of the pre-upgrade database is taken. If the upgrade fails partway through, a **Database upgrade failed** repair issue appears in Settings -> Repairs (see [Repairs](#repairs) above); confirming it restores that snapshot and reloads every Simple Inventory entry.
- **On demand**: call [`backup_database`](#simple_inventorybackup_database) before a risky change (e.g. a large import), and [`restore_database`](#simple_inventoryrestore_database) to roll back to it or any other recent snapshot.

Restoring, automatic or manual, replaces the live database with the snapshot's contents and reloads every Simple Inventory config entry, since they all share one database.

## Voice & AI Assistants

Simple Inventory registers ten native Home Assistant intents so you can
control your inventories by voice or through an LLM-backed conversation
agent, without writing any automations:

- **Remove/consume an item** — "remove one aluminum foil from the
  disposable goods inventory"
- **Add/restock an item** — "add two cans of soup to the pantry"
- **Set an exact quantity** — "set the milk in the fridge to three"
- **Move stock** — "move two milk from the fridge to the garage fridge in the
  kitchen" (without a quantity, everything at the source moves)
- **Query a quantity** — "how many aluminum foil do we have in disposable
  goods" or "how many apples are in dry goods" (the answer uses the stored
  item and inventory names; when stock is in several places it adds a
  breakdown: "…: 2 in Fridge, 1 in Garage.")
- **Find an item in every inventory** — "how many batteries do we have",
  "do we have any butter", "where are the batteries", or in one inventory
  "do we have any milk in the kitchen" (searches item names and aliases in
  all enabled inventories, or the named one; an exact name or alias wins over
  partial matches: "I found 2 matches for batteries: 4 AA batteries in
  Garage (Shelf B) and 8 AA batteries in Kitchen (Drawer).")
- **Count low-stock items** — items at or below their restock threshold,
  and how many of them are out of stock ("2 items are low on stock, 1 of
  them out of stock.")
- **List low-stock items** — "what's running low", "what are we low on in
  the pantry" ("2 items are low on stock: Butter and Oil (out of stock).")
- **Count expired / expiring items** (counts distinct items, even if an
  item has several expiring batches)
- **List expired / expiring items**

Counts and lists scoped to one inventory name it as stored ("… in Kitchen"),
not as heard.

The add and remove intents take an optional **location** (the storage spot
inside the inventory, e.g. "Fridge"): adding stores the new stock there,
removing only takes stock that is there. The location must already exist in
the inventory (matched with the same typo tolerance as items); an unknown
location is refused with "I don't know a location called … in …" and
nothing changes, so a misheard name never creates a new location. When the
spoken location matches several locations (e.g. "fridge" for "Fridge Door"
and "Fridge Drawer", with no location named exactly "Fridge"), removing
narrows them to the ones where the item has stock: one left is used, several
are asked about ("Which location in … did you mean: …?"), and none is refused
with "There is no … at … in …"; adding always asks. Nothing changes until
the location is clear. LLM-backed agents fill this slot directly. With the
bundled example sentences, name the
location before the inventory: "remove 2 milk from the fridge in the
kitchen", "add milk to the garage fridge in the kitchen". The add/remove
intents split "<location> in [the] <inventory>" only when the words after
"in" are exactly an inventory's name and the words before it match at least
one of that inventory's locations (the last "in" is tried first, so inventory
names containing "in" still work); anything else is treated as the inventory
name as before.

The move intent needs the destination and, optionally, the source location;
both must already exist in the inventory (same matching and refusal as
above). LLM-backed agents may leave out the source, which moves the
soonest-expiring stock that isn't already at the destination.

Items and inventories are matched by name with typo tolerance (exact match,
then substring, then closest-match), so you don't need to remember exact
casing or the internal inventory ID. Items also match by any alias you've
set on them (see [Item Aliases](#item-aliases)), which is handy for
giving voice commands a shorter or more natural name than what's stored.

### LLM-backed Assist (OpenAI, Google Generative AI, a local model via Ollama, etc.)

No setup needed beyond configuring the LLM conversation agent itself in
"Assist" control mode. Simple Inventory ships an `llm.py` platform module
that contributes these intents as callable tools to Home
Assistant's Assist API, so any LLM conversation agent using it gets them
automatically -- no entity exposure required, since these tools resolve
inventories and items by name rather than acting on Home Assistant
entities. Each tool's description ends with your current inventory names, so
the agent fills the inventory parameter with a real name.

### Local/offline Assist (Home Assistant Voice's default pipeline)

If your Home Assistant language is English, Spanish, French or Slovenian, check
**"Install example voice commands"** when adding your first inventory
(Settings → Devices & Services → Add Integration → Simple Inventory), or
later via the global Simple Inventory entry's **Configure** button (the same dialog
holds the [sidebar panel](#sidebar-panel) settings). This
copies the bundled example sentence file for that language into your config
directory, writes the inventory names file next to it (below) and reloads custom
sentences automatically — no restart needed. It never overwrites a file that's
already there, so it's safe to check even if you've already installed it or
created your own.

If you'd rather do it by hand — to review the content first, or because you
skipped the checkbox — copy the file for your language (`en`, `es`, `fr` or
`sl`) manually:

```bash
cp custom_components/simple_inventory/data/custom_sentences/en/simple_inventory.yaml \
   <config>/custom_sentences/en/simple_inventory.yaml
```

Then reload any Simple Inventory entry (or restart Home Assistant) so it writes the
names file and reloads custom sentences. Edit the sentence templates in that file to
add your own phrasing.

The sentences only accept the names of your inventories
(`{simple_inventory_name:inventory}`). Simple Inventory keeps them in
`<config>/custom_sentences/<language>/simple_inventory_names.yaml` and rewrites that
file whenever an inventory is added, renamed, enabled, disabled or removed; don't edit
it. Home Assistant prefers custom sentences over its own, so a slot that matched any
words would take over commands such as "add milk to my shopping list" or "add 5
minutes to my timer". For Slovenian the file also lists common case forms of each
name's last word ("v kuhinji", "v shrambo"); a name whose forms don't follow those
endings works in the form it is stored in.

Answers are spoken in the conversation's language (the Assist pipeline's
language) when it is English, Spanish, French or Slovenian, regional variants
included ("fr-CA" answers in French); any other language gets English answers.
Item, inventory and location names are spoken as stored. The Spanish, French
and Slovenian sentence files cover the same commands as the English one, except
naming a location inside an add/remove command (LLM-backed agents can still
fill it).

**Upgrading an installed sentence file.** An installed English file that is still the
unedited copy of an earlier release is replaced with the current one automatically.
An edited one is left alone and a repair (Settings → Repairs) lists it: in that
format any words can name an inventory, so delete it and install the example
sentences again, or bring your edits over to the current file. The "move" sentences
can mis-parse location names that contain the words "from", "to" or "in";
LLM-backed assistants are unaffected.

## Automation Examples

### Notify when an item is added to your shopping list

```yaml
automation:
  - alias: "Shopping list notification"
    trigger:
      - platform: event
        event_type: simple_inventory_item_added_to_list
    action:
      - service: notify.mobile_app
        data:
          title: "Added to shopping list"
          message: "{{ trigger.event.data.item_name }} (need {{ trigger.event.data.quantity_needed }})"
```

### Alert when something runs out

```yaml
automation:
  - alias: "Out of stock alert"
    trigger:
      - platform: event
        event_type: simple_inventory_item_depleted
    action:
      - service: notify.mobile_app
        data:
          title: "Out of stock"
          message: "{{ trigger.event.data.item_name }} is depleted!"
```

### Barcode scanner: increment on scan

Use `scan_barcode` for automatic cross-inventory resolution — no need to know which inventory the item belongs to:

```yaml
automation:
  - alias: "Barcode scan - add to inventory"
    trigger:
      - platform: event
        event_type: tag_scanned
    action:
      - service: simple_inventory.scan_barcode
        data:
          barcode: "{{ trigger.event.data.tag_id }}"
          action: "increment"
          amount: 1
```

### Barcode scanner: decrement on scan (checking out items)

```yaml
automation:
  - alias: "Barcode scan - use item"
    trigger:
      - platform: event
        event_type: tag_scanned
    condition:
      - condition: state
        entity_id: input_select.scan_mode
        state: "checkout"
    action:
      - service: simple_inventory.scan_barcode
        data:
          barcode: "{{ trigger.event.data.tag_id }}"
          action: "decrement"
          amount: 1
        response_variable: result
      - service: notify.mobile_app
        data:
          title: "Checked out"
          message: "{{ result.item_name }} (-{{ result.amount }})"
```

### Barcode lookup: find which inventory has an item

```yaml
script:
  find_item_by_barcode:
    sequence:
      - service: simple_inventory.lookup_by_barcode
        data:
          barcode: "012345678901"
        response_variable: result
      - service: notify.mobile_app
        data:
          title: "Barcode lookup"
          message: >
            {% if result.items | length == 0 %}
              Barcode not found in any inventory.
            {% else %}
              {% for item in result.items %}
              - {{ item.name }} in {{ item.inventory_name }} (qty: {{ item.quantity }})
              {% endfor %}
            {% endif %}
```

### Barcode scanner with mode toggle

Use an `input_select` helper to switch between scan modes (increment, decrement, lookup):

```yaml
automation:
  - alias: "Smart barcode scanner"
    trigger:
      - platform: event
        event_type: tag_scanned
    action:
      - service: simple_inventory.scan_barcode
        data:
          barcode: "{{ trigger.event.data.tag_id }}"
          action: "{{ states('input_select.scan_mode') }}"
          amount: "{{ states('input_number.scan_amount') | float(1) }}"
        response_variable: result
      - service: notify.mobile_app
        data:
          title: "Scanned: {{ result.item_name }}"
          message: >
            {% if result.action == 'lookup' %}
              Found in inventory {{ result.inventory_id }}
            {% else %}
              {{ result.action | title }}: {{ result.amount }}
            {% endif %}
```

### Notify when items expire

```yaml
automation:
  - alias: "Expiry notification"
    trigger:
      - platform: state
        entity_id: sensor.all_items_expiring_soon
    condition:
      - condition: numeric_state
        entity_id: sensor.all_items_expiring_soon
        above: 0
    action:
      - service: notify.mobile_app
        data:
          title: "Expiring soon"
          message: >
            {{ state_attr('sensor.all_items_expiring_soon', 'total_expiring') }} batches expiring soon,
            {{ state_attr('sensor.all_items_expiring_soon', 'total_expired') }} already expired.
```

### Low stock alert

```yaml
automation:
  - alias: "Low stock alert"
    trigger:
      - platform: state
        entity_id: sensor.kitchen_inventory
    condition:
      - condition: template
        value_template: >
          {{ state_attr('sensor.kitchen_inventory', 'below_threshold') | length > 0 }}
    action:
      - service: notify.mobile_app
        data:
          title: "Low stock items"
          message: >
            {% for item in state_attr('sensor.kitchen_inventory', 'below_threshold') %}
            - {{ item.name }}: {{ item.quantity }} remaining (need {{ item.quantity_needed }})
            {% endfor %}
```

### Alert when consumption rate spikes

Compare recent consumption against the long-term baseline and notify when an item is being used faster than normal:

```yaml
script:
  check_consumption_spike:
    sequence:
      - service: simple_inventory.get_item_consumption_rates
        data:
          inventory_id: "01JYFPCDMBRBRK4MB3C26S2FKH"
          name: "Milk"
          window_days: 30
        response_variable: recent
      - service: simple_inventory.get_item_consumption_rates
        data:
          inventory_id: "01JYFPCDMBRBRK4MB3C26S2FKH"
          name: "Milk"
        response_variable: baseline
      - condition: template
        value_template: >
          {{ recent.daily_rate and baseline.daily_rate and
             recent.daily_rate > (baseline.daily_rate * 1.5) }}
      - service: notify.mobile_app
        data:
          title: "Milk consumption spike"
          message: >
            Recent: {{ recent.daily_rate | round(1) }}/day
            vs baseline: {{ baseline.daily_rate | round(1) }}/day
```

### Alert when an item is running low

```yaml
automation:
  - alias: "Depletion warning"
    trigger:
      - platform: time_pattern
        hours: "/6"
    action:
      - service: simple_inventory.get_item_consumption_rates
        data:
          inventory_id: "01JYFPCDMBRBRK4MB3C26S2FKH"
          name: "Coffee"
        response_variable: rates
      - condition: template
        value_template: >
          {{ rates.days_until_depletion is not none and
             rates.days_until_depletion <= 7 }}
      - service: notify.mobile_app
        data:
          title: "Coffee running low"
          message: >
            ~{{ rates.days_until_depletion }} days left at current rate
            ({{ rates.daily_rate | round(1) }} {{ rates.unit }}/day)
```

### Get inventory data in a script

```yaml
script:
  get_inventory_report:
    sequence:
      - service: simple_inventory.get_items
        data:
          inventory_name: "Kitchen Fridge"
        response_variable: result
      - service: notify.mobile_app
        data:
          title: "Inventory Report"
          message: "You have {{ result.items | length }} items in the fridge."
```

### Cross-inventory low stock summary

```yaml
script:
  low_stock_summary:
    sequence:
      - service: simple_inventory.get_items_from_all_inventories
        response_variable: all_data
      - service: notify.mobile_app
        data:
          title: "Inventory Summary"
          message: >
            {% set ns = namespace(low=[]) %}
            {% for inv in all_data.inventories %}
              {% for item in inv.items if item.auto_add_enabled and item.quantity <= item.auto_add_to_list_quantity %}
                {% set ns.low = ns.low + [item.name ~ ' (' ~ inv.inventory_name ~ ')'] %}
              {% endfor %}
            {% endfor %}
            {% if ns.low %}Low stock: {{ ns.low | join(', ') }}{% else %}All stocked up!{% endif %}
```
