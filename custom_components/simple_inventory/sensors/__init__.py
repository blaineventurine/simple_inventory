"""Sensor components for Simple Inventory."""
from .inventory_sensor import InventorySensor
from .expiry_sensor import ExpiryNotificationSensor

__all__ = ["InventorySensor", "ExpiryNotificationSensor"]
