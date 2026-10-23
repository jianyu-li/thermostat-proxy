"""Helper utilities and configuration parsers for Thermostat Proxy."""

from __future__ import annotations

from collections.abc import Mapping
import datetime
import logging
from typing import Any, TypedDict

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
    CONF_USE_LAST_ACTIVE_SENSOR,
    DEFAULT_COOLDOWN_PERIOD,
    DEFAULT_DISABLE_AUTO_SWITCH,
    DEFAULT_MAX_HUMIDITY_OVERCOOL,
    DEFAULT_MAX_SYNC_OFFSET,
    DEFAULT_OVERDRIVE_OFFSET,
    DEFAULT_PRESERVE_VIRTUAL_TARGET,
    DEFAULT_SENSOR_CHANGE_THRESHOLD,
    DEFAULT_SENSOR_LAST_ACTIVE,
    DEFAULT_TARGET_HUMIDITY,
    PHYSICAL_SENSOR_NAME,
    TARGET_CHANGE_BEHAVIOR_AUTO_SWITCH,
    TARGET_CHANGE_BEHAVIOR_DISABLE_AUTO_SWITCH,
    TARGET_CHANGE_BEHAVIOR_PRESERVE_VIRTUAL_TARGET,
)

_LOGGER = logging.getLogger(__name__)


class EntityConfig(TypedDict):
    """Typed dictionary representing resolved entity configuration kwargs."""

    physical_sensor_name: str
    default_sensor: str | None
    use_last_active_sensor: bool
    disable_auto_switch: bool
    preserve_virtual_target: bool
    cooldown_period: float | int | datetime.timedelta
    user_min_temp: float | None
    user_max_temp: float | None
    max_sync_offset: float | None
    sensor_change_threshold: float
    max_humidity_overcool: float
    default_target_humidity: int
    min_dual_temp_spread: float | None
    overdrive_offset: float


def target_change_behavior_from_flags(
    disable_auto_switch: bool,
    preserve_virtual_target: bool,
) -> str:
    """Return the selector behavior corresponding to legacy boolean flags."""
    if disable_auto_switch and preserve_virtual_target:
        return TARGET_CHANGE_BEHAVIOR_PRESERVE_VIRTUAL_TARGET
    if disable_auto_switch:
        return TARGET_CHANGE_BEHAVIOR_DISABLE_AUTO_SWITCH
    return TARGET_CHANGE_BEHAVIOR_AUTO_SWITCH


def target_change_flags_from_behavior(behavior: str | None) -> tuple[bool, bool]:
    """Return legacy boolean settings for a UI behavior."""
    if behavior == TARGET_CHANGE_BEHAVIOR_PRESERVE_VIRTUAL_TARGET:
        return True, True
    if behavior == TARGET_CHANGE_BEHAVIOR_DISABLE_AUTO_SWITCH:
        return True, False
    return False, False


