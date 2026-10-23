"""Config flow for the Thermostat Proxy integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv, selector
from homeassistant.util import slugify

from .const import (
    CONF_COOLDOWN_PERIOD,
    CONF_DEFAULT_SENSOR,
    CONF_DEFAULT_TARGET_HUMIDITY,
    CONF_DISABLE_AUTO_SWITCH,
    CONF_MAX_HUMIDITY_OVERCOOL,
    CONF_MAX_SYNC_OFFSET,
    CONF_MAX_TEMP,
    CONF_MIN_DUAL_TEMP_SPREAD,
    CONF_MIN_TEMP,
    CONF_OVERDRIVE_OFFSET,
    CONF_PHYSICAL_SENSOR_NAME,
    CONF_PHYSICAL_TARGET_CHANGE_BEHAVIOR,
    CONF_PRESERVE_VIRTUAL_TARGET,
    CONF_SENSOR_CHANGE_THRESHOLD,
    CONF_SENSOR_ENTITY_ID,
    CONF_SENSOR_HUMIDITY_ENTITY_ID,
    CONF_SENSOR_NAME,
    CONF_SENSORS,
    CONF_THERMOSTAT,
    CONF_UNIQUE_ID,
    CONF_USE_LAST_ACTIVE_SENSOR,
    DEFAULT_COOLDOWN_PERIOD,
    DEFAULT_DISABLE_AUTO_SWITCH,
    DEFAULT_MAX_HUMIDITY_OVERCOOL,
    DEFAULT_MAX_SYNC_OFFSET,
    DEFAULT_NAME,
    DEFAULT_OVERDRIVE_OFFSET,
    DEFAULT_PRESERVE_VIRTUAL_TARGET,
    DEFAULT_SENSOR_CHANGE_THRESHOLD,
    DEFAULT_SENSOR_LAST_ACTIVE,
    DEFAULT_TARGET_HUMIDITY,
    DOMAIN,
    MAX_COOLDOWN_PERIOD_SECONDS,
    MAX_HUMIDITY_OVERCOOL,
    MAX_MIN_DUAL_TEMP_SPREAD,
    MAX_SAFETY_TEMP,
    MAX_SENSOR_CHANGE_THRESHOLD,
    MAX_TARGET_HUMIDITY,
    MIN_TARGET_HUMIDITY,
    PHYSICAL_SENSOR_NAME,
    TARGET_CHANGE_BEHAVIOR_AUTO_SWITCH,
    TARGET_CHANGE_BEHAVIOR_DISABLE_AUTO_SWITCH,
    TARGET_CHANGE_BEHAVIOR_PRESERVE_VIRTUAL_TARGET,
)
from .helpers import (
    extract_runtime_settings,
    target_change_behavior_from_flags,
    target_change_flags_from_behavior,
)

SENSOR_STEP = "sensors"
FINALIZE_STEP = "finalize"
CONF_ADD_ANOTHER = "add_another"
CONF_ACTION = "action"
CONF_TARGET_SENSOR = "target_sensor"

ACTION_ADD_SENSOR = "add_sensor"
ACTION_REPLACE_SENSOR = "replace_sensor"
ACTION_REMOVE_SENSOR = "remove_sensor"
ACTION_FINISH = "finish"
ACTION_LABELS = {
    ACTION_ADD_SENSOR: "Add a sensor",
    ACTION_REPLACE_SENSOR: "Replace a sensor",
    ACTION_REMOVE_SENSOR: "Remove a sensor",
    ACTION_FINISH: "Continue",
}

_target_change_behavior_from_flags = target_change_behavior_from_flags
_target_change_flags_from_behavior = target_change_flags_from_behavior


def _target_change_behavior_selector() -> selector.SelectSelector:
    """Build the physical target change behavior selector."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                TARGET_CHANGE_BEHAVIOR_AUTO_SWITCH,
                TARGET_CHANGE_BEHAVIOR_DISABLE_AUTO_SWITCH,
                TARGET_CHANGE_BEHAVIOR_PRESERVE_VIRTUAL_TARGET,
            ],
            mode=selector.SelectSelectorMode.LIST,
            translation_key=CONF_PHYSICAL_TARGET_CHANGE_BEHAVIOR,
        )
    )


def _coerce_overdrive_offset(user_input: dict[str, Any]) -> float:
    """Coerce the overdrive offset from user input, falling back to default."""
    val = user_input.get(CONF_OVERDRIVE_OFFSET)
    return float(val) if val is not None else DEFAULT_OVERDRIVE_OFFSET


