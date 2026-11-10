[← Back to README](../README.md)

# Features

## Items

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

## Item Images

Each item can have one photo. Every source is normalized (EXIF-rotated, stripped of metadata) and stored as WebP at three sizes (full, tile, thumbnail). JPEG, PNG, WebP and GIF up to 10 MB / 64 megapixels are accepted; HEIC/AVIF depend on the server's Pillow build. Ways to set a photo:

> 🖼️ *Screenshot: an item card/row showing a photo thumbnail* — replace with `![Item photo](images/item-photo.png)`.

- **Upload** — `POST /api/simple_inventory/image/<item_id>` (below); the card uses it for "Take or choose photo".
- **Product photo** — [`set_item_image_from_barcode`](services.md#simple_inventoryset_item_image_from_barcode) downloads the photo the barcode lookup returns.
- **Media** — [`set_item_image_from_media`](services.md#simple_inventoryset_item_image_from_media) copies a file from Home Assistant's local media folders or an image uploaded to Home Assistant.

[`clear_item_image`](services.md#simple_inventoryclear_item_image) (or `DELETE`) removes the photo; removing an item or inventory removes its photos too. Exports only record whether an item has a photo (`true`/`false`) — photos themselves are not exported or imported.

The item's `image` field is a version stamp, so clients can cache photos forever and refetch only when the stamp changes. The HTTP endpoints need a Home Assistant access token (`Authorization: Bearer <token>`) but no admin rights:

| Request | Result |
|---|---|
| `GET /api/simple_inventory/image/<item_id>` | The photo (`image/webp`). `?tile=1` returns the tile size (built from the full photo on first request for photos saved before tiles existed). `?thumb=1` returns the thumbnail and wins over `tile`. Any `v` parameter is ignored (use `v=<image stamp>` to bust caches). Sent with `Cache-Control: private, max-age=31536000, immutable`. `404 {"code": "image_not_found"}` when the item has no photo |
| `POST /api/simple_inventory/image/<item_id>` | Multipart form with the file in field `file`. `200 {"image": "<stamp>"}`; `400 {"code": "image_invalid"}` (not a supported image, or no `file` field); `413 {"code": "image_too_large"}` (over 10 MB, or over 64 megapixels); `404 {"code": "item_not_found"}` |
| `DELETE /api/simple_inventory/image/<item_id>` | `200 {"image": ""}`, also when there was no photo; `404 {"code": "item_not_found"}` for an unknown item |

## Batches

An item's stock is held in **batches**. A batch is one lot of the item with its own **quantity**, **expiry date**, **location**, **purchase date** (`purchased_at`), and **unit price** — e.g. two cartons of milk bought last week that expire on the 3rd sitting in the Fridge, and one bought today that expires on the 10th in the Garage fridge. The item's `quantity` is the sum of its batches and its `expiry_date` is the earliest batch expiry; both remain in the API for compatibility.

> 🖼️ *Screenshot: the batch editor, showing an item with two or three batches at different expiry dates/locations* — replace with `![Batch editor](images/batch-editor.png)`.

- **Restocking** (`add_item`, `increment_item`, `scan_barcode` increment, voice "add") adds stock as a batch. It **merges** into an existing batch when the expiry date, location, and unit price all match (the merged batch keeps the earliest purchase date); otherwise a new batch is created. Unspecified values default to: location = the given `location`, else the item's first usual location; expiry = none; unit price = the item's last known price (a positive `price` updates it).
- **Consuming** (`decrement_item`, `scan_barcode` decrement, voice "remove") takes from the batch expiring **soonest first**; ties go to the oldest purchase date, and batches without an expiry date are used last. A larger amount continues into the next batch in the same order.
  - `location` restricts consumption to batches stored there (`no_stock_at_location` error if there are none; nothing is changed).
  - `batch_id` consumes from exactly that batch (`batch_not_found` error if it doesn't exist) and takes precedence over `location`.
- A batch that reaches 0 is **deleted**; the item remains with quantity 0. History keeps the record.
- **Editing** a batch is done with [`update_batch`](services.md#simple_inventoryupdate_batch) (quantity, expiry, location, unit price, purchase date) and [`remove_batch`](services.md#simple_inventoryremove_batch).
- **Moving** stock to another location of the same inventory is done with [`transfer_item`](services.md#simple_inventorytransfer_item): part of a batch, a whole batch, everything at one location, or the soonest-expiring stock wherever it is. Moved stock keeps its expiry date, unit price and purchase date.
- **Expiry** is evaluated per batch: each expiring or expired batch is its own entry on the [expiry sensors](sensors.md#sensors), so an item with one batch expiring tomorrow and one next month is only partly "expiring soon".
- **Value**: `total_value` is the sum of each batch's quantity × its unit price.
- `update_item` still accepts scalar `quantity`, `expiry_date` and `price` — see [`update_item`](services.md#simple_inventoryupdate_item) for how they map onto batches.

Item responses (`get_items`, WebSocket `list_items`/`get_item`/`subscribe`) include a `batches` list (in consumption order) and `stocked_locations` (the distinct locations that currently hold stock, in the same order).

## Multi-Value Locations and Categories

Items can belong to multiple locations and categories. Pass comma-separated values:

```yaml
location: "Pantry, Kitchen"
category: "Snacks, Bulk Items"
```

The API returns both scalar fields (`location`, `category` with the first value) and array fields (`locations`, `categories` with all values) for backward compatibility.

## Expiration Tracking

Set an `expiry_date` and `expiry_alert_days` on any item. Expiry dates belong to [batches](#batches): each batch is checked against the item's `expiry_alert_days`, and when its remaining days are at or below that threshold the batch appears on the expiry sensors (one entry per batch). Empty batches don't exist, so out-of-stock items never alert. Days until expiry are counted from today's date in Home Assistant's configured time zone, and the expiry sensors recompute at local midnight, so batches move to "expiring" or "expired" on date rollover without any other inventory change.

## Auto-Add to Todo List

Automatically add items to a Home Assistant todo list when stock drops below a threshold. Configure these fields:

| Field | Description |
|---|---|
| `auto_add_enabled` | Enable/disable auto-add for this item |
| `auto_add_to_list_quantity` | Quantity threshold that triggers adding to the list |
| `desired_quantity` | Target stock level (controls how much to buy) |
| `todo_list` | Target todo list entity (e.g. `todo.shopping_list`); must be a `todo.*` entity or empty |
| `todo_quantity_placement` | Where to show the needed quantity: `"name"` (e.g. "Milk (x4)"), `"description"`, or `"none"` |

**How it works:**

- When `quantity` drops to or below `auto_add_to_list_quantity` with `auto_add_enabled` on, the item is added to your todo list. A threshold of `0` — every item's default — only counts as "below threshold" *anywhere* (the sensor's `below_threshold` stat, low-stock voice/LLM queries, this list) when `auto_add_enabled` is also on; otherwise every out-of-stock item would match.
- With `desired_quantity > 0` (fixed mode): the todo shows that target quantity; the item comes off the list once `quantity` reaches it.
- With `desired_quantity = 0` (threshold mode, legacy): the todo shows `threshold - quantity + 1`, live-updated; the item comes off once `quantity` exceeds the threshold.
- The list stays in sync on every quantity change, rename, `todo_list` change, or when auto-add is disabled (which removes the entry). Imports sync the same way.
- Notes you add to an entry are preserved, unless `todo_quantity_placement` is `"description"` (the integration then owns the description).

**Note:** The core Shopping List integration does not support item descriptions, so description-based features only work with todo lists that do (for example Local To-do). The integration checks each list's supported features, not its entity id.

## Description with Inventory ID

Enable `auto_add_id_to_description_enabled` to append the inventory ID to item descriptions. This is useful when scanning barcodes from todo lists — the ID lets automations route the item back to the correct inventory. See [this issue](https://github.com/blaineventurine/simple_inventory/issues/19) for the use case. It also keeps same-named items from different inventories as separate entries on a shared todo list.

## Barcodes

Items can have multiple barcodes associated with them (comma-separated in the API). Most service calls accept either `name` or `barcode` to identify an item. Two dedicated barcode services make scanning workflows easy:

- **`lookup_by_barcode`** — Search for an item by barcode across all inventories
- **`scan_barcode`** — Scan a barcode and perform an action (increment, decrement, or lookup) with automatic cross-inventory resolution

A third service, [`lookup_barcode_product`](services.md#simple_inventorylookup_barcode_product), queries external product databases (Open Food Facts, Open Beauty Facts, Open Pet Food Facts, UPC Item DB) for a barcode's name/photo/category when it isn't in any inventory yet — useful for prefilling `add_item`, or for [setting an item's photo from the product lookup](#item-images).

> **Important:** Barcodes with leading zeros (e.g. `0123456`) **must be quoted** in YAML automations and scripts. Unquoted values like `barcode: 0123456` are interpreted as integers by YAML, stripping the leading zero and matching the wrong item. Always use `barcode: "0123456"`. This does not affect the HA service call UI or the WebSocket API, which handle strings correctly.

## Item Aliases

Items can have alternate names ("oats", "steel-cut oats", "hot cereal" for
an item named "Oatmeal") that resolve to the same item in service calls,
voice commands, and LLM tool calls. Set them via the `aliases` field
(comma-separated); an empty string clears them.

Lookups by name (`increment_item`, `decrement_item`, `update_item`'s
`old_name`) resolve aliases automatically using the same typo-tolerant
matching as real names. `remove_item` is stricter — exact name or alias
only, so a typo can't delete the wrong item.

Names and aliases must be unique within an inventory (case-insensitive,
Unicode-aware — "čokolada" clashes with "Čokolada"). Adding or renaming
onto an existing name or alias is rejected; `add_item`'s own `name` field
is never alias-resolved. Data that already clashed before this check
existed is reported as ambiguous on lookup rather than silently picked.

## Change History

Every add, increment, decrement, and quantity change made via `update_item`, `update_batch`, or `remove_batch` (event type `update`) is recorded with before/after quantities and timestamps. Imports record `import` events. A change that touches several batches records **one row per batch**, each carrying that batch's `batch_id` and location (`location_from` for consumption, `location_to` for restocks). The recorded `amount` is the change actually applied (a decrement clamped at zero records only what was removed; a no-op records nothing). Removing an item deletes its history with it. Query history via the WebSocket API. Moves made with [`transfer_item`](services.md#simple_inventorytransfer_item) are recorded as `transfer` events, one per source batch, with that batch's `batch_id`, `location_from` and the destination as `location_to`; they don't change the item's quantity (`quantity_before` equals `quantity_after`) and consumption analytics ignore them.

## Consumption Analytics

Track how fast you consume items. The integration calculates consumption rates based on decrement history:

- **Daily / weekly consumption rate** — How much you use per day or week
- **Days until depletion** — Estimated days before the item runs out at the current rate
- **Average restock interval** — How often you typically restock the item
- **Total consumed / events tracked** — Lifetime consumption totals. Events are counted per history row, and history is recorded per batch, so one decrement that consumes from two batches counts as two events (`decrement_count: 2`)

Consumption rates need at least 2 decrement events to mean anything; below that, `daily_rate`, `weekly_rate` and `days_until_depletion` come back `null` and the response's `has_sufficient_data` is `false` — check that field before trusting them. `avg_restock_days` is computed separately from restock events, so it can still be populated even when `has_sufficient_data` is `false`.

Rates can be calculated over a configurable time window (e.g. last 30, 60, or 90 days) or across all history. With a window, rates are divided by the shorter of the window and the time since the first decrement inside it (minimum one day), so a short history isn't diluted by an empty window. Spend rates are measured from the first priced restock. The companion card shows this data in a "Consumption" tab in the item history modal. You can also query rates via the service call or WebSocket API for use in automations.

> 🖼️ *Screenshot: the consumption tab in the item history modal* — replace with `![Consumption analytics tab](images/consumption-tab.png)`.

## Pricing

Track item prices to see inventory value and spending trends. Each item has an optional `price` field holding the last known unit price, and every [batch](#batches) records the unit price it was bought at.

- **Unit price**: Set when adding or editing an item. Update it whenever the price changes (e.g. at the next purchase).
- **Price on restock**: `increment_item`, `decrement_item`, and `scan_barcode` accept an optional `price` parameter. When provided, it updates the item's stored unit price and records the price on the history event; on a restock it is also the new batch's unit price. A positive `unit_price` set via `update_batch` also becomes the item's price.
- **Total value**: Retrievable via the `get_items` service call. Computed per batch as quantity × the batch's unit price; batches with a unit price of 0 are excluded.
- **Spend analytics**: The consumption tab shows spend data computed from restocking (increment/add) events that have a price recorded:
  - **Daily Spend** — Average daily purchasing cost over the observation window
  - **Weekly Spend** — Average weekly purchasing cost
  - **Total Spend** — Total money spent purchasing the item

> **Note:** A price of 0 means "no price set", not "free". Items with no price are excluded from value and spend calculations.

## Events

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

## Import and Export

Export your inventory to JSON or CSV, and import data back with configurable merge strategies (`skip`, `overwrite`, or `merge_quantities`). Available via the WebSocket API, or the [`export`](services.md#simple_inventoryexport) service for automation-triggered exports. Exports include every field, including all locations, categories, barcodes, aliases, and [batches](#batches), so an export can be re-imported without loss. Photos are the exception: `image` is exported as `true`/`false` (CSV: `1`/`0`) and ignored on import. Older exports without batches still import: their scalar quantity becomes one batch. See [`simple_inventory/import`](websocket-api.md#simple_inventoryimport) for validation and merge details. Pass `dry_run: true` to the WebSocket `import` command to preview a file's effect (added/updated/skipped counts and any errors) without writing anything.