def extract_runtime_settings(config: Mapping[str, Any]) -> dict[str, Any]:
    """Extract runtime settings from a mapping (e.g. entry data merged with options)."""
    raw_default_sensor = config.get(CONF_DEFAULT_SENSOR)
    use_last_active_sensor = config.get(CONF_USE_LAST_ACTIVE_SENSOR, False)
    if raw_default_sensor == DEFAULT_SENSOR_LAST_ACTIVE:
        use_last_active_sensor = True
        default_sensor = None
    else:
        default_sensor = raw_default_sensor

    behavior = config.get(CONF_PHYSICAL_TARGET_CHANGE_BEHAVIOR)
    if behavior is not None:
        disable_auto_switch, preserve_virtual_target = (
            target_change_flags_from_behavior(behavior)
        )
    else:
        disable_auto_switch = config.get(
            CONF_DISABLE_AUTO_SWITCH, DEFAULT_DISABLE_AUTO_SWITCH
        )
        preserve_virtual_target = config.get(
            CONF_PRESERVE_VIRTUAL_TARGET, DEFAULT_PRESERVE_VIRTUAL_TARGET
        )

    raw_max_sync_offset = config.get(CONF_MAX_SYNC_OFFSET, DEFAULT_MAX_SYNC_OFFSET)
    max_sync_offset: float | None
    if raw_max_sync_offset is not None and float(raw_max_sync_offset) != 0.0:
        max_sync_offset = float(raw_max_sync_offset)
    else:
        max_sync_offset = None

    return {
        CONF_DEFAULT_SENSOR: default_sensor,
        CONF_USE_LAST_ACTIVE_SENSOR: use_last_active_sensor,
        CONF_COOLDOWN_PERIOD: config.get(CONF_COOLDOWN_PERIOD, DEFAULT_COOLDOWN_PERIOD),
        CONF_MIN_TEMP: config.get(CONF_MIN_TEMP),
        CONF_MAX_TEMP: config.get(CONF_MAX_TEMP),
        CONF_MAX_SYNC_OFFSET: max_sync_offset,
        CONF_DISABLE_AUTO_SWITCH: disable_auto_switch,
        CONF_PRESERVE_VIRTUAL_TARGET: preserve_virtual_target,
        CONF_SENSOR_CHANGE_THRESHOLD: config.get(
            CONF_SENSOR_CHANGE_THRESHOLD, DEFAULT_SENSOR_CHANGE_THRESHOLD
        ),
        CONF_MAX_HUMIDITY_OVERCOOL: config.get(
            CONF_MAX_HUMIDITY_OVERCOOL, DEFAULT_MAX_HUMIDITY_OVERCOOL
        ),
        CONF_DEFAULT_TARGET_HUMIDITY: config.get(
            CONF_DEFAULT_TARGET_HUMIDITY, DEFAULT_TARGET_HUMIDITY
        ),
        CONF_MIN_DUAL_TEMP_SPREAD: config.get(CONF_MIN_DUAL_TEMP_SPREAD),
        CONF_OVERDRIVE_OFFSET: config.get(
            CONF_OVERDRIVE_OFFSET, DEFAULT_OVERDRIVE_OFFSET
        ),
    }


def extract_entity_config(
    config: Mapping[str, Any],
    valid_sensor_names: list[str] | None = None,
    entry_id: str | None = None,
    physical_sensor_name: str | None = None,
) -> EntityConfig:
    """Extract and resolve entity configuration settings."""
    resolved_physical_name = physical_sensor_name or config.get(
        CONF_PHYSICAL_SENSOR_NAME, PHYSICAL_SENSOR_NAME
    )
    settings = extract_runtime_settings(config)
    default_sensor = settings[CONF_DEFAULT_SENSOR]

    if (
        valid_sensor_names is not None
        and default_sensor
        and default_sensor not in valid_sensor_names
    ):
        source = f"config entry {entry_id}" if entry_id else "configuration"
        _LOGGER.warning(
            "Default sensor '%s' not in %s; falling back to first sensor",
            default_sensor,
            source,
        )
        default_sensor = None

    return {
        "physical_sensor_name": resolved_physical_name,
        "default_sensor": default_sensor,
        "use_last_active_sensor": settings[CONF_USE_LAST_ACTIVE_SENSOR],
        "disable_auto_switch": settings[CONF_DISABLE_AUTO_SWITCH],
        "preserve_virtual_target": settings[CONF_PRESERVE_VIRTUAL_TARGET],
        "cooldown_period": settings[CONF_COOLDOWN_PERIOD],
        "user_min_temp": settings[CONF_MIN_TEMP],
        "user_max_temp": settings[CONF_MAX_TEMP],
        "max_sync_offset": settings[CONF_MAX_SYNC_OFFSET],
        "sensor_change_threshold": settings[CONF_SENSOR_CHANGE_THRESHOLD],
        "max_humidity_overcool": settings[CONF_MAX_HUMIDITY_OVERCOOL],
        "default_target_humidity": settings[CONF_DEFAULT_TARGET_HUMIDITY],
        "min_dual_temp_spread": settings[CONF_MIN_DUAL_TEMP_SPREAD],
        "overdrive_offset": settings[CONF_OVERDRIVE_OFFSET],
    }
