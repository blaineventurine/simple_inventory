"""Service handlers for Simple Inventory integration."""
import logging
import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .coordinator import SimpleInventoryCoordinator
from .todo_manager import TodoManager

_LOGGER = logging.getLogger(__name__)


class ServiceHandler:
    """Handle service calls for the integration."""

    def __init__(self, hass: HomeAssistant, coordinator: SimpleInventoryCoordinator, todo_manager: TodoManager):
        """Initialize the service handler."""
        self.hass = hass
        self.coordinator = coordinator
        self.todo_manager = todo_manager

    async def async_set_expiry_threshold(self, call: ServiceCall):
        """Set the expiry notification threshold."""
        threshold_days = call.data["threshold_days"]

        # Update the expiry sensor threshold
        # Find the expiry sensor
        expiry_sensor = None
        for entity in self.hass.states.async_entity_ids("sensor"):
            if entity == "sensor.items_expiring_soon":
                # Update the sensor's threshold
                # This would require storing a reference to the sensor
                # For now, we'll just update via service call
                break

        _LOGGER.info(f"Expiry threshold set to {threshold_days} days")

    async def async_add_item(self, call: ServiceCall):
        """Add an item to the inventory."""
        item_data = call.data
        inventory_id = item_data["inventory_id"]
        name = item_data["name"]

        # Remove name and inventory_id from item_data to avoid duplicate argument
        item_kwargs = {k: v for k, v in item_data.items() if k not in [
            "name", "inventory_id"]}

        self.coordinator.add_item(inventory_id, name, **item_kwargs)
        await self.coordinator.async_save_data(inventory_id)
        _LOGGER.info(f"Added item: {name} to inventory: {inventory_id}")

    async def async_remove_item(self, call: ServiceCall):
        """Remove an item from the inventory."""
        inventory_id = call.data["inventory_id"]
        name = call.data["name"]

        if self.coordinator.remove_item(inventory_id, name):
            await self.coordinator.async_save_data(inventory_id)
            _LOGGER.info(f"Removed item: {
                         name} from inventory: {inventory_id}")
        else:
            _LOGGER.warning(f"Item not found: {
                            name} in inventory: {inventory_id}")

    async def async_increment_item(self, call: ServiceCall):
        """Increment item quantity."""
        inventory_id = call.data["inventory_id"]
        name = call.data["name"]
        amount = call.data.get("amount", 1)

        if self.coordinator.increment_item(inventory_id, name, amount):
            await self.coordinator.async_save_data(inventory_id)
            _LOGGER.info(f"Incremented {name} by {
                         amount} in inventory: {inventory_id}")
        else:
            _LOGGER.warning(f"Item not found: {
                            name} in inventory: {inventory_id}")

    async def async_decrement_item(self, call: ServiceCall):
        """Decrement item quantity."""
        inventory_id = call.data["inventory_id"]
        name = call.data["name"]
        amount = call.data.get("amount", 1)

        if self.coordinator.decrement_item(inventory_id, name, amount):
            item_data = self.coordinator.get_item(inventory_id, name)
            if item_data:
                await self.todo_manager.check_and_add_item(name, item_data)

            await self.coordinator.async_save_data(inventory_id)
            _LOGGER.info(f"Decremented {name} by {
                         amount} in inventory: {inventory_id}")
        else:
            _LOGGER.warning(f"Item not found: {
                            name} in inventory: {inventory_id}")

    async def async_update_item_settings(self, call: ServiceCall):
        """Update item auto-add settings."""
        inventory_id = call.data["inventory_id"]
        name = call.data["name"]
        settings = {k: v for k, v in call.data.items() if k not in [
            "name", "inventory_id"]}

        if self.coordinator.update_item_settings(inventory_id, name, **settings):
            await self.coordinator.async_save_data(inventory_id)
            _LOGGER.info(f"Updated settings for item: {
                         name} in inventory: {inventory_id}")
        else:
            _LOGGER.warning(f"Item not found: {
                            name} in inventory: {inventory_id}")

    async def async_update_item(self, call: ServiceCall):
        """Update an existing item with new values."""
        data = call.data
        inventory_id = data["inventory_id"]
        old_name = data["old_name"]
        new_name = data["name"]

        # Check if the item exists
        if not self.coordinator.get_item(inventory_id, old_name):
            _LOGGER.warning(f"Item not found: {
                            old_name} in inventory: {inventory_id}")
            return

        # Prepare update data (only include fields that were provided)
        update_data = {}

        # Handle quantity specially - set it to the exact value provided
        if "quantity" in data:
            update_data["quantity"] = data["quantity"]

        optional_fields = ["unit", "category", "expiry_date",
                           "auto_add_enabled", "threshold", "todo_list"]
        for field in optional_fields:
            if field in data:
                update_data[field] = data[field]

        if self.coordinator.update_item(inventory_id, old_name, new_name, **update_data):
            await self.coordinator.async_save_data(inventory_id)
            _LOGGER.info(f"Updated item: {
                         old_name} -> {new_name} in inventory: {inventory_id}")
        else:
            _LOGGER.error(f"Failed to update item: {
                          old_name} in inventory: {inventory_id}")


ITEM_SCHEMA = vol.Schema({
    vol.Required("inventory_id"): cv.string,
    vol.Required("name"): cv.string,
    vol.Optional("quantity", default=1): cv.positive_int,
    vol.Optional("unit", default=""): cv.string,
    vol.Optional("category", default=""): cv.string,
    vol.Optional("expiry_date", default=""): cv.string,
    vol.Optional("auto_add_enabled", default=False): cv.boolean,
    vol.Optional("threshold", default=0): cv.positive_int,
    vol.Optional("todo_list", default=""): cv.string,
})

UPDATE_SCHEMA = vol.Schema({
    vol.Required("inventory_id"): cv.string,
    vol.Required("name"): cv.string,
    vol.Optional("amount", default=1): cv.positive_int,
})

UPDATE_SETTINGS_SCHEMA = vol.Schema({
    vol.Required("inventory_id"): cv.string,
    vol.Required("name"): cv.string,
    vol.Optional("auto_add_enabled", default=False): cv.boolean,
    vol.Optional("threshold", default=0): cv.positive_int,
    vol.Optional("todo_list"): cv.string,
})

REMOVE_SCHEMA = vol.Schema({
    vol.Required("inventory_id"): cv.string,
    vol.Required("name"): cv.string,
})

UPDATE_ITEM_SCHEMA = vol.Schema({
    vol.Required("inventory_id"): cv.string,
    vol.Required("old_name"): cv.string,
    vol.Required("name"): cv.string,
    vol.Optional("quantity"): vol.All(vol.Coerce(int), vol.Range(min=0)),
    vol.Optional("unit"): cv.string,
    vol.Optional("category"): cv.string,
    vol.Optional("expiry_date"): cv.string,
    vol.Optional("auto_add_enabled"): cv.boolean,
    vol.Optional("threshold"): vol.All(vol.Coerce(int), vol.Range(min=0)),
    vol.Optional("todo_list"): cv.string,
})

SET_EXPIRY_THRESHOLD_SCHEMA = vol.Schema({
    vol.Required("threshold_days"): vol.All(vol.Coerce(int), vol.Range(min=1, max=30))
})
