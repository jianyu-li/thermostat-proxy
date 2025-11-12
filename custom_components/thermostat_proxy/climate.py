"""Thermostat Proxy climate platform."""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import voluptuous as vol

from homeassistant.components.climate import PLATFORM_SCHEMA, ClimateEntity
from homeassistant.components.climate.const import (
    ATTR_CURRENT_TEMPERATURE,
    ATTR_HVAC_MODE,
    ATTR_MAX_TEMP,
    ATTR_MIN_TEMP,
    ATTR_TARGET_TEMP_STEP,
    DOMAIN as CLIMATE_DOMAIN,
    HVACMode,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_TEMPERATURE,
    ClimateEntityFeature,
)
from homeassistant.components.logbook import DOMAIN as LOGBOOK_DOMAIN

try:
    from homeassistant.components.logbook import SERVICE_LOG as LOGBOOK_SERVICE_LOG
except ImportError:  # Older HA versions don't expose SERVICE_LOG
    LOGBOOK_SERVICE_LOG = "log"
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    CONF_NAME,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, State, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import (
    ATTR_ACTIVE_SENSOR,
    ATTR_ACTIVE_SENSOR_ENTITY_ID,
    ATTR_REAL_CURRENT_TEMPERATURE,
    ATTR_REAL_TARGET_TEMPERATURE,
    ATTR_SELECTED_SENSOR_OPTIONS,
    ATTR_UNAVAILABLE_ENTITIES,
    DEFAULT_NAME,
    PHYSICAL_SENSOR_NAME,
    PHYSICAL_SENSOR_SENTINEL,
    CONF_DEFAULT_SENSOR,
    CONF_SENSOR_ENTITY_ID,
    CONF_SENSOR_NAME,
    CONF_SENSORS,
    CONF_THERMOSTAT,
    CONF_UNIQUE_ID,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_PRECISION = 0.1

# Attributes supplied by ClimateEntity itself that must NOT be overridden by
# forwarding the physical thermostat's attributes, otherwise the front-end sees
# the wrong preset/temperature metadata.
_RESERVED_REAL_ATTRIBUTES = {
    "temperature",
    "target_temp_high",
    "target_temp_low",
    "current_temperature",
    "hvac_modes",
    "hvac_mode",
    "preset_modes",
    "preset_mode",
    "target_temp_step",
    "supported_features",
    "fan_mode",
    "fan_modes",
}

SENSOR_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SENSOR_NAME): cv.string,
        vol.Required(CONF_SENSOR_ENTITY_ID): cv.entity_id,
    }
)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_THERMOSTAT): cv.entity_id,
        vol.Required(CONF_SENSORS): vol.All(cv.ensure_list, vol.Length(min=1), [SENSOR_SCHEMA]),
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_UNIQUE_ID): cv.string,
        vol.Optional(CONF_DEFAULT_SENSOR): cv.string,
    }
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up a Thermostat Proxy entity from YAML."""

    async_add_entities(
        [
            CustomThermostatEntity(
                hass=hass,
                name=config[CONF_NAME],
                real_thermostat=config[CONF_THERMOSTAT],
                sensors=config[CONF_SENSORS],
                default_sensor=config.get(CONF_DEFAULT_SENSOR),
                unique_id=config.get(CONF_UNIQUE_ID),
            )
        ]
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up a Thermostat Proxy entity from a config entry."""

    data = entry.data
    sensors = data.get(CONF_SENSORS) or []
    if not sensors:
        _LOGGER.error(
            "Config entry %s is missing sensors; skipping Thermostat Proxy creation",
            entry.entry_id,
        )
        return

    default_sensor = entry.options.get(CONF_DEFAULT_SENSOR) or data.get(CONF_DEFAULT_SENSOR)
    valid_sensor_names = [sensor[CONF_SENSOR_NAME] for sensor in sensors]
    if PHYSICAL_SENSOR_NAME not in valid_sensor_names:
        valid_sensor_names.append(PHYSICAL_SENSOR_NAME)

    if default_sensor and default_sensor not in valid_sensor_names:
        _LOGGER.warning(
            "Default sensor '%s' not in config entry %s; falling back to first sensor",
            default_sensor,
            entry.entry_id,
        )
        default_sensor = None

    async_add_entities(
        [
            CustomThermostatEntity(
                hass=hass,
                name=data.get(CONF_NAME, DEFAULT_NAME),
                real_thermostat=data[CONF_THERMOSTAT],
                sensors=sensors,
                default_sensor=default_sensor,
                unique_id=data.get(CONF_UNIQUE_ID) or entry.entry_id,
            )
        ]
    )


