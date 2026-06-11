[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)

# Simple Inventory

A Home Assistant custom integration for managing household inventories. Track items across multiple inventories with expiration dates, automatic todo list integration, barcode support, locations, categories, and change history.

## Table of Contents

- [Installation](#installation)
- [Configuration](#configuration)
- [Features](#features)
- [Sensors](#sensors)
- [Service Calls](#service-calls)
- [WebSocket API](#websocket-api)
- [Automation Examples](#automation-examples)

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

## Configuration

Add via Home Assistant UI: **Settings -> Devices & Services -> Add Integration -> Simple Inventory**

When you create your first inventory, a global device is also created automatically. Each inventory becomes a device with three sensors.

You can edit inventory names, icons, and descriptions in the integration options flow after creation.

## Features

### Items

Each item has a **name** (required) and these optional fields:

| Field | Description |
|---|---|
| `quantity` | Current stock level (supports decimals, e.g. 2.5) |
| `unit` | Unit of measurement (e.g. "boxes", "L", "kg") |
| `description` | Free-text description |
| `barcode` | UPC/EAN barcode for scanning |
| `location` | Where the item is stored (supports multiple, comma-separated) |
| `category` | Item category (supports multiple, comma-separated) |
| `price` | Current unit price (updated when restocking or editing) |
| `expiry_date` | Expiration date (YYYY-MM-DD) |
| `expiry_alert_days` | Days before expiry to trigger alerts |

### Multi-Value Locations and Categories

Items can belong to multiple locations and categories. Pass comma-separated values:

```yaml
location: "Pantry, Kitchen"
category: "Snacks, Bulk Items"
```

The API returns both scalar fields (`location`, `category` with the first value) and array fields (`locations`, `categories` with all values) for backward compatibility.

### Expiration Tracking

Set an `expiry_date` and `expiry_alert_days` on any item. When the number of remaining days is at or below your threshold, the item appears on the expiry sensors. Items with zero quantity are excluded from expiry alerts.

### Auto-Add to Todo List

Automatically add items to a Home Assistant todo list when stock drops below a threshold. Configure these fields:

| Field | Description |
|---|---|
| `auto_add_enabled` | Enable/disable auto-add for this item |
| `auto_add_to_list_quantity` | Quantity threshold that triggers adding to the list |
| `desired_quantity` | Target stock level (controls how much to buy) |
| `todo_list` | Target todo list entity (e.g. `todo.shopping_list`) |
| `todo_quantity_placement` | Where to show the needed quantity: `"name"` (e.g. "Milk (x4)"), `"description"`, or `"none"` |

**How it works:**

- When `quantity` drops to or below `auto_add_to_list_quantity`, the item is added to your todo list
- When `desired_quantity > 0` (fixed mode): the todo shows the desired quantity, and the item is removed from the list when `quantity >= desired_quantity`
- When `desired_quantity = 0` (threshold mode): the todo shows `threshold - quantity + 1`, updates live on each change, and the item is removed when `quantity > threshold`

**Note:** The built-in `todo.shopping_list` does not support item descriptions, so description-based features only work with other todo list integrations.

### Description with Inventory ID

Enable `auto_add_id_to_description_enabled` to append the inventory ID to item descriptions. This is useful when scanning barcodes from todo lists — the ID lets automations route the item back to the correct inventory. See [this issue](https://github.com/blaineventurine/simple_inventory/issues/19) for the use case.

### Barcodes

Items can have multiple barcodes associated with them (comma-separated in the API). Most service calls accept either `name` or `barcode` to identify an item. Two dedicated barcode services make scanning workflows easy:

- **`lookup_by_barcode`** — Search for an item by barcode across all inventories
- **`scan_barcode`** — Scan a barcode and perform an action (increment, decrement, or lookup) with automatic cross-inventory resolution

> **Important:** Barcodes with leading zeros (e.g. `0123456`) **must be quoted** in YAML automations and scripts. Unquoted values like `barcode: 0123456` are interpreted as integers by YAML, stripping the leading zero and matching the wrong item. Always use `barcode: "0123456"`. This does not affect the HA service call UI or the WebSocket API, which handle strings correctly.

### Change History

Every add, remove, increment, and decrement is recorded with before/after quantities and timestamps. Query history via the WebSocket API.

### Consumption Analytics

Track how fast you consume items. The integration calculates consumption rates based on decrement history:

- **Daily / weekly consumption rate** — How much you use per day or week
- **Days until depletion** — Estimated days before the item runs out at the current rate
- **Average restock interval** — How often you typically restock the item
- **Total consumed / events tracked** — Lifetime consumption totals

Rates can be calculated over a configurable time window (e.g. last 30, 60, or 90 days) or across all history. The companion card shows this data in a "Consumption" tab in the item history modal. You can also query rates via the service call or WebSocket API for use in automations.

### Pricing

Track item prices to see inventory value and spending trends. Each item has an optional `price` field representing the current unit price.

- **Unit price**: Set when adding or editing an item. Update it whenever the price changes (e.g. at the next purchase).
- **Price on restock**: `increment_item`, `decrement_item`, and `scan_barcode` accept an optional `price` parameter. When provided, it updates the item's stored unit price and records the price on the history event.
- **Total value**: Retrievable via the `get_items` service call. Items with `price = 0` are excluded from the calculation.
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
| `simple_inventory_item_added_to_list` | Item is newly added to a todo list |
| `simple_inventory_item_removed_from_list` | Item is removed from a todo list |

**Event payloads:**

`item_added`: `item_name`, `inventory_id`, `quantity`
`item_removed`: `item_name`, `inventory_id`
`item_quantity_changed`: `item_name`, `inventory_id`, `quantity_before`, `quantity_after`, `amount`, `direction` (`"increment"` or `"decrement"`)
`item_depleted`: `item_name`, `inventory_id`, `previous_quantity`
`item_restocked`: `item_name`, `inventory_id`, `quantity`
`item_added_to_list`: `item_name`, `inventory_id`, `quantity`, `todo_list`, `quantity_needed`
`item_removed_from_list`: `item_name`, `inventory_id`, `quantity`, `todo_list`

### Import and Export

Export your inventory to JSON or CSV, and import data back with configurable merge strategies (`skip`, `overwrite`, or `merge_quantities`). Available via the WebSocket API.

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
  - `below_threshold` — Items that need restocking, each with `name`, `quantity`, `threshold`, `desired_quantity`, `quantity_needed`, `unit`, `category`
  - `expiring_soon` — Count of items expiring within their alert threshold

**`sensor.<name>_items_expiring_soon`** — Expiry alert sensor
- **State**: Count of items within their alert threshold but not yet expired
- **Icon**: `mdi:calendar-alert` when items are expiring, `mdi:calendar-check` when all clear
- **Attributes**:
  - `expiring_items` — List of items expiring soon (days_until_expiry ≥ 0)
  - `expired_items` — List of already-expired items (for reference)
  - `total_expiring`, `total_expired` — Counts

**`sensor.<name>_expired_items`** — Expired items sensor
- **State**: Count of items past their expiration date
- **Icon**: `mdi:calendar-remove` (fixed)
- **Attributes**:
  - `expired_items` — List of expired items
  - `total_expired` — Count
  - `inventory_id`, `inventory_name`

### Global Sensors

**`sensor.all_items_expiring_soon`** — Aggregates expiring-soon items across ALL inventories
- **State**: Count of items within their alert threshold but not yet expired
- **Icon**: Progressive severity (`mdi:calendar-alert` → `mdi:calendar-clock` → `mdi:calendar-week` → `mdi:calendar-check`)
- **Attributes**:
  - `expiring_items`, `expired_items` — Aggregated lists
  - `next_expiring`, `oldest_expired` — Soonest/oldest dates
  - `inventories_count` — Number of inventories with matching items

**`sensor.all_expired_items`** — Aggregates expired items across ALL inventories
- **State**: Count of items past their expiration date across all inventories
- **Icon**: `mdi:calendar-remove` (fixed)
- **Attributes**:
  - `expired_items` — Aggregated list of expired items
  - `total_expired` — Count
  - `oldest_expired` — The most overdue item
  - `inventories_count` — Number of inventories with expired items

## Service Calls

All services are under the `simple_inventory` domain. You can find your inventory ID by going to **Developer Tools -> States** and filtering for "inventory" — the ID is shown in the sensor attributes.

### `simple_inventory.add_item`

Add a new item to an inventory.

```yaml
service: simple_inventory.add_item
data:
  inventory_id: "01JYFPCDMBRBRK4MB3C26S2FKH"
  name: "Frozen Pizza"
  quantity: 5
  unit: "boxes"
  category: "Frozen Foods"
  location: "Basement Freezer"
  price: 8.99
  barcode: "012345678901"
  expiry_date: "2026-06-15"
  expiry_alert_days: 7
  auto_add_enabled: true
  auto_add_to_list_quantity: 2
  desired_quantity: 5
  todo_list: "todo.grocery_list"
  todo_quantity_placement: "name"
  description: "Family size pepperoni"
```

Only `inventory_id` and `name` are required. All other fields are optional.

### `simple_inventory.remove_item`

Remove an item. Specify either `name` or `barcode`.

```yaml
service: simple_inventory.remove_item
data:
  inventory_id: "01JYFPCDMBRBRK4MB3C26S2FKH"
  name: "Frozen Pizza"
```

### `simple_inventory.increment_item`

Increase an item's quantity. Supports decimal amounts. Optionally pass `price` to update the item's unit price (e.g. when restocking at a new price).

```yaml
service: simple_inventory.increment_item
data:
  inventory_id: "01JYFPCDMBRBRK4MB3C26S2FKH"
  name: "Frozen Pizza"
  amount: 3
  price: 9.49
```

You can also use `barcode` instead of `name`:

```yaml
service: simple_inventory.increment_item
data:
  inventory_id: "01JYFPCDMBRBRK4MB3C26S2FKH"
  barcode: "012345678901"
  amount: 1
```

### `simple_inventory.decrement_item`

Decrease an item's quantity. Same parameters as `increment_item`.

```yaml
service: simple_inventory.decrement_item
data:
  inventory_id: "01JYFPCDMBRBRK4MB3C26S2FKH"
  name: "Frozen Pizza"
  amount: 1
```

### `simple_inventory.update_item`

Update any fields on an existing item. Use `old_name` to identify the item and `name` for the (possibly new) name.

```yaml
service: simple_inventory.update_item
data:
  inventory_id: "01JYFPCDMBRBRK4MB3C26S2FKH"
  old_name: "Frozen Pizza"
  name: "Frozen Pizza"
  category: "Frozen Foods, Quick Meals"
  location: "Kitchen Freezer"
  expiry_date: "2026-08-01"
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
      "barcodes": ["012345678901"]
    }
  ]
}
```

Note the dual fields: `category`/`categories` and `location`/`locations`. The singular fields contain only the first value for backward compatibility. Prefer the array fields.

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

## WebSocket API

The integration provides WebSocket commands for real-time communication. These are used by the companion card and can also be used by custom panels or scripts.

### `simple_inventory/list_items`

Fetch all items for an inventory.

```json
{
  "type": "simple_inventory/list_items",
  "inventory_id": "01JYFPCDMBRBRK4MB3C26S2FKH"
}
```

Returns: `{ "items": [...] }`

### `simple_inventory/get_item`

Fetch a single item by name.

```json
{
  "type": "simple_inventory/get_item",
  "inventory_id": "01JYFPCDMBRBRK4MB3C26S2FKH",
  "name": "Frozen Pizza"
}
```

Returns: `{ "item": { ... } }`

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

All fields except `inventory_id` are optional. Supported `event_type` values: `add`, `remove`, `increment`, `decrement`, `update`.

Returns: `{ "events": [...] }` where each event has:
- `event_type` — What happened
- `amount` — How much changed
- `quantity_before`, `quantity_after` — Stock levels
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

### `simple_inventory/lookup_by_barcode`

Search for an item by barcode across all inventories.

```json
{
  "type": "simple_inventory/lookup_by_barcode",
  "barcode": "012345678901"
}
```

Returns: `{ "items": [...] }` — each item includes `inventory_id` and `inventory_name`.

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

Only `barcode` and `action` are required. `amount` defaults to 1. `inventory_id` is optional unless the barcode exists in multiple inventories.

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

Merge strategies:
- `skip` — Skip items that already exist (default)
- `overwrite` — Replace existing items with imported data
- `merge_quantities` — Add imported quantities to existing quantities

Returns: `{ "added": 1, "updated": 0, "skipped": 0, "errors": [] }`

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
          title: "Items expiring soon"
          message: >
            {{ state_attr('sensor.all_items_expiring_soon', 'total_expiring') }} items expiring soon,
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
