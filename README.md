Add custom card, use:

```yaml
type: custom:simple-inventory-card
entity: sensor.simple_inventory
```

May need to edit dashboard -> settings -> add this as a resource:

```yaml
/local/community/simple-inventory-card/simple-inventory-card.js
```

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
