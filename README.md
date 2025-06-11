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

The integration will create two sensors, `sensor.whatever_inventory` and `sensor.items_expiring_soon`. You are free to add additional inventories, they will appear as separate sensors. When you add an inventory, you will be prompted to provide a name, and optional icon/description. A default `expiry_threshold` of 7 is set.

The `expiry_threshold` determines when to add an item to the `items_expiring_soon` sensor. If it is set to 7 days, when an item is seven days away from the expiring, it will be put on the `items_expiring_soon` list for you to build notifications/automations around.

Each inventory item can be given an expiration date, and optionally automatically added to a specific todo list if it reaches a certain threshold.

## Sample Automation

Sample automation for notifying about expiration dates coming soon:

```yaml
automation:
  - alias: "Notify about expiring inventory items"
    trigger:
      - platform: numeric_state
        entity_id: sensor.items_expiring_soon
        above: 0
      - platform: time
        at: "09:00:00"
    condition:
      - condition: numeric_state
        entity_id: sensor.items_expiring_soon
        above: 0
    action:
      - service: notify.mobile_app_your_phone
        data:
          title: "🗓️ Inventory Items Expiring Soon"
          message: >
            {% set expiring = state_attr('sensor.items_expiring_soon', 'expiring_items') %}
            {% set expired = state_attr('sensor.items_expiring_soon', 'expired_items') %}
            {% if expired %}
              ⚠️ {{ expired | length }} expired items: {{ expired[:3] | map(attribute='name') | join(', ') }}
            {% endif %}
            {% if expiring %}
              📅 {{ expiring | length }} expiring soon: {{ expiring[:3] | map(attribute='name') | join(', ') }}
            {% endif %}
          data:
            actions:
              - action: "view_inventory"
                title: "View Inventory"
```
