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
CONF_SENSOR_HUMIDITY_ENTITY_ID = "humidity_entity_id"
CONF_DEFAULT_SENSOR = "default_sensor"
DEFAULT_SENSOR_LAST_ACTIVE = "__thermostat_proxy_last_active__"
CONF_USE_LAST_ACTIVE_SENSOR = "use_last_active_sensor"
CONF_UNIQUE_ID = "unique_id"
CONF_PHYSICAL_SENSOR_NAME = "physical_sensor_name"
CONF_COOLDOWN_PERIOD = "cooldown_period"
CONF_MIN_TEMP = "min_temp"
CONF_MAX_TEMP = "max_temp"
CONF_MAX_SYNC_OFFSET = "max_sync_offset"
CONF_DISABLE_AUTO_SWITCH = "disable_auto_switch"
CONF_PRESERVE_VIRTUAL_TARGET = "preserve_virtual_target"
CONF_PHYSICAL_TARGET_CHANGE_BEHAVIOR = "physical_target_change_behavior"
CONF_SENSOR_CHANGE_THRESHOLD = "sensor_change_threshold"
CONF_MAX_HUMIDITY_OVERCOOL = "max_humidity_overcool"
CONF_DEFAULT_TARGET_HUMIDITY = "default_target_humidity"

TARGET_CHANGE_BEHAVIOR_AUTO_SWITCH = "auto_switch"
TARGET_CHANGE_BEHAVIOR_DISABLE_AUTO_SWITCH = "disable_auto_switch"
TARGET_CHANGE_BEHAVIOR_PRESERVE_VIRTUAL_TARGET = "preserve_virtual_target"

DEFAULT_COOLDOWN_PERIOD = 0
DEFAULT_MAX_SYNC_OFFSET = 10.0
DEFAULT_DISABLE_AUTO_SWITCH = False
DEFAULT_PRESERVE_VIRTUAL_TARGET = False
DEFAULT_SENSOR_CHANGE_THRESHOLD = 0.0
DEFAULT_MAX_HUMIDITY_OVERCOOL = 2.0
DEFAULT_TARGET_HUMIDITY = 50
DEFAULT_HUMIDITY_DEADBAND = 2.0

ATTR_ACTIVE_SENSOR = "active_sensor"
ATTR_ACTIVE_SENSOR_ENTITY_ID = "active_sensor_entity_id"
ATTR_ACTIVE_HUMIDITY_SENSOR = "active_humidity_sensor"
ATTR_ACTIVE_HUMIDITY_SENSOR_ENTITY_ID = "active_humidity_sensor_entity_id"
ATTR_REAL_CURRENT_TEMPERATURE = "real_current_temperature"
ATTR_REAL_TARGET_TEMPERATURE = "real_target_temperature"
ATTR_REAL_CURRENT_HUMIDITY = "real_current_humidity"
ATTR_SELECTED_SENSOR_OPTIONS = "sensor_options"
ATTR_UNAVAILABLE_ENTITIES = "unavailable_entities"
ATTR_HUMIDITY_OVERDRIVE_ACTIVE = "humidity_overdrive_active"

OVERDRIVE_ADJUSTMENT_HEAT = 1.0
OVERDRIVE_ADJUSTMENT_COOL = -1.0

SYNC_LOG_SUPPRESSION_PADDING_SEC = 5

UNINITIALIZED_TEMP_FAHRENHEIT = 32.0
UNINITIALIZED_TEMP_CELSIUS = 0.0
