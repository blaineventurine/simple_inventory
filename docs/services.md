[← Back to README](../README.md)

# Service Calls

All services are under the `simple_inventory` domain. You can find your inventory ID by going to **Developer Tools -> States** and filtering for "inventory" — the ID is shown in the sensor attributes. Unless a service says otherwise, identify the inventory with either `inventory_id` or `inventory_name` (not both); errors use a stable `translation_key` — see [Error codes](websocket-api.md#error-codes) for the full list.

**Item CRUD**
| Service | Purpose |
|---|---|
| [`add_item`](#simple_inventoryadd_item) | Add a new item |
| [`remove_item`](#simple_inventoryremove_item) | Remove an item |
| [`increment_item`](#simple_inventoryincrement_item) | Add stock (a new or merged [batch](features.md#batches)) |
| [`decrement_item`](#simple_inventorydecrement_item) | Consume stock, soonest-expiring batch first |
| [`update_item`](#simple_inventoryupdate_item) | Edit any field on an existing item |

**Batches & Transfers**
| Service | Purpose |
|---|---|
| [`update_batch`](#simple_inventoryupdate_batch) | Edit one batch's quantity, expiry, location, price or purchase date |
| [`remove_batch`](#simple_inventoryremove_batch) | Delete one batch |
| [`transfer_item`](#simple_inventorytransfer_item) | Move stock between locations of the same inventory |

**Photos**
| Service | Purpose |
|---|---|
| [`set_item_image_from_barcode`](#simple_inventoryset_item_image_from_barcode) | Set an item's photo from its barcode's product lookup |
| [`set_item_image_from_media`](#simple_inventoryset_item_image_from_media) | Set an item's photo from a Home Assistant media source |
| [`clear_item_image`](#simple_inventoryclear_item_image) | Remove an item's photo |

**Listing & Analytics**
| Service | Purpose |
|---|---|
| [`get_items`](#simple_inventoryget_items) | List every item in one inventory |
| [`get_items_from_all_inventories`](#simple_inventoryget_items_from_all_inventories) | List every item, grouped by inventory |
| [`get_inventory_consumption_rates`](#simple_inventoryget_inventory_consumption_rates) | Consumption rates for every item in an inventory, plus a summary |
| [`get_item_consumption_rates`](#simple_inventoryget_item_consumption_rates) | Consumption rates for one item |

**Barcode**
| Service | Purpose |
|---|---|
| [`lookup_by_barcode`](#simple_inventorylookup_by_barcode) | Find which inventory/inventories have an item with this barcode |
| [`lookup_barcode_product`](#simple_inventorylookup_barcode_product) | Look up a barcode in external product databases |
| [`scan_barcode`](#simple_inventoryscan_barcode) | Scan a barcode and increment/decrement/look up the matched item |

**Backups & Export**
| Service | Purpose |
|---|---|
| [`backup_database`](#simple_inventorybackup_database) | Take an on-demand database snapshot |
| [`restore_database`](#simple_inventoryrestore_database) | Restore the database from a snapshot |
| [`export`](#simple_inventoryexport) | Export one inventory as JSON or CSV |

## `simple_inventory.add_item`

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

`name` is required (plus `inventory_id` or `inventory_name`, per the rule above); every other field is optional. A non-zero `quantity` becomes the item's first [batch](features.md#batches), using `expiry_date`, the first `location`, and `price`.

## `simple_inventory.remove_item`

Remove an item. Specify either `name` or `barcode`. `name` must match the item's name or one of its aliases exactly (case-insensitive); no fuzzy matching is applied.

```yaml
service: simple_inventory.remove_item
data:
  inventory_id: "01JYFPCDMBRBRK4MB3C26S2FKH"
  name: "Frozen Pizza"
```

## `simple_inventory.increment_item`

Increase an item's quantity by adding a [batch](features.md#batches) (or merging into a matching one). Supports decimal amounts. Optionally pass `price` to update the item's unit price (e.g. when restocking at a new price).

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
| `price` | Unit price of this stock; also becomes the item's price. `0` (the default) means "don't update the price," not "set it to zero" |
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

## `simple_inventory.decrement_item`

Decrease an item's quantity. Stock is taken from the batch expiring soonest (see [Batches](features.md#batches)). Accepts `name`/`barcode`, `amount`, and `price` like `increment_item`, plus:

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

## `simple_inventory.update_item`

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

`location` here sets the item's usual storage places; it does not move existing batches (use `update_batch`). The scalar stock fields map onto [batches](features.md#batches):

- `quantity` — an increase adds a batch (with the requested `expiry_date`, the item's price, and the item's first usual location); a decrease consumes batches in soonest-expiry order. Recorded as `update` events.
- `expiry_date` / `price` — applied to the batch when the item has exactly one. A value equal to the current one is ignored, so re-saving an unchanged form is a no-op. Changing them on an item with several batches is rejected with `batch_required` — edit the batch with `update_batch` instead. Changing `expiry_date` on an item with no stock is rejected with `no_stock_for_expiry` — restock it with an expiry date instead (a `price` change there only sets the item's price).

**Batches & Transfers**

## `simple_inventory.update_batch`

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

## `simple_inventory.remove_batch`

Delete one batch (recorded as an `update` event taking its quantity away).

```yaml
service: simple_inventory.remove_batch
data:
  inventory_id: "01JYFPCDMBRBRK4MB3C26S2FKH"
  batch_id: "6f1c2e0a-3b7d-4f5e-9a12-0c4d8e7b9a31"
```

## `simple_inventory.transfer_item`

Move stock of an item to another location in the same inventory. Identify the item by `name` (or alias) or `barcode`, and the inventory by `inventory_id` or `inventory_name`.

| Field | Description |
|---|---|
| `to_location` | **Required.** Where the stock goes. A new name creates the location, and the destination is added to the item's usual locations if missing (the first usual location stays first) |
| `amount` | How much to move (greater than 0). Omit it to move everything at the source |
| `batch_id` | Move from exactly this batch (`batch_not_found` if it isn't one of the item's batches); takes precedence over `from_location` |
| `from_location` | Move only stock stored here, soonest expiry first (`no_stock_at_location` if there is none) |

Without `batch_id` or `from_location`, the soonest-expiring stock that is **not already at the destination** is moved, continuing into the next batch in [consumption order](features.md#batches).

```yaml
service: simple_inventory.transfer_item
data:
  inventory_id: "01JYFPCDMBRBRK4MB3C26S2FKH"
  name: "Milk"
  amount: 2
  from_location: "Fridge"
  to_location: "Garage Fridge"
```

Moved stock keeps its expiry date, unit price and purchase date. At the destination it joins a batch with the same expiry date and unit price (keeping the earliest purchase date); a source batch that is emptied is deleted. The item's total quantity doesn't change, so no quantity, depleted or restocked events fire and todo lists are left alone; one [`simple_inventory_item_transferred`](features.md#events) event fires instead, and each source batch gets a `transfer` history row.

Nothing is changed when the move can't be made:

- `insufficient_stock` — the source holds less than `amount` (or nothing at all)
- `same_location` — the source is already the destination
- `batch_not_found`, `no_stock_at_location`, `item_not_found` — as for `decrement_item`

**Photos**

## `simple_inventory.set_item_image_from_barcode`

Use the product photo of a barcode lookup as the item's [photo](features.md#item-images). Identify the item by `name` (or alias, exact match) or `barcode`, and the inventory by `inventory_id` or `inventory_name`. `lookup_barcode` picks the barcode to look up; it must be one of the item's barcodes and defaults to its first one (sorted). The lookup uses the [configured provider](websocket-api.md#simple_inventoryset_barcode_provider_config) (or all of them); the first result with a photo wins. Only that photo URL is fetched (`http`/`https`, at most 10 MB within 10 seconds) — the service never takes a URL from the caller.

```yaml
service: simple_inventory.set_item_image_from_barcode
data:
  inventory_id: "01JYFPCDMBRBRK4MB3C26S2FKH"
  name: "Milk"
```

Errors: `image_not_found` (the item has no barcode, or the lookup has no photo), `barcode_not_on_item`, `image_download_failed`, `image_too_large`, `image_invalid`.

## `simple_inventory.set_item_image_from_media`

Copy an image from Home Assistant's local media folders (`media_dirs`, e.g. `/media`) or one uploaded through Home Assistant's own image upload (`media-source://image_upload/<id>`, stored as `<config>/image/<id>/original`) as the item's [photo](features.md#item-images). Other media sources (cameras, TTS, add-ons) are rejected with `unsupported_media_source`, as is anything outside those folders and any image upload id that isn't 32 lowercase hex characters.

```yaml
service: simple_inventory.set_item_image_from_media
data:
  inventory_id: "01JYFPCDMBRBRK4MB3C26S2FKH"
  name: "Milk"
  media_content_id: "media-source://media_source/local/pantry/milk.jpg"
```

## `simple_inventory.clear_item_image`

Remove the item's [photo](features.md#item-images); does nothing when it has none.

```yaml
service: simple_inventory.clear_item_image
data:
  inventory_id: "01JYFPCDMBRBRK4MB3C26S2FKH"
  barcode: "012345678901"
```

**Listing & Analytics**

## `simple_inventory.get_items`

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

## `simple_inventory.get_items_from_all_inventories`

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

## `simple_inventory.get_inventory_consumption_rates`

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

## `simple_inventory.get_item_consumption_rates`

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

**Barcode**

## `simple_inventory.lookup_by_barcode`

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

## `simple_inventory.lookup_barcode_product`

Look up product information for a barcode, for example to pre-fill a new item. Supports `response_variable` for use in automations and scripts.

```yaml
service: simple_inventory.lookup_barcode_product
data:
  barcode: "012345678901"
response_variable: product
```

If an item in any inventory already has the barcode, only that item is reported (as provider `inventory`, with its `name` and, when set, `description`, `category` and `unit`) and no external database is queried. Otherwise the external providers are queried in parallel: only the one selected with [`simple_inventory/set_barcode_provider_config`](websocket-api.md#simple_inventoryset_barcode_provider_config), or all of `openfoodfacts`, `openbeautyfacts`, `openpetfoodfacts` and `upcitemdb` when none is selected. Each provider gets a 10-second timeout; a slow or unreachable one just reports `"found": false` rather than delaying the others.

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

## `simple_inventory.scan_barcode`

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
| `price` | No | Unit price to record for this transaction (updates the item's stored price). `0` means "don't update" |
| `inventory_id` | No | Scope the search to a specific inventory. Required if the barcode exists in multiple inventories. |
| `expiry_date` | No | Increment only: expiry of the new stock |
| `location` | No | Increment: where the new stock is stored. Decrement: only consume batches there |
| `purchased_at` | No | Increment only: purchase date `YYYY-MM-DD` |
| `batch_id` | No | Decrement only: consume from exactly this batch |

Increments and decrements follow the [batch rules](features.md#batches). They need the item's inventory to be loaded (`inventory_not_loaded` otherwise, e.g. for a disabled inventory); a `lookup` without `inventory_id` answers for an item in any inventory, like [`lookup_by_barcode`](#simple_inventorylookup_by_barcode).

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
- Barcode not found in any inventory: raises an error (`barcode_not_found`)
- Barcode found in multiple inventories without `inventory_id`: raises an error listing the inventories (`ambiguous_barcode`)

**Backups & Export**

## `simple_inventory.backup_database`

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

## `simple_inventory.restore_database`

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

## `simple_inventory.export`

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
