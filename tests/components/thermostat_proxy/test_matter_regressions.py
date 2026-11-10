"""Regressions for thermostats with incomplete or rounded state reports."""

import time
from unittest.mock import MagicMock

import pytest

from homeassistant.components.climate import HVACMode
from homeassistant.core import State

from .test_climate import create_proxy


@pytest.mark.parametrize(
    "action", [None, "unknown", "unavailable", "off", "idle", "heating"]
)
@pytest.mark.parametrize("already_active", [False, True])
@pytest.mark.asyncio
async def test_heating_overdrive_requires_known_action(hass, action, already_active):
    """Missing action must neither start nor retain a heating boost."""
    proxy = create_proxy(hass, target_temp_step=0.1)
    proxy._virtual_target_temperature = 22.0
    proxy._selected_sensor_name = "Sensor 1"
    proxy._sensor_states["sensor.1"] = State("sensor.1", "20.0")
    attrs = dict(proxy._real_state.attributes)
    if action is not None:
        attrs["hvac_action"] = action
    proxy._real_state = State("climate.real", HVACMode.HEAT, attrs)
    proxy._active_overdrive_heat = already_active

    active, offset = proxy._evaluate_single_target_overdrive(20.0)

    expected = action == "idle" or (already_active and action == "heating")
    assert active is expected
    assert proxy._active_overdrive_heat is expected
    assert offset == (proxy._overdrive_offset if expected else 0.0)


@pytest.mark.parametrize("new_target", [69.0, 68.0, 70.0])
@pytest.mark.asyncio
async def test_target_detection_uses_reported_transition(hass, new_target):
    """An unchanged reported target is not a dial adjustment after guards expire."""
    proxy = create_proxy(hass, target_temp_step=0.1)
    proxy._temperature_unit = "°F"
    proxy._min_temp = 50.0
    proxy._max_temp = 90.0
    proxy._virtual_target_temperature = 70.0
    proxy._selected_sensor_name = "Sensor 1"
    proxy._sensor_states["sensor.1"] = State("sensor.1", "70.0")
    proxy._last_real_target_temp = 69.8
    proxy._last_commanded_real_target = 69.8
    proxy._last_real_write_time = time.monotonic() - 180.0
    proxy._recent_real_target_requests = []
    proxy.async_write_ha_state = MagicMock()
    proxy._schedule_target_realign = MagicMock()
    attrs = {
        "current_temperature": 71.0,
        "temperature": 69.0,
        "target_temp_step": 0.1,
        "temperature_unit": "°F",
        "min_temp": 50.0,
        "max_temp": 90.0,
    }
    old = State("climate.real", HVACMode.HEAT, attrs)
    new = State(
        "climate.real",
        HVACMode.HEAT,
        {**attrs, "current_temperature": 72.0, "temperature": new_target},
    )
    event = MagicMock()
    event.data = {"old_state": old, "new_state": new}

    proxy._async_handle_real_state_event(event)

    assert proxy._selected_sensor_name == (
        "Sensor 1" if new_target == 69.0 else "Physical"
    )
    assert proxy._virtual_target_temperature == (
        70.0 if new_target == 69.0 else new_target
    )