def _get_overdrive_offset_selector() -> selector.NumberSelector:
    """Build the overdrive offset number selector."""
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0.0, max=5.0, step=0.5, mode=selector.NumberSelectorMode.BOX
        )
    )


def _temperature_entity_selector() -> selector.EntitySelector:
    """Build the temperature entity selector."""
    return selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain=["sensor", "climate", "number"],
            device_class="temperature",
        )
    )


def _humidity_entity_selector() -> selector.EntitySelector:
    """Build the humidity entity selector."""
    return selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain=["sensor"],
            device_class="humidity",
        )
    )


def _validate_sensor_submission(
    sensors: list[dict[str, Any]],
    physical_sensor_name: str,
    sensor_name: str,
    entity_id: str,
    humidity_entity_id: str | None,
    exclude_name: str | None = None,
) -> str | None:
    """Validate submitted sensor attributes for collisions."""
    reserved_names = {
        PHYSICAL_SENSOR_NAME.lower(),
        physical_sensor_name.lower(),
    }
    if sensor_name.lower() in reserved_names:
        return "reserved_sensor_name"

    other_sensors = (
        [s for s in sensors if s[CONF_SENSOR_NAME] != exclude_name]
        if exclude_name is not None
        else sensors
    )

    if any(sensor_name == sensor[CONF_SENSOR_NAME] for sensor in other_sensors):
        return "duplicate_sensor_name"

    if any(entity_id == sensor[CONF_SENSOR_ENTITY_ID] for sensor in other_sensors) or (
        humidity_entity_id
        and any(
            humidity_entity_id == sensor.get(CONF_SENSOR_HUMIDITY_ENTITY_ID)
            for sensor in other_sensors
        )
    ):
        return "duplicate_sensor_entity"

    return None


def _extract_entry_runtime_settings(
    entry: config_entries.ConfigEntry,
) -> dict[str, Any]:
    """Extract runtime settings from a config entry, merging options over data."""
    return extract_runtime_settings({**entry.data, **entry.options})


def _value_or_default(data: dict[str, Any], key: str, default: Any) -> Any:
    """Return user value if present and not None, else return default."""
    val = data.get(key)
    return val if val is not None else default


def _parse_and_validate_runtime_input(
    user_input: dict[str, Any],
    available_default_options: list[str | None],
    fallback_disable_auto_switch: bool,
    fallback_preserve_virtual_target: bool,
) -> tuple[dict[str, Any], str | None]:
    """Parse and validate submitted runtime settings."""
    default_sensor = user_input.get(CONF_DEFAULT_SENSOR)
    if default_sensor and default_sensor not in (
        *available_default_options,
        DEFAULT_SENSOR_LAST_ACTIVE,
    ):
        return {}, "invalid_default_sensor"

    min_temp = user_input.get(CONF_MIN_TEMP) or None
    max_temp = user_input.get(CONF_MAX_TEMP) or None
    if min_temp is not None and max_temp is not None and min_temp >= max_temp:
        return {}, "invalid_temp_range"

    data: dict[str, Any] = {}
    if default_sensor == DEFAULT_SENSOR_LAST_ACTIVE:
        data[CONF_DEFAULT_SENSOR] = DEFAULT_SENSOR_LAST_ACTIVE
        data[CONF_USE_LAST_ACTIVE_SENSOR] = True
    else:
        if default_sensor:
            data[CONF_DEFAULT_SENSOR] = default_sensor
        data[CONF_USE_LAST_ACTIVE_SENSOR] = False

    data[CONF_COOLDOWN_PERIOD] = user_input.get(
        CONF_COOLDOWN_PERIOD, DEFAULT_COOLDOWN_PERIOD
    )
    data[CONF_MIN_TEMP] = min_temp
    data[CONF_MAX_TEMP] = max_temp
    data[CONF_MAX_SYNC_OFFSET] = user_input.get(CONF_MAX_SYNC_OFFSET) or None

    disable_auto_switch, preserve_virtual_target = target_change_flags_from_behavior(
        user_input.get(
            CONF_PHYSICAL_TARGET_CHANGE_BEHAVIOR,
            target_change_behavior_from_flags(
                fallback_disable_auto_switch,
                fallback_preserve_virtual_target,
            ),
        )
    )
    data[CONF_DISABLE_AUTO_SWITCH] = disable_auto_switch
    data[CONF_PRESERVE_VIRTUAL_TARGET] = preserve_virtual_target
    data[CONF_SENSOR_CHANGE_THRESHOLD] = _value_or_default(
        user_input, CONF_SENSOR_CHANGE_THRESHOLD, DEFAULT_SENSOR_CHANGE_THRESHOLD
    )
    data[CONF_MAX_HUMIDITY_OVERCOOL] = _value_or_default(
        user_input, CONF_MAX_HUMIDITY_OVERCOOL, DEFAULT_MAX_HUMIDITY_OVERCOOL
    )
    data[CONF_DEFAULT_TARGET_HUMIDITY] = _value_or_default(
        user_input, CONF_DEFAULT_TARGET_HUMIDITY, DEFAULT_TARGET_HUMIDITY
    )
    data[CONF_MIN_DUAL_TEMP_SPREAD] = user_input.get(CONF_MIN_DUAL_TEMP_SPREAD) or None
    data[CONF_OVERDRIVE_OFFSET] = _coerce_overdrive_offset(user_input)

    return data, None


