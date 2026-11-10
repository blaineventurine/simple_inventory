[← Back to README](../README.md)

# WebSocket API

The integration provides WebSocket commands for real-time communication. These are used by the companion card and can also be used by custom panels or scripts.

**Conventions:** most errors carry a stable `translation_key` (see [Error codes](#error-codes)), same as service errors. A command scoped to one `inventory_id` rejects an unknown one with `inventory_not_found` first. Schema validation failures report `code: "invalid_format"`. A few setup-level failures (`no_inventories`, `no_repository`) are plain WS-only codes with a message but no `translation_key`, since there's nothing to localize. Date fields accept `YYYY-MM-DD` or a full ISO 8601 timestamp.

**Handshake & Listing**
| Command | Purpose |
|---|---|
| [`get_info`](#simple_inventoryget_info) | Version handshake |
| [`list_inventories`](#simple_inventorylist_inventories) | Every inventory, sorted by name |
| [`list_items`](#simple_inventorylist_items) | Every item in one inventory |
| [`get_item`](#simple_inventoryget_item) | One item by name |
| [`search`](#simple_inventorysearch) | Full-text search across one or more inventories |
| [`overview`](#simple_inventoryoverview) | Per-inventory summary counts |
| [`subscribe`](#simple_inventorysubscribe) | Live updates for one or every inventory |

**History & Analytics**
| Command | Purpose |
|---|---|
| [`get_history`](#simple_inventoryget_history) | Change history for one item or inventory |
| [`get_item_consumption_rates`](#simple_inventoryget_item_consumption_rates) | Consumption rates for one item |
| [`get_inventory_consumption_rates`](#simple_inventoryget_inventory_consumption_rates) | Consumption rates for every item in an inventory |
| [`get_inventory_statistics`](#simple_inventoryget_inventory_statistics) | The stats the inventory sensor reads |

**Barcode**
| Command | Purpose |
|---|---|
| [`lookup_by_barcode`](#simple_inventorylookup_by_barcode) | Find which inventory/inventories have an item with this barcode |
| [`lookup_barcode_product`](#simple_inventorylookup_barcode_product) | Look up a barcode in external product databases |
| [`scan_barcode`](#simple_inventoryscan_barcode) | Scan a barcode and increment/decrement/look up the matched item |
| [`get_barcode_provider_config`](#simple_inventoryget_barcode_provider_config) | Read the selected product-lookup provider |
| [`set_barcode_provider_config`](#simple_inventoryset_barcode_provider_config) | Select a product-lookup provider (admin only) |

**Import & Export**
| Command | Purpose |
|---|---|
| [`export`](#simple_inventoryexport) | Export one inventory as JSON or CSV |
| [`import`](#simple_inventoryimport) | Import items, with a merge strategy and optional `dry_run` preview |

## `simple_inventory/get_info`

Version handshake. No arguments, available to every authenticated user.

```json
{
  "type": "simple_inventory/get_info"
}
```

Returns: `{ "version": "0.11.0", "api_version": 4, "features": ["batches", "transfers", "item_icons", "item_images", "panel", "tile_images", "search", "overview"] }`

- `version` — the installed integration version (from `manifest.json`).
- `api_version` — the frontend contract version, bumped **only** for breaking changes (`3`: batches; `4`: inventory sensor state changed from a quantity sum to an item count). Compare against the minimum version you support; additive changes never bump it.
- `features` — optional capability strings; gate UI on these, not on `version`. `batches`: batch fields/services. `transfers`: [`transfer_item`](services.md#simple_inventorytransfer_item). `item_icons`: items carry `icon`. `item_images`: items carry `image`; [image endpoints](features.md#item-images) and the image services exist. `panel`: [`list_inventories`](#simple_inventorylist_inventories) and the [sidebar panel](../README.md#sidebar-panel). `tile_images`: the image endpoint accepts `?tile=1`. `search`/`overview`: those commands exist.

A backend without this command answers `get_info` with an `unknown_command` error.

## `simple_inventory/list_inventories`

Every inventory (the global entry excluded), sorted by name (case-insensitive). No arguments. Used by the [sidebar panel](../README.md#sidebar-panel) to build its tabs.

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

## Error codes

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

<details>
<summary><strong>Full error code reference</strong> (37 keys)</summary>

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

</details>

## `simple_inventory/list_items`

Fetch all items for an inventory.

```json
{
  "type": "simple_inventory/list_items",
  "inventory_id": "01JYFPCDMBRBRK4MB3C26S2FKH"
}
```

Returns: `{ "items": [...] }` — each item includes `batches` and `stocked_locations` (see [`get_items`](services.md#simple_inventoryget_items)).

## `simple_inventory/get_item`

Fetch a single item by name.

```json
{
  "type": "simple_inventory/get_item",
  "inventory_id": "01JYFPCDMBRBRK4MB3C26S2FKH",
  "name": "Frozen Pizza"
}
```

Returns: `{ "item": { ... } }` — including `batches` and `stocked_locations`.

## `simple_inventory/search`

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

## `simple_inventory/overview`

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

- `inventories` — one summary per enabled inventory (global entry excluded), sorted by display name. `total_items`/`total_value` match [`get_inventory_statistics`](#simple_inventoryget_inventory_statistics). `attention` counts items in each section below.
- Each section entry is the item's [`list_items`](#simple_inventorylist_items) dict plus `inventory_id`, `inventory_name` (the inventory's display name) and `reason`.

| Section | `reason` | Sorted by |
|---|---|---|
| `expired` | `days_overdue` (of the oldest expired batch), `batches` and `quantity` (count and total quantity of the expired batches) | most overdue first, then item name, then inventory name |
| `expiring_soon` | `days_until_expiry` (of the soonest batch), `batches` and `quantity` (count and total quantity of the batches expiring within the item's `expiry_alert_days`) | soonest first, then item name, then inventory name |
| `out_of_stock` | `{}` | item name, then inventory name |
| `low_stock` | `threshold` (the item's `auto_add_to_list_quantity`) and `quantity_needed` (see [Auto-Add to Todo List](features.md#auto-add-to-todo-list)) | item name, then inventory name |

Each item is listed once, in its most urgent section: expired, then expiring soon, then out of stock (quantity ≤ 0), then low stock. The `attention` counts follow the same rule. Expiry is per batch with each item's own alert window, matching the [expiry sensors](sensors.md#per-inventory-sensors). To refresh live, [subscribe](#simple_inventorysubscribe) without `inventory_id` and fetch the overview again on each event.

## `simple_inventory/subscribe`

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

**History & Analytics**

## `simple_inventory/get_history`

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

All fields except `inventory_id` are optional. `event_type` values: `add`, `increment`, `decrement`, `update`, `transfer`, `import`. An `end_date` as `YYYY-MM-DD` includes that whole day; a full ISO timestamp is an inclusive upper bound. `limit` (default `100`) and `offset` (default `0`) must be ≥ 0.

Returns: `{ "events": [...] }` where each event has:
- `event_type` — What happened
- `amount` — How much changed
- `quantity_before`, `quantity_after` — Item stock levels (one event per touched batch, with running totals)
- `batch_id` — The batch the event touched
- `location_from`, `location_to` — The batch's location for consumption / restock
- `timestamp` — When it happened

## `simple_inventory/get_item_consumption_rates`

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

## `simple_inventory/get_inventory_consumption_rates`

Get consumption analytics for every item in an inventory, plus a summary.

```json
{
  "type": "simple_inventory/get_inventory_consumption_rates",
  "inventory_id": "01JYFPCDMBRBRK4MB3C26S2FKH",
  "window_days": 30
}
```

`window_days` is optional (≥ 1) — omit it to calculate rates across all history.

Returns the same shape as the [`get_inventory_consumption_rates` service](services.md#simple_inventoryget_inventory_consumption_rates): `{ "inventory_id": "...", "window_days": 30, "items": [...], "summary": { ... } }`.

## `simple_inventory/get_inventory_statistics`

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
- `below_threshold` — Same entries as the inventory sensor's [`below_threshold`](sensors.md#per-inventory-sensors) attribute
- `expiring_items` — One entry per batch within its item's alert threshold, expired batches included, soonest first (same fields as the [expiry sensors'](sensors.md#per-inventory-sensors) entries)

**Barcode**

## `simple_inventory/lookup_by_barcode`

Search for an item by barcode across all inventories.

```json
{
  "type": "simple_inventory/lookup_by_barcode",
  "barcode": "012345678901"
}
```

Returns: `{ "items": [...] }` — each item includes `inventory_id` and `inventory_name`.

## `simple_inventory/lookup_barcode_product`

Look up product information for a barcode.

```json
{
  "type": "simple_inventory/lookup_barcode_product",
  "barcode": "012345678901"
}
```

Returns `{ "barcode": "...", "results": [...] }`, the same shape and provider rules as the [`lookup_barcode_product` service](services.md#simple_inventorylookup_barcode_product).

## `simple_inventory/scan_barcode`

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

Only `barcode` and `action` are required. `amount` defaults to 1 and must be greater than 0; `price` must be ≥ 0. `inventory_id` is optional unless the barcode exists in multiple inventories. The batch fields `expiry_date`, `location`, `purchased_at` (increment) and `location`, `batch_id` (decrement) behave as in the [`scan_barcode` service](services.md#simple_inventoryscan_barcode).

Returns: `{ "action": "increment", "success": true, "item_name": "...", "inventory_id": "...", "amount": 1.0 }`

**Import & Export**

## `simple_inventory/export`

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

## `simple_inventory/import`

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

A record matches an existing item when their names are equal under Unicode case folding (e.g. "STRASSE" matches "Straße"). A record is listed in `errors` and skipped when it would make a name ambiguous: a new item whose name or aliases clash with another item's, or an `overwrite` that adds an alias already used as another item's name or alias. Earlier records in the same import count too.

Merge strategies:
- `skip` — Skip items that already exist (default)
- `overwrite` — Replace only fields present in each record (scalars and locations/categories/barcodes/aliases). An empty list clears that relation; absent fields are untouched. A record with `batches` (or `quantity`) replaces the item's stock. An `expiry_date`/`price` without stock follows the [`update_item` rules](services.md#simple_inventoryupdate_item).
- `merge_quantities` — Add the record's quantity to existing stock, merging into a batch with the same expiry date, location and unit price, else a new batch (a price also updates the item's price). Records with no or zero quantity count as skipped.

Records with a `batches` list restore those batches; records without one import their scalar `quantity` as a single batch. Imported stock is recorded in history as `import` events. Imports fire no item lifecycle events (added, quantity changed, depleted, restocked) — only todo-list events (`simple_inventory_item_added_to_list` / `simple_inventory_item_removed_from_list`) fire, when an imported item's todo entry changes.

Each record is validated like `add_item` (non-negative numbers, `YYYY-MM-DD` dates, valid `todo_quantity_placement`/auto-add config, `icon` empty or `prefix:name`). Invalid records are listed in `errors` (`Item N (...)` / `Row N (...)`) and skipped; a record that fails part-way leaves no changes. Files without `icon` import with the default icon; an `overwrite` import without it keeps the item's icon.

CSV cells beginning with `=`, `+`, `-`, `@`, tab, or carriage return are prefixed with `'` on export so spreadsheets don't evaluate them as formulas; the prefix is removed on import. Exported descriptions omit the `(inventory_id)` tag; it is re-applied for the target inventory on import.

Returns: `{ "added": 1, "updated": 0, "skipped": 0, "errors": [] }`

Pass `"dry_run": true` to run the same validation and merge-strategy decisions and get the same summary back, without writing anything or syncing the todo list — use it to preview a file's effect first.

**Barcode** (continued — these two live last since they configure the lookup providers used by the commands above, not scanning itself)

## `simple_inventory/get_barcode_provider_config`

Read the barcode provider selection.

```json
{
  "type": "simple_inventory/get_barcode_provider_config"
}
```

Returns `{ "provider": "openfoodfacts" }` once a provider has been selected, or `{}` when none is (all providers are queried).

## `simple_inventory/set_barcode_provider_config`

Admin only. Select which product-lookup provider barcode lookups query.

```json
{
  "type": "simple_inventory/set_barcode_provider_config",
  "provider": "openfoodfacts"
}
```

`provider` must be one of `openfoodfacts`, `openbeautyfacts`, `openpetfoodfacts`, `upcitemdb`. Once set, product lookups query only that provider; with nothing set, all four are queried. Read the current value with `simple_inventory/get_barcode_provider_config`.
