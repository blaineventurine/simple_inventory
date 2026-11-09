[← Back to README](../README.md)

# Sensors

## Per-Inventory Sensors

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

## Global Sensors

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