def _build_default_sensor_field(
    options: list[str] | None,
    default_value: str | None,
) -> tuple[Any, Any] | None:
    """Build selector field tuple for the default sensor setting."""
    if not options:
        return None

    default_options = [
        selector.SelectOptionDict(value=option, label=option) for option in options
    ]
    default_options.append(
        selector.SelectOptionDict(
            value=DEFAULT_SENSOR_LAST_ACTIVE,
            label="Last active sensor",
        )
    )
    selector_config = selector.SelectSelectorConfig(options=default_options)
    if default_value:
        return (
            vol.Optional(CONF_DEFAULT_SENSOR, default=default_value),
            selector.SelectSelector(selector_config),
        )
    return (
        vol.Optional(CONF_DEFAULT_SENSOR),
        selector.SelectSelector(selector_config),
    )


def _build_temperature_limit_fields(
    min_temp: float | None,
    max_temp: float | None,
    max_sync_offset: float | None,
) -> dict[Any, Any]:
    """Build voluptuous fields for temperature limits."""
    number_selector = selector.NumberSelector(
        selector.NumberSelectorConfig(
            max=MAX_SAFETY_TEMP, step=0.5, mode=selector.NumberSelectorMode.BOX
        )
    )
    return {
        vol.Optional(
            CONF_MIN_TEMP, default=min_temp if min_temp is not None else 0
        ): number_selector,
        vol.Optional(
            CONF_MAX_TEMP, default=max_temp if max_temp is not None else 0
        ): number_selector,
        vol.Optional(
            CONF_MAX_SYNC_OFFSET,
            default=(
                max_sync_offset
                if max_sync_offset is not None
                else DEFAULT_MAX_SYNC_OFFSET
            ),
        ): number_selector,
    }