@dataclass
class SensorConfig:
    """Configuration for a temperature sensor."""

    name: str
    entity_id: str | None
    is_physical: bool = False


class CustomThermostatEntity(RestoreEntity, ClimateEntity):
    """Thermostat proxy that can borrow any temperature sensor."""

    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        name: str,
        real_thermostat: str,
        sensors: list[dict[str, Any]],
        default_sensor: str | None,
        unique_id: str | None,
    ) -> None:
        self.hass = hass
        self._attr_name = name
        self._attr_unique_id = unique_id
        self._real_entity_id = real_thermostat
        base_sensors: list[SensorConfig] = [
            SensorConfig(name=item[CONF_SENSOR_NAME], entity_id=item[CONF_SENSOR_ENTITY_ID])
            for item in sensors
        ]
        self._sensors = self._add_physical_sensor(base_sensors)
        self._sensor_lookup: dict[str, SensorConfig] = {
            sensor.name: sensor for sensor in self._sensors
        }
        self._configured_default_sensor = (
            default_sensor if default_sensor in self._sensor_lookup else None
        )
        if self._configured_default_sensor:
            self._selected_sensor_name = self._configured_default_sensor
        else:
            self._selected_sensor_name = self._sensors[0].name
        self._sensor_states: dict[str, State | None] = {}
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
        )
        self._virtual_target_temperature: float | None = None
        self._temperature_unit: str | None = None
        self._real_state: State | None = None
        self._last_requested_real_target: float | None = None
        self._last_real_target_temp: float | None = None
        self._unsub_listeners: list[Callable[[], None]] = []
        self._min_temp: float | None = None
        self._max_temp: float | None = None
        self._target_temp_step: float | None = None
        self._entity_health: dict[str, bool] = {}
        self._command_lock = asyncio.Lock()
        self._sensor_realign_task: asyncio.Task | None = None

    async def async_added_to_hass(self) -> None:
        """Finish setup when entity is added."""

        await super().async_added_to_hass()
        await self._async_restore_state()
        self._real_state = self.hass.states.get(self._real_entity_id)
        self._update_real_temperature_limits()
        for sensor in self._sensors:
            if sensor.is_physical:
                continue
            self._sensor_states[sensor.entity_id] = self.hass.states.get(sensor.entity_id)
            self._update_sensor_health_from_state(
                sensor.entity_id, self._sensor_states[sensor.entity_id]
            )
        self._temperature_unit = self._discover_temperature_unit()
        if self._virtual_target_temperature is None:
            self._virtual_target_temperature = self._apply_target_constraints(
                self._get_real_target_temperature()
                or self._get_active_sensor_temperature()
                or self._get_real_current_temperature()
            )
        await self._async_subscribe_to_states()

    async def _async_subscribe_to_states(self) -> None:
        """Listen for updates to real thermostat and sensors."""

        self._unsub_listeners.append(
            async_track_state_change_event(
                self.hass,
                [self._real_entity_id],
                self._async_handle_real_state_event,
            )
        )

        sensor_entity_ids = [
            sensor.entity_id
            for sensor in self._sensors
            if not sensor.is_physical and sensor.entity_id
        ]
        self._unsub_listeners.append(
            async_track_state_change_event(
                self.hass,
                sensor_entity_ids,
                self._async_handle_sensor_state_event,
            )
        )

    async def async_will_remove_from_hass(self) -> None:
        """Clean up listeners when entity is removed."""

        await super().async_will_remove_from_hass()
        if self._sensor_realign_task and not self._sensor_realign_task.done():
            self._sensor_realign_task.cancel()
        while self._unsub_listeners:
            unsubscribe = self._unsub_listeners.pop()
            unsubscribe()

    @callback
    def _async_handle_real_state_event(self, event) -> None:
        """Handle updates to the linked thermostat."""

        new_state: State | None = event.data.get("new_state")
        self._real_state = new_state
        self._update_real_temperature_limits()
        if not new_state:
            self.async_write_ha_state()
            return

        self._temperature_unit = self._discover_temperature_unit()
        real_target = self._get_real_target_temperature()
        if real_target is not None:
            self._sync_virtual_target_from_real(real_target)
            self._last_real_target_temp = real_target
        self.async_write_ha_state()

    @callback
    def _async_handle_sensor_state_event(self, event) -> None:
        """Handle updates to any configured sensor."""

        entity_id = event.data.get("entity_id")
        new_state: State | None = event.data.get("new_state")
        if entity_id:
            self._sensor_states[entity_id] = new_state
        self._update_sensor_health_from_state(entity_id, new_state)
        if self._is_active_sensor_entity(entity_id):
            self._schedule_sensor_realignment()
        self.async_write_ha_state()

    def _is_active_sensor_entity(self, entity_id: str | None) -> bool:
        if not entity_id:
            return False
        sensor = self._sensor_lookup.get(self._selected_sensor_name)
        if not sensor or sensor.is_physical:
            return False
        return sensor.entity_id == entity_id

    def _schedule_sensor_realignment(self) -> None:
        if self._sensor_realign_task and not self._sensor_realign_task.done():
            return

        async def _run():
            try:
                await self._async_realign_real_target_from_sensor()
            finally:
                self._sensor_realign_task = None

        self._sensor_realign_task = self.hass.async_create_task(_run())

    def _discover_temperature_unit(self) -> str:
        if self._real_state and (unit := self._real_state.attributes.get("unit_of_measurement")):
            return unit
        return self.hass.config.units.temperature_unit or UnitOfTemperature.CELSIUS

    def _get_real_current_temperature(self) -> float | None:
        if not self._real_state:
            self._mark_entity_health(self._real_entity_id, False)
            return None
        if self._real_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            self._mark_entity_health(self._real_entity_id, False)
            return None
        value = _coerce_temperature(
            self._real_state.attributes.get(ATTR_CURRENT_TEMPERATURE)
        )
        self._mark_entity_health(self._real_entity_id, value is not None)
        return value

    def _get_real_target_temperature(self) -> float | None:
        if not self._real_state:
            self._mark_entity_health(self._real_entity_id, False)
            return None
        value = _coerce_temperature(self._real_state.attributes.get(ATTR_TEMPERATURE))
        if value is None:
            self._mark_entity_health(self._real_entity_id, False)
        else:
            self._mark_entity_health(self._real_entity_id, True)
        return value

    def _get_active_sensor_temperature(self) -> float | None:
        sensor = self._sensor_lookup.get(self._selected_sensor_name)
        if not sensor:
            return None
        if sensor.is_physical:
            return self._get_real_current_temperature()
        state = self._sensor_states.get(sensor.entity_id)
        if not state or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            self._mark_entity_health(sensor.entity_id, False)
            return None
        value = _coerce_temperature(state.state)
        if value is None:
            self._mark_entity_health(sensor.entity_id, False)
            return None
        self._mark_entity_health(sensor.entity_id, True)
        return value

    def _sync_virtual_target_from_real(self, real_target: float) -> None:
        if (
            self._last_requested_real_target is not None
            and math.isclose(real_target, self._last_requested_real_target, abs_tol=0.05)
        ):
            self._last_requested_real_target = None
            return

        sensor_temp = self._get_active_sensor_temperature()
        real_current = self._get_real_current_temperature()
        fallback = self._virtual_target_temperature
        if sensor_temp is None:
            sensor_temp = real_current
        if sensor_temp is None or real_current is None:
            return
        derived = sensor_temp + (real_target - real_current)
        if derived is not None:
            self._virtual_target_temperature = self._apply_target_constraints(derived)
        else:
            self._virtual_target_temperature = fallback

    @property
    def temperature_unit(self) -> str:
        return self._temperature_unit or self.hass.config.units.temperature_unit

    @property
    def min_temp(self) -> float:
        if self._min_temp is not None:
            return self._min_temp
        return super().min_temp

    @property
    def max_temp(self) -> float:
        if self._max_temp is not None:
            return self._max_temp
        return super().max_temp

    @property
    def target_temperature_step(self) -> float | None:
        if self._target_temp_step is not None:
            return self._target_temp_step
        return 1.0

    @property
    def precision(self) -> float:
        return self.target_temperature_step or DEFAULT_PRECISION

    @property
    def current_temperature(self) -> float | None:
        return self._get_active_sensor_temperature() or self._get_real_current_temperature()

    @property
    def target_temperature(self) -> float | None:
        return self._virtual_target_temperature

    @property
    def hvac_mode(self) -> HVACMode | None:
        if self._real_state:
            try:
                return HVACMode(self._real_state.state)
            except ValueError:
                return None
        return None

    @property
    def hvac_modes(self) -> list[HVACMode]:
        if not self._real_state:
            return []
        modes = self._real_state.attributes.get("hvac_modes")
        if not isinstance(modes, list):
            return []
        result: list[HVACMode] = []
        for mode in modes:
            try:
                result.append(HVACMode(mode))
            except ValueError:
                continue
        return result

    @property
    def preset_modes(self) -> list[str] | None:
        return [sensor.name for sensor in self._sensors]

    @property
    def preset_mode(self) -> str | None:
        return self._selected_sensor_name

    @property
    def available(self) -> bool:
        if not self._real_state:
            return False
        if self._real_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return False
        return True

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        if self._real_state:
            forwarded = {
                key: value
                for key, value in self._real_state.attributes.items()
                if key not in _RESERVED_REAL_ATTRIBUTES
            }
            attrs.update(forwarded)
        sensor = self._sensor_lookup.get(self._selected_sensor_name)
        attrs.update(
            {
                ATTR_ACTIVE_SENSOR: self._selected_sensor_name,
                ATTR_ACTIVE_SENSOR_ENTITY_ID: sensor.entity_id if sensor else None,
                ATTR_REAL_CURRENT_TEMPERATURE: self._get_real_current_temperature(),
                ATTR_REAL_TARGET_TEMPERATURE: self._last_real_target_temp
                or self._get_real_target_temperature(),
                ATTR_SELECTED_SENSOR_OPTIONS: {
                    item.name: (
                        self._real_entity_id if item.is_physical else item.entity_id
                    )
                    for item in self._sensors
                },
                ATTR_UNAVAILABLE_ENTITIES: sorted(
                    entity
                    for entity, healthy in self._entity_health.items()
                    if not healthy
                ),
            }
        )
        return attrs

    async def async_set_temperature(self, **kwargs: Any) -> None:
        async with self._command_lock:
            temperature = kwargs.get(ATTR_TEMPERATURE)
            requested = _coerce_temperature(temperature)
            if requested is None:
                _LOGGER.warning(
                    "Set temperature called with invalid value '%s' for %s",
                    temperature,
                    self.entity_id,
                )
                return

            constrained_target = self._apply_target_constraints(requested)
            if requested != constrained_target:
                _LOGGER.info(
                    "%s target adjusted from %s to %s to honor thermostat limits",
                    self.entity_id,
                    requested,
                    constrained_target,
                )

            display_current = self.current_temperature
            real_current = self._get_real_current_temperature()
            if display_current is None or real_current is None:
                _LOGGER.warning(
                    "Cannot compute temperature delta for %s because sensor or thermostat is missing",
                    self.entity_id,
                )
                return

            delta = constrained_target - display_current
            real_target = self._apply_target_constraints(real_current + delta)
            payload = {
                ATTR_ENTITY_ID: self._real_entity_id,
                ATTR_TEMPERATURE: real_target,
            }
            if ATTR_HVAC_MODE in kwargs and kwargs[ATTR_HVAC_MODE] is not None:
                payload[ATTR_HVAC_MODE] = kwargs[ATTR_HVAC_MODE]

            await self.hass.services.async_call(
                CLIMATE_DOMAIN,
                SERVICE_SET_TEMPERATURE,
                payload,
                blocking=True,
            )

            self._virtual_target_temperature = constrained_target
            self._last_requested_real_target = real_target
            self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        await self.hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_HVAC_MODE,
            {
                ATTR_ENTITY_ID: self._real_entity_id,
                ATTR_HVAC_MODE: hvac_mode,
            },
            blocking=True,
        )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode not in self._sensor_lookup:
            raise ValueError(f"Unknown preset '{preset_mode}'")

        self._selected_sensor_name = preset_mode
        # Only rebuild the virtual target if we don't yet have a stored value (e.g. very first run).
        if self._virtual_target_temperature is None:
            real_target = self._last_real_target_temp or self._get_real_target_temperature()
            if real_target is not None:
                self._sync_virtual_target_from_real(real_target)
        await self._async_realign_real_target_from_sensor()
        self.async_write_ha_state()

        await self.hass.services.async_call(
            LOGBOOK_DOMAIN,
            LOGBOOK_SERVICE_LOG,
            {
                "name": self.name,
                "entity_id": self.entity_id,
                "message": f"Preset changed to '{preset_mode}'",
            },
            blocking=False,
        )

    async def _async_realign_real_target_from_sensor(self) -> None:
        """Push a new target temperature to the real thermostat based on the active sensor."""

        if self._virtual_target_temperature is None:
            return

        async with self._command_lock:
            sensor_temp = self._get_active_sensor_temperature()
            real_current = self._get_real_current_temperature()
            if sensor_temp is None or real_current is None:
                return

            delta = self._virtual_target_temperature - sensor_temp
            desired_real_target = self._apply_target_constraints(real_current + delta)
            if desired_real_target is None:
                return

            current_real_target = self._get_real_target_temperature()
            tolerance = max(self.precision or DEFAULT_PRECISION, 0.1)
            if current_real_target is not None and math.isclose(
                current_real_target, desired_real_target, abs_tol=tolerance
            ):
                return
            if self._last_requested_real_target is not None and math.isclose(
                self._last_requested_real_target, desired_real_target, abs_tol=tolerance
            ):
                return

            await self.hass.services.async_call(
                CLIMATE_DOMAIN,
                SERVICE_SET_TEMPERATURE,
                {
                    ATTR_ENTITY_ID: self._real_entity_id,
                    ATTR_TEMPERATURE: desired_real_target,
                },
                blocking=True,
            )
            self._last_requested_real_target = desired_real_target
            self._last_real_target_temp = desired_real_target


    async def _async_restore_state(self) -> None:
        last_state = await self.async_get_last_state()
        if not last_state:
            return

        restored_sensor = last_state.attributes.get(ATTR_ACTIVE_SENSOR)
        if self._configured_default_sensor:
            self._selected_sensor_name = self._configured_default_sensor
        elif restored_sensor in self._sensor_lookup:
            self._selected_sensor_name = restored_sensor

        restored_virtual = _coerce_temperature(last_state.attributes.get(ATTR_TEMPERATURE))
        if restored_virtual is not None:
            self._virtual_target_temperature = self._apply_target_constraints(
                restored_virtual
            )

        restored_real = _coerce_temperature(
            last_state.attributes.get(ATTR_REAL_TARGET_TEMPERATURE)
        )
        if restored_real is not None:
            self._last_real_target_temp = restored_real

    def _update_real_temperature_limits(self) -> None:
        if not self._real_state:
            self._min_temp = None
            self._max_temp = None
            self._target_temp_step = None
            self._mark_entity_health(self._real_entity_id, False)
            return

        is_available = self._real_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN)
        self._mark_entity_health(self._real_entity_id, is_available)

        self._min_temp = _coerce_temperature(self._real_state.attributes.get(ATTR_MIN_TEMP))
        self._max_temp = _coerce_temperature(self._real_state.attributes.get(ATTR_MAX_TEMP))
        step_attr = self._real_state.attributes.get(ATTR_TARGET_TEMP_STEP)
        try:
            self._target_temp_step = float(step_attr) if step_attr is not None else None
        except (TypeError, ValueError):
            self._target_temp_step = None

    def _update_sensor_health_from_state(self, entity_id: str | None, state: State | None) -> None:
        if not entity_id:
            return
        if not state or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            self._mark_entity_health(entity_id, False)
            return
        self._mark_entity_health(entity_id, _coerce_temperature(state.state) is not None)

    def _mark_entity_health(self, entity_id: str | None, is_available: bool) -> None:
        if not entity_id:
            return
        previous = self._entity_health.get(entity_id)
        if previous == is_available:
            return
        self._entity_health[entity_id] = is_available
        if not is_available:
            _LOGGER.warning(
                "Entity %s became unavailable for %s; using fallbacks where possible",
                entity_id,
                self.entity_id,
            )
        elif previous is not None:
            _LOGGER.info(
                "Entity %s recovered for %s",
                entity_id,
                self.entity_id,
            )

    def _apply_target_constraints(self, value: float | None) -> float | None:
        if value is None:
            return None
        result = value
        min_temp = self.min_temp
        max_temp = self.max_temp
        if min_temp is not None:
            result = max(result, min_temp)
        if max_temp is not None:
            result = min(result, max_temp)
        step = self.target_temperature_step
        if step:
            try:
                if step > 0:
                    result = round(result / step) * step
            except TypeError:
                step = None
        if min_temp is not None:
            result = max(result, min_temp)
        if max_temp is not None:
            result = min(result, max_temp)
        return self._round_temperature(result)

    def _round_temperature(self, value: float) -> float:
        precision = self.precision or DEFAULT_PRECISION
        if precision >= 1:
            return round(value)
        if math.isclose(precision, 0.5, abs_tol=0.01):
            return round(value * 2) / 2

        decimals = max(1, min(3, int(round(-math.log10(precision)))))
        return round(value, decimals)

    def _add_physical_sensor(self, sensors: list[SensorConfig]) -> list[SensorConfig]:
        sensors_with_physical = list(sensors)
        if any(sensor.name == PHYSICAL_SENSOR_NAME for sensor in sensors_with_physical):
            _LOGGER.warning(
                "Sensor name '%s' is reserved for %s; skipping built-in physical sensor",
                PHYSICAL_SENSOR_NAME,
                self.entity_id,
            )
            return sensors_with_physical

        sensors_with_physical.append(
            SensorConfig(
                name=PHYSICAL_SENSOR_NAME,
                entity_id=PHYSICAL_SENSOR_SENTINEL,
                is_physical=True,
            )
        )
        return sensors_with_physical


def _coerce_temperature(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number):
        return None
    return number
