# Simple Inventory Integration

A Home Assistant integration for managing household inventories.

## Installation

### Via HACS (Recommended)

1. Add this repository to HACS
2. Install "Simple Inventory"
3. Install the companion card: [Simple Inventory Card](https://github.com/blaineventurine/simple-inventory-card)
4. Restart Home Assistant

### Manual Installation

1. Copy `custom_components/simple_inventory/` to your Home Assistant `custom_components/` directory
2. Restart Home Assistant

## Frontend Card

This integration works best with the companion card:
**[Simple Inventory Card](https://github.com/blaineventurine/simple-inventory-card)**

## Configuration

Add via Home Assistant UI: Configuration → Integrations → Add Integration → Simple Inventory

The integration will create the inventory you specify as a device with two sensors: `sensor.whatever_inventory` and `sensor.whatever_items_expiring_soon`, along with a second device with a single `sensor.all_items_expiring_soon`. Each additional inventory you create will be added as a device with a sensor for the items, and a sensor for the items expiring soon.

### Expiration Dates

Each item you add to the inventory has a mandatory name, and several optional fields. You can set an expiration date, and an expiration date alert threshold. When the number of days left before expiration is equal to or below the threshold you set, the item will be added to the local inventory sensor for expiring items and to the global sensor.

The companion frontend card will show you two badges, one for items expiring soon, and one for expired items in the local inventory the card is assigned to. For now there is no global expiring items card - that sensor is mostly intended to build automations around.

### Auto-add to To-do List

Each item has an option to add it to a specific to-do list when the quantity remaining reaches a certain amount. The item will be added to the list when below, and removed from the list when incremented above.
