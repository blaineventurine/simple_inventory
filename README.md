[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)

# Simple Inventory

A Home Assistant custom integration for managing household inventories. Track items across multiple inventories with per-batch stock (expiry, location, purchase date, price), photos, barcode scanning, item aliases, locations and categories, automatic todo-list integration, consumption and spend analytics, voice and LLM control, and automatic backup/restore safety around every database upgrade.

> 🖼️ *Screenshot: the main inventory card view, showing a few items with photos, quantities, and low-stock highlighting* — replace this line with `![Simple Inventory card](images/card-overview.png)` once you have one.

## Documentation

- [Features](docs/features.md) — items, photos, batches, barcodes, aliases, locations & categories, auto-add, expiration, consumption analytics, pricing, events, import/export
- [Sensors](docs/sensors.md) — per-inventory and global sensor entities
- [Service Calls](docs/services.md) — the `simple_inventory.*` services
- [WebSocket API](docs/websocket-api.md) — the `simple_inventory/*` commands, error codes
- [Diagnostics & Repairs](docs/diagnostics-and-repairs.md)
- [Backups & Restore](docs/backups-and-restore.md)
- [Voice & AI Assistants](docs/voice-and-ai-assistants.md)
- [Automation Examples](docs/automation-examples.md)
- [Upgrading notes](docs/upgrading.md) — migration notes for past releases

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

> 🖼️ *Screenshot: the sidebar panel open on one inventory tab* — replace with `![Inventory sidebar panel](images/sidebar-panel.png)`.

- **Enable it:** Settings -> Devices & Services -> Simple Inventory -> the **All Items Expiring Soon** (global) entry -> **Configure** -> check **Show the Inventory panel in the sidebar**. Saving the options adds or removes the sidebar entry right away.
- **Admins only:** in the same dialog, check **Only administrators can see the panel** to hide it from non-admin users (default: every user sees it).
- **Requirements:** the panel's code ships with the [Simple Inventory Card](https://github.com/blaineventurine/simple-inventory-card) (`simple-inventory-panel.js`). Install the card through HACS, or copy its release files into `<config>/www/community/simple-inventory-card/` by hand. The panel loads `/api/simple_inventory/panel-loader.js` (no login needed, never cached), which imports `/local/community/simple-inventory-card/simple-inventory-panel.js` stamped with the file's modification time, so a card update reaches the browser on the next page load without restarting Home Assistant.
- **Missing file:** while the panel is enabled but that file is missing, the **Inventory panel needs the Simple Inventory card** repair issue is raised (see [Repairs](docs/diagnostics-and-repairs.md#repairs)). It clears on the next restart or options save after the file appears.
- **No global entry, no panel:** the setting lives on the global entry. If you deleted that entry, there is no panel (the global entry is not recreated).

## Configuration

Add via Home Assistant UI: **Settings -> Devices & Services -> Add Integration -> Simple Inventory**

When you create your first inventory, a global device is also created automatically. Each inventory becomes a device with three sensors.

You can edit inventory names, icons, and descriptions in the integration options flow after creation.
