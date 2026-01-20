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
    CONF_DEFAULT_SENSOR,
    CONF_PHYSICAL_SENSOR_NAME,
    CONF_SENSOR_ENTITY_ID,
    CONF_SENSOR_NAME,
    CONF_SENSORS,
    DEFAULT_SENSOR_LAST_ACTIVE,
    CONF_THERMOSTAT,
    CONF_UNIQUE_ID,
    CONF_USE_LAST_ACTIVE_SENSOR,
    DEFAULT_NAME,
    DOMAIN,
    PHYSICAL_SENSOR_NAME,
    CONF_COOLDOWN_PERIOD,
    DEFAULT_COOLDOWN_PERIOD,
    CONF_MIN_TEMP,
    CONF_MAX_TEMP,
)

SENSOR_STEP = "sensors"
FINALIZE_STEP = "finalize"
CONF_ADD_ANOTHER = "add_another"
CONF_ACTION = "action"

ACTION_ADD_SENSOR = "add_sensor"
ACTION_REMOVE_SENSOR = "remove_sensor"
ACTION_FINISH = "finish"
ACTION_LABELS = {
    ACTION_ADD_SENSOR: "Add a sensor",
    ACTION_REMOVE_SENSOR: "Remove a sensor",
    ACTION_FINISH: "Continue",
}


class CustomThermostatConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Thermostat Proxy."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._sensors: list[dict[str, str]] = []
        self._default_sensor: str | None = None
        self._physical_sensor_name: str = PHYSICAL_SENSOR_NAME
        self._use_last_active_sensor: bool = False
        self._cooldown_period: int = DEFAULT_COOLDOWN_PERIOD
        self._min_temp: float | None = None
        self._max_temp: float | None = None
        self._reconfigure_entry: config_entries.ConfigEntry | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            thermostat = user_input[CONF_THERMOSTAT]
            unique_id = self._generate_unique_id(name, thermostat)

            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

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
            {CONF_SENSOR_NAME: sensor[CONF_SENSOR_NAME], CONF_SENSOR_ENTITY_ID: sensor[CONF_SENSOR_ENTITY_ID]}
            for sensor in entry.data.get(CONF_SENSORS, [])
        ]
        self._default_sensor = entry.data.get(CONF_DEFAULT_SENSOR)
        self._physical_sensor_name = entry.data.get(
            CONF_PHYSICAL_SENSOR_NAME, PHYSICAL_SENSOR_NAME
        )
        self._cooldown_period = entry.data.get(
            CONF_COOLDOWN_PERIOD, DEFAULT_COOLDOWN_PERIOD
        )
        self._min_temp = entry.data.get(CONF_MIN_TEMP)
        self._max_temp = entry.data.get(CONF_MAX_TEMP)
        self._use_last_active_sensor = entry.data.get(
            CONF_USE_LAST_ACTIVE_SENSOR, False
        )
        if self._default_sensor == DEFAULT_SENSOR_LAST_ACTIVE:
            self._use_last_active_sensor = True
            self._default_sensor = None

        errors: dict[str, str] = {}
        if user_input is not None:
            self._data[CONF_NAME] = user_input[CONF_NAME].strip()
            self._data[CONF_THERMOSTAT] = user_input[CONF_THERMOSTAT]
            return await self.async_step_manage_sensors()

        data_schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=self._data[CONF_NAME]): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                ),
                vol.Required(CONF_THERMOSTAT, default=self._data[CONF_THERMOSTAT]): selector.EntitySelector(
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
            action_options[ACTION_REMOVE_SENSOR] = ACTION_LABELS[ACTION_REMOVE_SENSOR]
            action_options[ACTION_FINISH] = ACTION_LABELS[ACTION_FINISH]

        default_action = (
            ACTION_FINISH if self._sensors else ACTION_ADD_SENSOR
        )

        sensor_list = ", ".join(
            sensor[CONF_SENSOR_NAME] for sensor in self._sensors
        ) or "None"

        data_schema = vol.Schema(
            {
                vol.Required(CONF_ACTION, default=default_action): vol.In(
                    action_options
                )
            }
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

            reserved_names = {
                PHYSICAL_SENSOR_NAME.lower(),
                self._physical_sensor_name.lower(),
            }
            if sensor_name.lower() in reserved_names:
                errors["base"] = "reserved_sensor_name"
            elif any(sensor_name == sensor[CONF_SENSOR_NAME] for sensor in self._sensors):
                errors["base"] = "duplicate_sensor_name"
            elif any(entity_id == sensor[CONF_SENSOR_ENTITY_ID] for sensor in self._sensors):
                errors["base"] = "duplicate_sensor_entity"
            else:
                self._sensors.append(
                    {
                        CONF_SENSOR_NAME: sensor_name,
                        CONF_SENSOR_ENTITY_ID: entity_id,
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
                vol.Required(CONF_SENSOR_ENTITY_ID): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["sensor", "climate", "number"],
                        device_class="temperature",
                    )
                ),
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

    async def async_step_finalize(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if not self._sensors:
            errors["base"] = "no_sensors"

        sensor_names = [sensor[CONF_SENSOR_NAME] for sensor in self._sensors]
        current_physical_name = self._physical_sensor_name
        available_default_options = list(sensor_names)
        if current_physical_name not in available_default_options:
            available_default_options.append(current_physical_name)

        default_sensor = (
            DEFAULT_SENSOR_LAST_ACTIVE
            if self._use_last_active_sensor
            else self._default_sensor
        )
        if user_input is not None:
            default_sensor = user_input.get(CONF_DEFAULT_SENSOR)
            submitted_physical_name = user_input.get(
                CONF_PHYSICAL_SENSOR_NAME, current_physical_name
            )
            physical_sensor_name = (
                submitted_physical_name.strip() if submitted_physical_name else ""
            ) or PHYSICAL_SENSOR_NAME

            cooldown_period = user_input.get(CONF_COOLDOWN_PERIOD, DEFAULT_COOLDOWN_PERIOD)
            min_temp = user_input.get(CONF_MIN_TEMP) or None
            max_temp = user_input.get(CONF_MAX_TEMP) or None

            if any(
                physical_sensor_name.lower() == sensor_name.lower()
                for sensor_name in sensor_names
            ):
                errors["base"] = "physical_name_conflict"
            elif default_sensor and default_sensor not in (*available_default_options, DEFAULT_SENSOR_LAST_ACTIVE):
                errors["base"] = "invalid_default_sensor"
            elif min_temp is not None and max_temp is not None and min_temp >= max_temp:
                errors["base"] = "invalid_temp_range"
            else:
                if (
                    default_sensor
                    and default_sensor == current_physical_name
                    and physical_sensor_name != current_physical_name
                ):
                    default_sensor = physical_sensor_name

                use_last_active_sensor = default_sensor == DEFAULT_SENSOR_LAST_ACTIVE
                self._default_sensor = (
                    None if use_last_active_sensor else default_sensor
                )
                self._physical_sensor_name = physical_sensor_name
                self._cooldown_period = cooldown_period
                self._min_temp = min_temp
                self._max_temp = max_temp
                self._use_last_active_sensor = use_last_active_sensor

                sensor_names_with_physical = list(sensor_names)
                if physical_sensor_name not in sensor_names_with_physical:
                    sensor_names_with_physical.append(physical_sensor_name)

                data = {
                    **self._data,
                    CONF_SENSORS: self._sensors,
                    CONF_PHYSICAL_SENSOR_NAME: self._physical_sensor_name,
                    CONF_COOLDOWN_PERIOD: self._cooldown_period,
                    CONF_USE_LAST_ACTIVE_SENSOR: self._use_last_active_sensor,
                    CONF_MIN_TEMP: min_temp,
                    CONF_MAX_TEMP: max_temp,
                }
                if self._use_last_active_sensor:
                    data[CONF_DEFAULT_SENSOR] = DEFAULT_SENSOR_LAST_ACTIVE
                elif default_sensor:
                    data[CONF_DEFAULT_SENSOR] = default_sensor
                if self._reconfigure_entry:
                    options = dict(self._reconfigure_entry.options)
                    current_option_default = options.get(CONF_DEFAULT_SENSOR)
                    if (
                        current_option_default
                        and current_option_default
                        not in (*sensor_names_with_physical, DEFAULT_SENSOR_LAST_ACTIVE)
                    ):
                        options.pop(CONF_DEFAULT_SENSOR)
                    self.hass.config_entries.async_update_entry(
                        self._reconfigure_entry,
                        data=data,
                        options=options,
                    )
                    await self.hass.config_entries.async_reload(
                        self._reconfigure_entry.entry_id
                    )
                    return self.async_abort(reason="reconfigure_successful")
                return self.async_create_entry(title=self._data[CONF_NAME], data=data)

        schema_fields: dict[Any, Any] = {
            vol.Optional(
                CONF_PHYSICAL_SENSOR_NAME, default=self._physical_sensor_name
            ): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
            ),
            vol.Optional(
                CONF_COOLDOWN_PERIOD, default=self._cooldown_period
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=300, unit_of_measurement="seconds", mode=selector.NumberSelectorMode.BOX
                )
            ),
        }

        number_selector = selector.NumberSelector(
            selector.NumberSelectorConfig(max=100, step=0.5, mode=selector.NumberSelectorMode.BOX)
        )
        
        # Show current values as defaults during reconfigure (0 = disabled)
        min_temp_default = self._min_temp if self._min_temp is not None else 0
        max_temp_default = self._max_temp if self._max_temp is not None else 0
        
        schema_fields[vol.Optional(CONF_MIN_TEMP, default=min_temp_default)] = number_selector
        schema_fields[vol.Optional(CONF_MAX_TEMP, default=max_temp_default)] = number_selector

        if sensor_names:
            default_options = [
                selector.SelectOptionDict(value=option, label=option)
                for option in available_default_options
            ]
            default_options.append(
                selector.SelectOptionDict(
                    value=DEFAULT_SENSOR_LAST_ACTIVE,
                    label="Last active sensor",
                )
            )

            selector_config = selector.SelectSelectorConfig(options=default_options)
            if default_sensor:
                schema_fields[
                    vol.Optional(CONF_DEFAULT_SENSOR, default=default_sensor)
                ] = selector.SelectSelector(selector_config)
            else:
                schema_fields[
                    vol.Optional(CONF_DEFAULT_SENSOR)
                ] = selector.SelectSelector(selector_config)

        data_schema = vol.Schema(schema_fields)

        return self.async_show_form(
            step_id=FINALIZE_STEP,
            data_schema=data_schema,
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
        self.config_entry = entry

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

        current_default = self.config_entry.options.get(
            CONF_DEFAULT_SENSOR,
            self.config_entry.data.get(CONF_DEFAULT_SENSOR),
        )
        use_last_active_sensor = self.config_entry.options.get(
            CONF_USE_LAST_ACTIVE_SENSOR,
            self.config_entry.data.get(CONF_USE_LAST_ACTIVE_SENSOR, False),
        )
        current_cooldown = self.config_entry.options.get(
            CONF_COOLDOWN_PERIOD,
            self.config_entry.data.get(CONF_COOLDOWN_PERIOD, DEFAULT_COOLDOWN_PERIOD),
        )
        current_min_temp = self.config_entry.options.get(
            CONF_MIN_TEMP,
            self.config_entry.data.get(CONF_MIN_TEMP),
        )
        current_max_temp = self.config_entry.options.get(
            CONF_MAX_TEMP,
            self.config_entry.data.get(CONF_MAX_TEMP),
        )

        if current_default == DEFAULT_SENSOR_LAST_ACTIVE:
            use_last_active_sensor = True
            current_default = None

        errors: dict[str, str] = {}
        if user_input is not None:
            default_sensor = user_input.get(CONF_DEFAULT_SENSOR)
            min_temp = user_input.get(CONF_MIN_TEMP) or None
            max_temp = user_input.get(CONF_MAX_TEMP) or None
            
            if default_sensor and default_sensor not in (*sensor_names, DEFAULT_SENSOR_LAST_ACTIVE):
                errors["base"] = "invalid_default_sensor"
            elif min_temp is not None and max_temp is not None and min_temp >= max_temp:
                errors["base"] = "invalid_temp_range"
            else:
                data: dict[str, Any] = {}
                if default_sensor == DEFAULT_SENSOR_LAST_ACTIVE:
                    data[CONF_DEFAULT_SENSOR] = DEFAULT_SENSOR_LAST_ACTIVE
                    data[CONF_USE_LAST_ACTIVE_SENSOR] = True
                else:
                    if default_sensor:
                        data[CONF_DEFAULT_SENSOR] = default_sensor
                    data[CONF_USE_LAST_ACTIVE_SENSOR] = False
                
                data[CONF_COOLDOWN_PERIOD] = user_input.get(CONF_COOLDOWN_PERIOD, DEFAULT_COOLDOWN_PERIOD)
                data[CONF_MIN_TEMP] = min_temp
                data[CONF_MAX_TEMP] = max_temp
                
                return self.async_create_entry(title="", data=data)

        schema_fields: dict[Any, Any] = {}

        if sensor_names != [None]:
            default_options = [
                selector.SelectOptionDict(value=name, label=name)
                for name in sensor_names
            ]
            default_options.append(
                selector.SelectOptionDict(
                    value=DEFAULT_SENSOR_LAST_ACTIVE,
                    label="Last active sensor",
                )
            )
            selector_config = selector.SelectSelectorConfig(options=default_options)
            default_choice = (
                DEFAULT_SENSOR_LAST_ACTIVE
                if use_last_active_sensor
                else current_default
            )
            schema_fields[vol.Optional(
                CONF_DEFAULT_SENSOR,
                default=default_choice or sensor_names[0],
            )] = selector.SelectSelector(selector_config)

        schema_fields[
            vol.Optional(CONF_COOLDOWN_PERIOD, default=current_cooldown)
        ] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0, max=300, unit_of_measurement="seconds", mode=selector.NumberSelectorMode.BOX
            )
        )

        number_selector = selector.NumberSelector(
            selector.NumberSelectorConfig(max=100, step=0.5, mode=selector.NumberSelectorMode.BOX)
        )
        
        # Show current values as defaults in options (0 = disabled)
        min_temp_default = current_min_temp if current_min_temp is not None else 0
        max_temp_default = current_max_temp if current_max_temp is not None else 0
        
        schema_fields[vol.Optional(CONF_MIN_TEMP, default=min_temp_default)] = number_selector
        schema_fields[vol.Optional(CONF_MAX_TEMP, default=max_temp_default)] = number_selector

        data_schema = vol.Schema(schema_fields)

        return self.async_show_form(
            step_id="init",
            data_schema=data_schema,
            errors=errors,
        )


@callback
def async_get_options_flow(config_entry: config_entries.ConfigEntry):
    """Return the options flow handler."""

    return CustomThermostatOptionsFlowHandler(config_entry)