def _build_advanced_tuning_fields(
    *,
    max_humidity_overcool: float | None,
    default_target_humidity: int | None,
    min_dual_temp_spread: float | None,
    overdrive_offset: float | None,
    target_change_behavior: str,
) -> dict[Any, Any]:
    """Build voluptuous fields for humidity, spread, overdrive, and behavior."""
    return {
        vol.Optional(
            CONF_MAX_HUMIDITY_OVERCOOL,
            default=(
                max_humidity_overcool
                if max_humidity_overcool is not None
                else DEFAULT_MAX_HUMIDITY_OVERCOOL
            ),
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0.0,
                max=MAX_HUMIDITY_OVERCOOL,
                step=0.5,
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
        vol.Optional(
            CONF_DEFAULT_TARGET_HUMIDITY,
            default=(
                default_target_humidity
                if default_target_humidity is not None
                else DEFAULT_TARGET_HUMIDITY
            ),
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=MIN_TARGET_HUMIDITY,
                max=MAX_TARGET_HUMIDITY,
                step=1,
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
        vol.Optional(
            CONF_MIN_DUAL_TEMP_SPREAD,
            default=min_dual_temp_spread if min_dual_temp_spread is not None else 0.0,
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0.0,
                max=MAX_MIN_DUAL_TEMP_SPREAD,
                step=0.5,
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
        vol.Optional(
            CONF_OVERDRIVE_OFFSET,
            default=(
                overdrive_offset
                if overdrive_offset is not None
                else DEFAULT_OVERDRIVE_OFFSET
            ),
        ): _get_overdrive_offset_selector(),
        vol.Optional(
            CONF_PHYSICAL_TARGET_CHANGE_BEHAVIOR,
            default=target_change_behavior,
        ): _target_change_behavior_selector(),
    }


def _build_cooldown_field(cooldown_period: Any) -> tuple[Any, Any]:
    """Build selector field tuple for the cooldown period."""
    return (
        vol.Optional(CONF_COOLDOWN_PERIOD, default=cooldown_period),
        selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0,
                max=MAX_COOLDOWN_PERIOD_SECONDS,
                unit_of_measurement="seconds",
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
    )


def _build_threshold_field(threshold: Any) -> tuple[Any, Any]:
    """Build selector field tuple for sensor change threshold."""
    return (
        vol.Optional(CONF_SENSOR_CHANGE_THRESHOLD, default=threshold),
        selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0.0,
                max=MAX_SENSOR_CHANGE_THRESHOLD,
                step=0.1,
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
    )


def _build_runtime_settings_schema(
    *,
    settings: dict[str, Any],
    default_sensor_options: list[str] | None = None,
    default_sensor_value: str | None = None,
    default_sensor_first: bool = False,
    physical_sensor_name: str | None = None,
) -> dict[Any, Any]:
    """Build voluptuous schema fields for runtime settings."""
    schema_fields: dict[Any, Any] = {}

    if physical_sensor_name is not None:
        schema_fields[
            vol.Optional(CONF_PHYSICAL_SENSOR_NAME, default=physical_sensor_name)
        ] = selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
        )

    default_sensor_field = _build_default_sensor_field(
        default_sensor_options, default_sensor_value
    )

    if default_sensor_first and default_sensor_field is not None:
        schema_fields[default_sensor_field[0]] = default_sensor_field[1]

    cooldown_key, cooldown_val = _build_cooldown_field(
        settings.get(CONF_COOLDOWN_PERIOD, DEFAULT_COOLDOWN_PERIOD)
    )
    schema_fields[cooldown_key] = cooldown_val

    schema_fields.update(
        _build_temperature_limit_fields(
            settings.get(CONF_MIN_TEMP),
            settings.get(CONF_MAX_TEMP),
            settings.get(CONF_MAX_SYNC_OFFSET),
        )
    )

    threshold_key, threshold_val = _build_threshold_field(
        settings.get(CONF_SENSOR_CHANGE_THRESHOLD, DEFAULT_SENSOR_CHANGE_THRESHOLD)
    )
    schema_fields[threshold_key] = threshold_val

    if not default_sensor_first and default_sensor_field is not None:
        schema_fields[default_sensor_field[0]] = default_sensor_field[1]

    target_change_behavior = target_change_behavior_from_flags(
        settings.get(CONF_DISABLE_AUTO_SWITCH, DEFAULT_DISABLE_AUTO_SWITCH),
        settings.get(CONF_PRESERVE_VIRTUAL_TARGET, DEFAULT_PRESERVE_VIRTUAL_TARGET),
    )

    schema_fields.update(
        _build_advanced_tuning_fields(
            max_humidity_overcool=settings.get(CONF_MAX_HUMIDITY_OVERCOOL),
            default_target_humidity=settings.get(CONF_DEFAULT_TARGET_HUMIDITY),
            min_dual_temp_spread=settings.get(CONF_MIN_DUAL_TEMP_SPREAD),
            overdrive_offset=settings.get(CONF_OVERDRIVE_OFFSET),
            target_change_behavior=target_change_behavior,
        )
    )

    return schema_fields


class CustomThermostatConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Thermostat Proxy."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        """Get the options flow for this handler."""
        return CustomThermostatOptionsFlowHandler(config_entry)

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._sensors: list[dict[str, str]] = []
        self._default_sensor: str | None = None
        self._physical_sensor_name: str = PHYSICAL_SENSOR_NAME
        self._use_last_active_sensor: bool = False
        self._cooldown_period: int = DEFAULT_COOLDOWN_PERIOD
        self._min_temp: float | None = None
        self._max_temp: float | None = None
        self._max_sync_offset: float | None = None
        self._disable_auto_switch: bool = DEFAULT_DISABLE_AUTO_SWITCH
        self._preserve_virtual_target: bool = DEFAULT_PRESERVE_VIRTUAL_TARGET
        self._sensor_change_threshold: float = DEFAULT_SENSOR_CHANGE_THRESHOLD
        self._max_humidity_overcool: float = DEFAULT_MAX_HUMIDITY_OVERCOOL
        self._default_target_humidity: int = DEFAULT_TARGET_HUMIDITY
        self._min_dual_temp_spread: float | None = None
        self._overdrive_offset: float = DEFAULT_OVERDRIVE_OFFSET
        self._reconfigure_entry: config_entries.ConfigEntry | None = None
        self._replace_target: str | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            thermostat = user_input[CONF_THERMOSTAT]
            unique_id = self._generate_unique_id(name, thermostat)

            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured(reload_on_update=False)

            self._data = {
                CONF_NAME: name,
                CONF_THERMOSTAT: thermostat,
                CONF_UNIQUE_ID: unique_id,
            }

            self._sensors = []
            self._default_sensor = None
            self._physical_sensor_name = PHYSICAL_SENSOR_NAME
            return await self.async_step_manage_sensors()

        data_schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=DEFAULT_NAME): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                ),
                vol.Required(CONF_THERMOSTAT): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["climate"])
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None):
        entry_id = self.context.get("entry_id")
        entry = self.hass.config_entries.async_get_entry(entry_id) if entry_id else None
        if entry is None:
            return self.async_abort(reason="unknown")

        self._reconfigure_entry = entry
        self._data = {
            CONF_NAME: entry.data.get(CONF_NAME, DEFAULT_NAME),
            CONF_THERMOSTAT: entry.data.get(CONF_THERMOSTAT),
            CONF_UNIQUE_ID: entry.unique_id,
        }
        self._sensors = [
            {
                CONF_SENSOR_NAME: sensor[CONF_SENSOR_NAME],
                CONF_SENSOR_ENTITY_ID: sensor[CONF_SENSOR_ENTITY_ID],
                CONF_SENSOR_HUMIDITY_ENTITY_ID: sensor.get(
                    CONF_SENSOR_HUMIDITY_ENTITY_ID
                ),
            }
            for sensor in entry.data.get(CONF_SENSORS, [])
        ]
        self._physical_sensor_name = entry.data.get(
            CONF_PHYSICAL_SENSOR_NAME, PHYSICAL_SENSOR_NAME
        )
        settings = _extract_entry_runtime_settings(entry)
        self._default_sensor = settings[CONF_DEFAULT_SENSOR]
        self._use_last_active_sensor = settings[CONF_USE_LAST_ACTIVE_SENSOR]
        self._cooldown_period = settings[CONF_COOLDOWN_PERIOD]
        self._min_temp = settings[CONF_MIN_TEMP]
        self._max_temp = settings[CONF_MAX_TEMP]
        self._max_sync_offset = settings[CONF_MAX_SYNC_OFFSET]
        self._disable_auto_switch = settings[CONF_DISABLE_AUTO_SWITCH]
        self._preserve_virtual_target = settings[CONF_PRESERVE_VIRTUAL_TARGET]
        self._sensor_change_threshold = settings[CONF_SENSOR_CHANGE_THRESHOLD]
        self._max_humidity_overcool = settings[CONF_MAX_HUMIDITY_OVERCOOL]
        self._default_target_humidity = settings[CONF_DEFAULT_TARGET_HUMIDITY]
        self._min_dual_temp_spread = settings[CONF_MIN_DUAL_TEMP_SPREAD]
        self._overdrive_offset = settings[CONF_OVERDRIVE_OFFSET]

        errors: dict[str, str] = {}
        if user_input is not None:
            self._data[CONF_NAME] = user_input[CONF_NAME].strip()
            self._data[CONF_THERMOSTAT] = user_input[CONF_THERMOSTAT]
            return await self.async_step_manage_sensors()

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_NAME, default=self._data[CONF_NAME]
                ): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                ),
                vol.Required(
                    CONF_THERMOSTAT, default=self._data[CONF_THERMOSTAT]
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["climate"])
                ),
            }
        )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_manage_sensors(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            action = user_input[CONF_ACTION]
            if action == ACTION_ADD_SENSOR:
                return await self.async_step_sensors()
            if action == ACTION_REPLACE_SENSOR:
                if not self._sensors:
                    errors["base"] = "no_sensors"
                else:
                    return await self.async_step_replace_sensor()
            if action == ACTION_REMOVE_SENSOR:
                if not self._sensors:
                    errors["base"] = "no_sensors"
                else:
                    return await self.async_step_remove_sensor()
            if action == ACTION_FINISH:
                if not self._sensors:
                    errors["base"] = "no_sensors"
                else:
                    return await self.async_step_finalize()

        action_options = {ACTION_ADD_SENSOR: ACTION_LABELS[ACTION_ADD_SENSOR]}
        if self._sensors:
            action_options[ACTION_REPLACE_SENSOR] = ACTION_LABELS[ACTION_REPLACE_SENSOR]
            action_options[ACTION_REMOVE_SENSOR] = ACTION_LABELS[ACTION_REMOVE_SENSOR]
            action_options[ACTION_FINISH] = ACTION_LABELS[ACTION_FINISH]

        default_action = ACTION_FINISH if self._sensors else ACTION_ADD_SENSOR

        sensor_list = (
            ", ".join(sensor[CONF_SENSOR_NAME] for sensor in self._sensors) or "None"
        )

        data_schema = vol.Schema(
            {vol.Required(CONF_ACTION, default=default_action): vol.In(action_options)}
        )

        return self.async_show_form(
            step_id="manage_sensors",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={"sensor_list": sensor_list},
        )

    async def async_step_sensors(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            sensor_name = user_input[CONF_SENSOR_NAME].strip()
            entity_id = user_input[CONF_SENSOR_ENTITY_ID]
            humidity_entity_id = user_input.get(CONF_SENSOR_HUMIDITY_ENTITY_ID)

            error = _validate_sensor_submission(
                sensors=self._sensors,
                physical_sensor_name=self._physical_sensor_name,
                sensor_name=sensor_name,
                entity_id=entity_id,
                humidity_entity_id=humidity_entity_id,
            )
            if error:
                errors["base"] = error
            else:
                self._sensors.append(
                    {
                        CONF_SENSOR_NAME: sensor_name,
                        CONF_SENSOR_ENTITY_ID: entity_id,
                        CONF_SENSOR_HUMIDITY_ENTITY_ID: humidity_entity_id,
                    }
                )
                if user_input.get(CONF_ADD_ANOTHER, False):
                    return await self.async_step_sensors()
                return await self.async_step_manage_sensors()

        data_schema = vol.Schema(
            {
                vol.Required(CONF_SENSOR_NAME): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                ),
                vol.Required(CONF_SENSOR_ENTITY_ID): _temperature_entity_selector(),
                vol.Optional(
                    CONF_SENSOR_HUMIDITY_ENTITY_ID
                ): _humidity_entity_selector(),
                vol.Optional(CONF_ADD_ANOTHER, default=True): cv.boolean,
            }
        )

        return self.async_show_form(
            step_id=SENSOR_STEP,
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_remove_sensor(self, user_input: dict[str, Any] | None = None):
        if not self._sensors:
            return await self.async_step_manage_sensors()

        options = [sensor[CONF_SENSOR_NAME] for sensor in self._sensors]
        errors: dict[str, str] = {}
        if user_input is not None:
            target = user_input.get(CONF_SENSOR_NAME)
            if target not in options:
                errors["base"] = "invalid_default_sensor"
            else:
                self._sensors = [
                    sensor
                    for sensor in self._sensors
                    if sensor[CONF_SENSOR_NAME] != target
                ]
                if self._default_sensor == target:
                    self._default_sensor = None
                return await self.async_step_manage_sensors()

        data_schema = vol.Schema(
            {
                vol.Required(CONF_SENSOR_NAME): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=options)
                )
            }
        )

        return self.async_show_form(
            step_id="remove_sensor",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_replace_sensor(self, user_input: dict[str, Any] | None = None):
        if not self._sensors:
            return await self.async_step_manage_sensors()

        options = [sensor[CONF_SENSOR_NAME] for sensor in self._sensors]
        errors: dict[str, str] = {}
        if user_input is not None:
            target = user_input.get(CONF_TARGET_SENSOR)
            if target not in options:
                errors["base"] = "invalid_default_sensor"
            else:
                self._replace_target = target
                return await self.async_step_replace_sensor_details()

        data_schema = vol.Schema(
            {
                vol.Required(CONF_TARGET_SENSOR): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=options)
                ),
            }
        )

        return self.async_show_form(
            step_id="replace_sensor",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_replace_sensor_details(
        self, user_input: dict[str, Any] | None = None
    ):
        target = self._replace_target
        if target is None:
            return await self.async_step_replace_sensor()

        target_sensor = next(
            (s for s in self._sensors if s[CONF_SENSOR_NAME] == target), None
        )
        if target_sensor is None:
            return await self.async_step_manage_sensors()

        errors: dict[str, str] = {}
        if user_input is not None:
            sensor_name = user_input[CONF_SENSOR_NAME].strip()
            entity_id = user_input[CONF_SENSOR_ENTITY_ID]
            humidity_entity_id = user_input.get(CONF_SENSOR_HUMIDITY_ENTITY_ID)

            error = _validate_sensor_submission(
                sensors=self._sensors,
                physical_sensor_name=self._physical_sensor_name,
                sensor_name=sensor_name,
                entity_id=entity_id,
                humidity_entity_id=humidity_entity_id,
                exclude_name=target,
            )
            if error:
                errors["base"] = error
            else:
                target_sensor[CONF_SENSOR_NAME] = sensor_name
                target_sensor[CONF_SENSOR_ENTITY_ID] = entity_id
                target_sensor[CONF_SENSOR_HUMIDITY_ENTITY_ID] = humidity_entity_id
                if self._default_sensor == target:
                    self._default_sensor = sensor_name
                self._replace_target = None
                return await self.async_step_manage_sensors()

        schema_dict: dict[Any, Any] = {
            vol.Required(
                CONF_SENSOR_NAME, default=target_sensor[CONF_SENSOR_NAME]
            ): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
            ),
            vol.Required(
                CONF_SENSOR_ENTITY_ID,
                default=target_sensor[CONF_SENSOR_ENTITY_ID],
            ): _temperature_entity_selector(),
        }
        current_humidity = target_sensor.get(CONF_SENSOR_HUMIDITY_ENTITY_ID)
        if current_humidity:
            schema_dict[
                vol.Optional(
                    CONF_SENSOR_HUMIDITY_ENTITY_ID,
                    default=current_humidity,
                )
            ] = _humidity_entity_selector()
        else:
            schema_dict[vol.Optional(CONF_SENSOR_HUMIDITY_ENTITY_ID)] = (
                _humidity_entity_selector()
            )

        data_schema = vol.Schema(schema_dict)

        return self.async_show_form(
            step_id="replace_sensor_details",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_finalize(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if not self._sensors:
            errors["base"] = "no_sensors"

        sensor_names = [sensor[CONF_SENSOR_NAME] for sensor in self._sensors]
        current_physical_name = self._physical_sensor_name
        available_default_options = list(sensor_names)
        if current_physical_name not in available_default_options:
            available_default_options.append(current_physical_name)

        if user_input is not None:
            submitted_physical_name = user_input.get(
                CONF_PHYSICAL_SENSOR_NAME, current_physical_name
            )
            physical_sensor_name = (
                submitted_physical_name.strip() if submitted_physical_name else ""
            ) or PHYSICAL_SENSOR_NAME

            if any(
                physical_sensor_name.lower() == sensor_name.lower()
                for sensor_name in sensor_names
            ):
                errors["base"] = "physical_name_conflict"
            else:
                runtime_data, error = _parse_and_validate_runtime_input(
                    user_input,
                    available_default_options,
                    self._disable_auto_switch,
                    self._preserve_virtual_target,
                )
                if error:
                    errors["base"] = error
                else:
                    if (
                        runtime_data.get(CONF_DEFAULT_SENSOR) == current_physical_name
                        and physical_sensor_name != current_physical_name
                    ):
                        runtime_data[CONF_DEFAULT_SENSOR] = physical_sensor_name

                    self._default_sensor = (
                        None
                        if runtime_data[CONF_USE_LAST_ACTIVE_SENSOR]
                        else runtime_data.get(CONF_DEFAULT_SENSOR)
                    )
                    self._physical_sensor_name = physical_sensor_name
                    self._cooldown_period = runtime_data[CONF_COOLDOWN_PERIOD]
                    self._min_temp = runtime_data[CONF_MIN_TEMP]
                    self._max_temp = runtime_data[CONF_MAX_TEMP]
                    self._max_sync_offset = runtime_data[CONF_MAX_SYNC_OFFSET]
                    self._disable_auto_switch = runtime_data[CONF_DISABLE_AUTO_SWITCH]
                    self._preserve_virtual_target = runtime_data[
                        CONF_PRESERVE_VIRTUAL_TARGET
                    ]
                    self._sensor_change_threshold = runtime_data[
                        CONF_SENSOR_CHANGE_THRESHOLD
                    ]
                    self._max_humidity_overcool = runtime_data[
                        CONF_MAX_HUMIDITY_OVERCOOL
                    ]
                    self._default_target_humidity = runtime_data[
                        CONF_DEFAULT_TARGET_HUMIDITY
                    ]
                    self._min_dual_temp_spread = runtime_data[CONF_MIN_DUAL_TEMP_SPREAD]
                    self._overdrive_offset = runtime_data[CONF_OVERDRIVE_OFFSET]
                    self._use_last_active_sensor = runtime_data[
                        CONF_USE_LAST_ACTIVE_SENSOR
                    ]

                    data = {
                        **self._data,
                        CONF_SENSORS: self._sensors,
                        CONF_PHYSICAL_SENSOR_NAME: self._physical_sensor_name,
                        **runtime_data,
                    }

                    if self._reconfigure_entry:
                        options = dict(self._reconfigure_entry.options)
                        # Sync shared parameters to ensure reconfigured values
                        # are not overridden by stale options
                        for key in (
                            CONF_DEFAULT_SENSOR,
                            CONF_COOLDOWN_PERIOD,
                            CONF_MIN_TEMP,
                            CONF_MAX_TEMP,
                            CONF_MAX_SYNC_OFFSET,
                            CONF_DISABLE_AUTO_SWITCH,
                            CONF_PRESERVE_VIRTUAL_TARGET,
                            CONF_SENSOR_CHANGE_THRESHOLD,
                            CONF_USE_LAST_ACTIVE_SENSOR,
                            CONF_MAX_HUMIDITY_OVERCOOL,
                            CONF_DEFAULT_TARGET_HUMIDITY,
                            CONF_MIN_DUAL_TEMP_SPREAD,
                            CONF_OVERDRIVE_OFFSET,
                        ):
                            if key in options:
                                options[key] = data.get(key)

                        if data.get(CONF_NAME) != self._reconfigure_entry.title:
                            self.hass.config_entries.async_update_entry(
                                self._reconfigure_entry, title=data[CONF_NAME]
                            )
                        return self.async_update_reload_and_abort(
                            self._reconfigure_entry,
                            data=data,
                            options=options,
                            reason="reconfigure_successful",
                        )
                    return self.async_create_entry(
                        title=self._data[CONF_NAME], data=data
                    )

        current_settings = {
            CONF_COOLDOWN_PERIOD: self._cooldown_period,
            CONF_MIN_TEMP: self._min_temp,
            CONF_MAX_TEMP: self._max_temp,
            CONF_MAX_SYNC_OFFSET: self._max_sync_offset,
            CONF_DISABLE_AUTO_SWITCH: self._disable_auto_switch,
            CONF_PRESERVE_VIRTUAL_TARGET: self._preserve_virtual_target,
            CONF_SENSOR_CHANGE_THRESHOLD: self._sensor_change_threshold,
            CONF_MAX_HUMIDITY_OVERCOOL: self._max_humidity_overcool,
            CONF_DEFAULT_TARGET_HUMIDITY: self._default_target_humidity,
            CONF_MIN_DUAL_TEMP_SPREAD: self._min_dual_temp_spread,
            CONF_OVERDRIVE_OFFSET: self._overdrive_offset,
        }

        default_sensor = (
            user_input.get(CONF_DEFAULT_SENSOR)
            if user_input is not None
            else (
                DEFAULT_SENSOR_LAST_ACTIVE
                if self._use_last_active_sensor
                else self._default_sensor
            )
        )

        schema_fields = _build_runtime_settings_schema(
            settings=current_settings,
            default_sensor_options=available_default_options if sensor_names else None,
            default_sensor_value=default_sensor,
            default_sensor_first=False,
            physical_sensor_name=self._physical_sensor_name,
        )

        return self.async_show_form(
            step_id=FINALIZE_STEP,
            data_schema=vol.Schema(schema_fields),
            errors=errors,
        )

    def _generate_unique_id(self, name: str, thermostat: str) -> str:
        existing_ids = {
            entry.unique_id
            for entry in self._async_current_entries()
            if entry.unique_id
        }

        base = slugify(name)
        if not base:
            base = slugify(thermostat)
        if not base:
            base = "thermostat_proxy"

        candidate = base
        suffix = 2
        while candidate in existing_ids:
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate


class CustomThermostatOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Thermostat Proxy options."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        pass

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        sensors = self.config_entry.data.get(CONF_SENSORS, [])
        sensor_names = [sensor[CONF_SENSOR_NAME] for sensor in sensors]
        physical_sensor_name = self.config_entry.data.get(
            CONF_PHYSICAL_SENSOR_NAME, PHYSICAL_SENSOR_NAME
        )
        if physical_sensor_name not in sensor_names:
            sensor_names.append(physical_sensor_name)
        if not sensor_names:
            sensor_names = [None]

        settings = _extract_entry_runtime_settings(self.config_entry)

        errors: dict[str, str] = {}
        if user_input is not None:
            data, error = _parse_and_validate_runtime_input(
                user_input,
                sensor_names,
                settings[CONF_DISABLE_AUTO_SWITCH],
                settings[CONF_PRESERVE_VIRTUAL_TARGET],
            )
            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(title="", data=data)

        default_sensor_options = sensor_names if sensor_names != [None] else None
        default_choice = (
            DEFAULT_SENSOR_LAST_ACTIVE
            if settings[CONF_USE_LAST_ACTIVE_SENSOR]
            else settings[CONF_DEFAULT_SENSOR]
        )
        default_sensor_value = (
            (default_choice or sensor_names[0]) if default_sensor_options else None
        )

        schema_fields = _build_runtime_settings_schema(
            settings=settings,
            default_sensor_options=default_sensor_options,
            default_sensor_value=default_sensor_value,
            default_sensor_first=True,
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema_fields),
            errors=errors,
        )
