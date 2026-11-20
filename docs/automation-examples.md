[← Back to README](../README.md)

# Automation Examples

## Notify when an item is added to your shopping list

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

## Alert when something runs out

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

## Barcode scanner: increment on scan

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

## Barcode scanner: decrement on scan (checking out items)

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

## Barcode lookup: find which inventory has an item

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

## Barcode scanner with mode toggle

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

## Notify when items expire

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
          title: "Expiring soon"
          message: >
            {{ state_attr('sensor.all_items_expiring_soon', 'total_expiring') }} batches expiring soon,
            {{ state_attr('sensor.all_items_expiring_soon', 'total_expired') }} already expired.
```

## Low stock alert

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

## Alert when consumption rate spikes

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

## Alert when an item is running low

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

## Get inventory data in a script

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

## Cross-inventory low stock summary

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
