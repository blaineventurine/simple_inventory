[← Back to README](../README.md)

# Upgrading Notes

## Upgrading to 0.12.0

`sensor.<name>_inventory`'s state changes from the sum of every item's
`quantity` (meaningless once items use different units - e.g. grams and
"each" summed together) to the count of distinct items in the inventory,
which is what its `unit_of_measurement` ("items") actually describes. The
old sum is still available as the `total_quantity` attribute, unchanged.
Any automation, template, or history graph keyed off this sensor's state
expecting a quantity total needs to switch to reading the `total_quantity`
attribute instead. `simple_inventory/get_info` now reports `api_version: 4`.

## Upgrading to 0.11.0

0.11.0 adds [item images](features.md#item-images). On first start the database moves to schema v6: every existing item gets an empty `image` (no photo). Photos are stored in `<config>/simple_inventory/images/`, so they are part of Home Assistant backups. No manual steps are needed; like every schema upgrade it cannot be undone by downgrading. `simple_inventory/get_info` now also reports the `item_images` feature; `api_version` stays `3`.

## Upgrading to 0.10.0

0.10.0 adds a per-item [`icon`](features.md#items). On first start the database moves to schema v5: every existing item gets an empty icon (the card shows its default icon). No manual steps are needed; like every schema upgrade it cannot be undone by downgrading. `simple_inventory/get_info` now also reports the `item_icons` feature; `api_version` stays `3`.

## Upgrading to 0.8.0

0.8.0 introduces [batches](features.md#batches). Before upgrading, note:

- **Automatic database upgrade** — on first start the database moves to schema v4. Each item that has stock becomes one batch carrying its quantity, expiry date, first location, and price; out-of-stock items get no batch and their expiry date is cleared. No manual steps are needed, but the upgrade cannot be undone by downgrading.
- **Update the [Simple Inventory Card](https://github.com/blaineventurine/simple-inventory-card)** to its batches-aware release. Older cards keep working but cannot edit individual batches. A plain restock (e.g. the card's `+` button) of an item that has an expiry date creates a separate batch without an expiry; once an item has several batches, its expiry can only be changed per batch, which needs the batch editor of the new card (or the [`update_batch`](services.md#simple_inventoryupdate_batch) service).
- **Expiry sensors count batches** — the expiring-soon and expired sensors count each expiring batch, so one item with two expiring batches counts twice.
- **Stricter dates** — `expiry_date` and `purchased_at` must be `YYYY-MM-DD` in every service.
- **API version 3** — `simple_inventory/get_info` reports `api_version: 3` (with the `batches` feature).
