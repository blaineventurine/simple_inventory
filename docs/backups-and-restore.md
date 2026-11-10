[← Back to README](../README.md)

# Backups & Restore

The database (`<config>/simple_inventory.db`) and item photos (`<config>/simple_inventory/images/`) already live under Home Assistant's config directory, so a full HA backup (Settings -> System -> Backups) captures and restores them automatically. Simple Inventory checkpoints its write-ahead log before every HA backup runs, so that capture is always consistent.

On top of that, Simple Inventory keeps its own lightweight snapshots in `<config>/simple_inventory/backups/`. Automatic and manual snapshots share one pool of **3**: taking a new one (of either kind) prunes the oldest until 3 remain, so a manual snapshot you're relying on can be pruned by a later automatic one (or vice versa) — call `backup_database` again right before you need it, rather than relying on one taken earlier.

- **Automatic**: right before a database schema upgrade runs (on update to a release with a newer schema), a snapshot of the pre-upgrade database is taken. If the upgrade fails partway through, a **Database upgrade failed** repair issue appears in Settings -> Repairs (see [Repairs](diagnostics-and-repairs.md#repairs) above); confirming it restores that snapshot and reloads every Simple Inventory entry.
- **On demand**: call [`backup_database`](services.md#simple_inventorybackup_database) before a risky change (e.g. a large import), and [`restore_database`](services.md#simple_inventoryrestore_database) to roll back to it or any other recent snapshot.

Restoring, automatic or manual, replaces the live database with the snapshot's contents and reloads every Simple Inventory config entry, since they all share one database.
