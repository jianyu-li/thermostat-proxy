"""Tests for the sensor_change_threshold (Smart Rate Limiter) feature."""

import time
from unittest.mock import MagicMock

import pytest

from custom_components.thermostat_proxy.climate import CustomThermostatEntity
from homeassistant.components.climate import (
    ATTR_TEMPERATURE,
    SERVICE_SET_TEMPERATURE,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.core import HomeAssistant, State


def create_proxy(
    hass,
    thermostat="climate.real",
    sensors=None,
    sensor_change_threshold=0.5,
    target_temp_step=0.1,
    cooldown_period=0,
):
    """Helper to create a configured CustomThermostatEntity."""
    if sensors is None:
        sensors = [{"name": "Kids Room", "entity_id": "sensor.kids_room"}]

    proxy = CustomThermostatEntity(
        hass=hass,
        name="Test Proxy",
        real_thermostat=thermostat,
        sensors=sensors,
        default_sensor="Kids Room",
        unique_id="123",
        physical_sensor_name="Physical",
        use_last_active_sensor=False,
        sensor_change_threshold=sensor_change_threshold,
        cooldown_period=cooldown_period,
    )
    proxy.entity_id = "climate.test_proxy"

    real_attrs = {
        "current_temperature": 73.0,
        "temperature": 73.0,
        "hvac_action": HVACAction.COOLING,
        "target_temp_step": target_temp_step,
        "supported_features": ClimateEntityFeature.TARGET_TEMPERATURE,
    }
    hass.states.async_set(thermostat, HVACMode.COOL, dict(real_attrs))
    proxy._real_state = hass.states.get(thermostat)

    async def mock_async_call(domain, service, service_data, **kwargs):
        if service == SERVICE_SET_TEMPERATURE and ATTR_TEMPERATURE in service_data:
            real_attrs["temperature"] = service_data[ATTR_TEMPERATURE]
            hass.states.async_set(thermostat, HVACMode.COOL, dict(real_attrs))
            proxy._real_state = hass.states.get(thermostat)

    hass.services.async_call.side_effect = mock_async_call

    proxy._update_real_temperature_limits()
    proxy._temperature_unit = "°F"
    proxy.async_write_ha_state = MagicMock()
    return proxy


@pytest.mark.asyncio
async def test_sensor_change_threshold_skipping(hass):
    """Test that updates below threshold are skipped when not crossing target."""
    proxy = create_proxy(hass, sensor_change_threshold=0.5)
    proxy._virtual_target_temperature = 75.0

    # Initial state: Kids room 76.0 (needs cool)
    proxy._sensor_states["sensor.kids_room"] = State("sensor.kids_room", "76.0")

    # 1. First realign -> Should run and record 76.0
    await proxy._async_realign_real_target_from_sensor(trigger_source="sensor")
    assert proxy._last_acted_sensor_temp == 76.0
    initial_calls = hass.services.async_call.call_count
    assert initial_calls > 0
    assert proxy._get_real_target_temperature() == 72.0

    # 2. Sensor drops slightly to 75.7 (change = 0.3 < 0.5 threshold, not satisfied yet)
    proxy._sensor_states["sensor.kids_room"] = State("sensor.kids_room", "75.7")
    await proxy._async_realign_real_target_from_sensor(trigger_source="sensor")
    # Call count should remain unchanged (skipped!)
    assert hass.services.async_call.call_count == initial_calls
    assert proxy._last_acted_sensor_temp == 76.0


@pytest.mark.asyncio
async def test_sensor_change_threshold_target_met_override(hass):
    """Test that crossing/meeting target overrides threshold to stop cooling immediately."""
    proxy = create_proxy(hass, sensor_change_threshold=0.5)
    proxy._virtual_target_temperature = 75.0

    # Initial state: 76.0 (Target: 75.0, Real Temp: 73.0 -> Real Target: 72.0)
    proxy._sensor_states["sensor.kids_room"] = State("sensor.kids_room", "76.0")
    await proxy._async_realign_real_target_from_sensor(trigger_source="sensor")
    count_1 = hass.services.async_call.call_count
    assert proxy._get_real_target_temperature() == 72.0

    # Sensor drops to 75.8 (change = 0.2 < 0.5 threshold, not satisfied yet) -> Skipped!
    proxy._sensor_states["sensor.kids_room"] = State("sensor.kids_room", "75.8")
    await proxy._async_realign_real_target_from_sensor(trigger_source="sensor")
    count_2 = hass.services.async_call.call_count
    assert count_2 == count_1  # Skipped!
    assert proxy._last_acted_sensor_temp == 76.0

    # Sensor drops to 75.0 (change = 0.8 from 76.0, AND meets target!)
    # Target: 75.0, Sensor: 75.0 -> Delta: 0 -> Real Target: 73.0
    proxy._sensor_states["sensor.kids_room"] = State("sensor.kids_room", "75.0")
    await proxy._async_realign_real_target_from_sensor(trigger_source="sensor")
    count_3 = hass.services.async_call.call_count
    assert count_3 > count_2  # Target met override fired!
    assert proxy._last_acted_sensor_temp == 75.0
    assert proxy._get_real_target_temperature() == 73.0


@pytest.mark.asyncio
async def test_sensor_change_threshold_zero_backward_compatibility(hass):
    """Test that setting threshold to 0.0 disables skipping (backward compatibility)."""
    proxy = create_proxy(hass, sensor_change_threshold=0.0)
    proxy._virtual_target_temperature = 75.0

    # Initial state: 76.0 (Target: 75.0 -> Real target: 72.0)
    proxy._sensor_states["sensor.kids_room"] = State("sensor.kids_room", "76.0")
    await proxy._async_realign_real_target_from_sensor(trigger_source="sensor")
    count_1 = hass.services.async_call.call_count

    # Small 0.2 change to 75.8 (Real target becomes 72.2)
    proxy._sensor_states["sensor.kids_room"] = State("sensor.kids_room", "75.8")
    await proxy._async_realign_real_target_from_sensor(trigger_source="sensor")
    count_2 = hass.services.async_call.call_count
    # Should NOT skip because threshold is 0.0
    assert count_2 > count_1


@pytest.mark.asyncio
async def test_sensor_change_threshold_skips_during_cooldown(
    hass: HomeAssistant,
) -> None:
    """Test that sub-threshold sensor noise during cooldown does not schedule a retry timer."""
    proxy = create_proxy(
        hass,
        sensor_change_threshold=0.5,
        cooldown_period=60,
    )
    proxy._virtual_target_temperature = 75.0
    proxy._last_acted_sensor_temp = 70.0
    proxy._last_real_write_time = time.monotonic()

    # Initial sensor state
    hass.states.async_set("sensor.kids_room", "70.0")
    proxy._sensor_states["sensor.kids_room"] = hass.states.get("sensor.kids_room")

    await proxy._async_subscribe_to_states()

    # Change sensor state within threshold (0.2 < 0.5)
    hass.states.async_set("sensor.kids_room", "70.2")
    await hass.async_block_till_done()

    # Verify no cooldown retry timer was scheduled for sub-threshold noise
    assert proxy._cooldown_timer_unsub is None

    await proxy.async_will_remove_from_hass()
