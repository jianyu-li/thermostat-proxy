"""Constants for the Thermostat Proxy integration."""

from __future__ import annotations

DOMAIN = "thermostat_proxy"

DEFAULT_NAME = "Thermostat Proxy"
PHYSICAL_SENSOR_NAME = "Physical Entity"
PHYSICAL_SENSOR_SENTINEL = "__thermostat_proxy_physical__"

CONF_THERMOSTAT = "thermostat"
CONF_SENSORS = "sensors"
CONF_SENSOR_NAME = "name"
CONF_SENSOR_ENTITY_ID = "entity_id"
CONF_DEFAULT_SENSOR = "default_sensor"
DEFAULT_SENSOR_LAST_ACTIVE = "__thermostat_proxy_last_active__"
CONF_USE_LAST_ACTIVE_SENSOR = "use_last_active_sensor"
CONF_UNIQUE_ID = "unique_id"
CONF_PHYSICAL_SENSOR_NAME = "physical_sensor_name"
CONF_COOLDOWN_PERIOD = "cooldown_period"
CONF_MIN_TEMP = "min_temp"
CONF_MAX_TEMP = "max_temp"

DEFAULT_COOLDOWN_PERIOD = 0

ATTR_ACTIVE_SENSOR = "active_sensor"
ATTR_ACTIVE_SENSOR_ENTITY_ID = "active_sensor_entity_id"
ATTR_REAL_CURRENT_TEMPERATURE = "real_current_temperature"
ATTR_REAL_TARGET_TEMPERATURE = "real_target_temperature"
ATTR_REAL_CURRENT_HUMIDITY = "real_current_humidity"
ATTR_SELECTED_SENSOR_OPTIONS = "sensor_options"
ATTR_UNAVAILABLE_ENTITIES = "unavailable_entities"

OVERDRIVE_ADJUSTMENT_HEAT = 1.0
OVERDRIVE_ADJUSTMENT_COOL = -1.0

