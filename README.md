[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)

# Simple Inventory Integration

A Home Assistant integration for managing household inventories.

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

This integration works best with the companion card:
**[Simple Inventory Card](https://github.com/blaineventurine/simple-inventory-card)**

## Configuration

Add via Home Assistant UI: Settings → Devices & Services → Add Integration → Simple Inventory

The integration will create the inventory you specify as a device with two sensors:

- `sensor.whatever_inventory`
- `sensor.whatever_items_expiring_soon`

along with a second device with a single `sensor.all_items_expiring_soon`.

Each additional inventory you create will be added as a device with a sensor for the items, and a sensor for the items expiring soon.

### Expiration Dates

Each item you add to the inventory has a mandatory name, and several optional fields. You can set an expiration date, and an expiration date alert threshold. When the number of days left before expiration is equal to or below the threshold you set, the item will be added to the local inventory sensor for expiring items and to the global sensor.

The companion frontend card will show you two badges, one for items expiring soon, and one for expired items in the local inventory the card is assigned to. For now there is no global expiring items card - that sensor is mostly intended to build automations around.

### Auto-add to To-do List

Each item has an option to add it to a specific to-do list when the quantity remaining reaches a certain amount. The item will be added to the list when below, and removed from the list when incremented above.

### Automations

This integration exposes the following actions:

- `add_item`
- `remove_item`
- `update_item`
- `increment_item`
- `decrement_item`
- `get_items` (returns data)
- `get_items_from_all_inventories` (returns data)

which can be used in automations. For example, if I call `simple_inventory.increment_item` with:

```yaml
inventory_id: "01JYFPCDMBRBRK4MB3C26S2FKH"
name: "frozen pizzas"
amount: 1
```

<img width="1085" height="506" alt="image" src="https://github.com/user-attachments/assets/5e1c2411-4d5e-46f9-abc3-2c8dcb639305" />

it will increment the amount by 1. The amount field is how much you want to increment it by. You can get the inventory ID by going to Developer Tools → States, then filtering on “inventory” and you will see a list of your inventories and their IDs in the Attributes column.

### Retrieve all items in an inventory

Use the `simple_inventory.get_items` service to get the full list of items for a specific inventory. This service supports responses; in Developer Tools → Services, set `return_response: true` to receive the data back.

You can specify the inventory either by its ID or by its name (case-insensitive). Examples:

By inventory ID:
```yaml
inventory_id: "01JYFPCDMBRBRK4MB3C26S2FKH"
```

By inventory name:
```yaml
inventory_name: "Kitchen Freezer"
```

Example response:

```json
{
  "items": [
    {
      "name": "Milk",
      "quantity": 1,
      "unit": "L",
      "category": "Dairy",
      "expiry_date": "2025-11-10",
      "expiry_alert_days": 3,
      "auto_add_enabled": true,
      "auto_add_to_list_quantity": 1,
      "todo_list": "todo.grocery_list",
      "location": "Fridge"
    }
  ]
}
```

### Retrieve items from all inventories

Use the `simple_inventory.get_items_from_all_inventories` service to fetch every inventory at once. Like the per-inventory call, set `return_response: true` when calling this service to receive the aggregated data.

Example call:

```yaml
service: simple_inventory.get_items_from_all_inventories
return_response: true
```

Example response:

```json
{
  "inventories": [
    {
      "inventory_id": "01JYFPCDMBRBRK4MB3C26S2FKH",
      "inventory_name": "Kitchen Fridge",
      "description": "Fresh items",
      "items": [
        {
          "name": "Milk",
          "quantity": 1,
          "unit": "L"
        }
      ]
    }
  ]
}
```
