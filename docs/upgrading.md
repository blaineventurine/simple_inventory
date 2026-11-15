[← Back to README](../README.md)

# Upgrading Notes

## Upgrading to 0.7.0

0.7.0 adds [batches](features.md#batches), stock transfers, per-item [icons](features.md#items) and [images](features.md#item-images). Back up Home Assistant before upgrading, and note:

- **Automatic database upgrade**: on first start the database moves from schema v3 to schema v6. No manual steps are needed, but the upgrade cannot be undone by downgrading.
  - Each item that has stock becomes one batch carrying its quantity, expiry date, first location, and price. Out-of-stock items get no batch, and their expiry date is cleared.
  - Every existing item gets an empty icon (the card shows its default icon) and no image. Images are stored in `<config>/simple_inventory/images/`, so they are part of Home Assistant backups.
- **Update the [Simple Inventory Card](https://github.com/blaineventurine/simple-inventory-card)** to its matching release. Older cards keep working but cannot edit individual batches. A plain restock (e.g. the card's `+` button) of an item that has an expiry date creates a separate batch without an expiry; once an item has several batches, its expiry can only be changed per batch, which needs the batch editor of the new card (or the [`update_batch`](services.md#simple_inventoryupdate_batch) service).
- **Expiry sensors count batches**: the expiring-soon and expired sensors count each expiring batch, so one item with two expiring batches counts twice.
- **Inventory sensor state**: `sensor.<name>_inventory`'s state changes from the sum of every item's `quantity` (meaningless once items use different units, e.g. grams and "each" summed together) to the count of distinct items in the inventory, which is what its `unit_of_measurement` ("items") describes. The old sum is still available as the `total_quantity` attribute. Any automation, template, or history graph that expects a quantity total from this sensor's state needs to read the `total_quantity` attribute instead.
- **Stricter dates**: `expiry_date` and `purchased_at` must be `YYYY-MM-DD` in every service.
- **Version handshake**: the new `simple_inventory/get_info` WebSocket command reports `api_version: 4` and the supported features.
