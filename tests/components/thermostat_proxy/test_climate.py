"""Tests for the Thermostat Proxy climate platform."""

from unittest.mock import AsyncMock, MagicMock
import pytest

from homeassistant.core import HomeAssistant, State
from homeassistant.components.climate import ClimateEntityFeature, HVACMode
from custom_components.thermostat_proxy.climate import CustomThermostatEntity





def create_proxy(hass, thermostat="climate.real", sensors=None, target_temp_step=1.0):
    """Helper to create a configured CustomThermostatEntity."""
    if sensors is None:
        sensors = [{"name": "Sensor 1", "entity_id": "sensor.1"}]

    proxy = CustomThermostatEntity(
        hass=hass,
        name="Test Proxy",
        real_thermostat=thermostat,
        sensors=sensors,
        default_sensor="Sensor 1",
        unique_id="123",
        physical_sensor_name="Physical",
        use_last_active_sensor=False,
    )

    # Mock physical thermostat state
    hass.states.async_set(
        thermostat,
        HVACMode.HEAT,
        {
            "current_temperature": 20.0,
            "temperature": 22.0,
            "target_temp_step": target_temp_step,
            "supported_features": ClimateEntityFeature.TARGET_TEMPERATURE,
        },
    )
    proxy._real_state = hass.states.get(thermostat)
    proxy._update_real_temperature_limits()

    return proxy


@pytest.mark.asyncio
async def test_infer_sensor_precision(hass):
    """Test inference of sensor precision from state string."""
    proxy = create_proxy(hass)

    assert proxy._infer_sensor_precision(State("sensor.1", "22.8")) == 0.1
    assert proxy._infer_sensor_precision(State("sensor.1", "22.85")) == 0.01
    assert proxy._infer_sensor_precision(State("sensor.1", "22.0")) == 0.1
    assert proxy._infer_sensor_precision(State("sensor.1", "22")) == 1.0
    assert (
        proxy._infer_sensor_precision(State("sensor.1", "unknown")) == 0.1
    )  # DEFAULT_PRECISION


@pytest.mark.asyncio
async def test_precision_and_step_handling(hass):
    """Test that precision and target_temp_step handle coarse and fine sensors correctly."""
    proxy = create_proxy(hass, target_temp_step=0.5)

    # Sensor 1 reports 1.0 precision (coarse)
    hass.states.async_set("sensor.1", "22")

    proxy._sensor_states["sensor.1"] = State("sensor.1", "22")
    proxy._sensor_precisions["sensor.1"] = proxy._infer_sensor_precision(
        State("sensor.1", "22")
    )
    proxy._selected_sensor_name = "Sensor 1"

    # Thermostat step is 0.5. Even with coarse sensor (1.0), we preserve half-degree targets.
    # Display precision also correctly snaps to 0.5 instead of losing half-degree display.
    assert proxy.precision == 0.5
    assert proxy.target_temperature_step == 0.5

    # Switch to high precision sensor (0.01)
    proxy._sensor_states["sensor.1"] = State("sensor.1", "22.85")
    proxy._sensor_precisions["sensor.1"] = proxy._infer_sensor_precision(
        State("sensor.1", "22.85")
    )

    # Thermostat is 0.5, Sensor inferred is 0.01.
    # Sensor display precision caps at 0.1 (DEFAULT_PRECISION). min(0.5, 0.1) -> 0.1
    # Target step stays 0.5.
    assert proxy.precision == 0.1
    assert proxy.target_temperature_step == 0.5


@pytest.mark.asyncio
async def test_log_formatting_preserves_decimals(hass):
    """Test that math formatting methods preserve exactly one decimal place."""
    proxy = create_proxy(hass)
    proxy._precision_override = 0.5

    # Output should always have .1f
    res = proxy._format_math_sensor_virtual(22.0, 20.0, "°C")
    assert res == "22.0°C - 20.0°C = 2.0°C"

    res = proxy._format_math_real_adjustment(
        25.0, 22.5, 20.0, 27.5, "°C", overdrive_adjust=1.0
    )
    assert res == "25.0°C - 2.5°C (+1.0 overdrive) = 27.5°C"


@pytest.mark.asyncio
async def test_pending_request_tolerance_covers_step(hass):
    """Test that _pending_request_tolerance does not incorrectly incorporate target_temp_step to avoid ignoring manual changes."""
    proxy = create_proxy(hass, target_temp_step=0.5)
    proxy._sensor_precisions["sensor.1"] = 1.0
    # With coarse sensor (1.0), precision resolves to 0.5 (min of step and sensor).
    # precision / 2 is 0.25.
    # It should not use step (0.5) directly to increase tolerance, so tolerance should be 0.25.
    tolerance = proxy._pending_request_tolerance()
    assert tolerance == 0.25

@pytest.mark.asyncio
async def test_overdrive_short_cycling_and_threshold(hass):
    """Test that overdrive respects the threshold as a deadband and remains sticky."""
    proxy = create_proxy(hass, target_temp_step=0.1)
    proxy._sensor_change_threshold = 0.5
    proxy._virtual_target_temperature = 72.6
    proxy._last_real_target_temp = 72.6
    proxy._selected_sensor_name = "Sensor 1"
    
    mock_real_state = State(
        "climate.real",
        HVACMode.COOL,
        {
            "current_temperature": 72.6,
            "temperature": 72.6,
            "target_temp_step": 0.1,
            "hvac_action": "idle",
        },
    )
    
    mock_sensor_state = State("sensor.1", "72.6")
    
    hass.states.async_set("sensor.1", "72.6")
    proxy._real_state = mock_real_state
    proxy._sensor_states["sensor.1"] = mock_sensor_state
    
    # Run a dummy sync to setup state
    await proxy._async_realign_real_target_from_sensor(trigger_source="sensor")
    assert not proxy._active_overdrive_cool
    
    # Case 1: Room warms up slightly to 72.9 (within 0.5 threshold)
    mock_sensor_state = State("sensor.1", "72.9")
    proxy._sensor_states["sensor.1"] = mock_sensor_state
    await proxy._async_realign_real_target_from_sensor(trigger_source="cooldown_expired")
    # Should NOT trigger overdrive because 72.6 < (72.9 - 0.5) is False
    assert not proxy._active_overdrive_cool
    
    # Case 2: Room warms up to 73.2 (exceeds 0.5 threshold deadband)
    mock_sensor_state = State("sensor.1", "73.2")
    proxy._sensor_states["sensor.1"] = mock_sensor_state
    await proxy._async_realign_real_target_from_sensor(trigger_source="cooldown_expired")
    # SHOULD trigger overdrive because 72.6 < (73.2 - 0.5) is True
    assert proxy._active_overdrive_cool
    
    # Case 3: The physical thermostat starts cooling, but then stops prematurely (short cycling simulation)
    # The room dropped to 73.0. 73.0 is within the threshold but above the target.
    mock_real_state = State(
        "climate.real",
        HVACMode.COOL,
        {
            "current_temperature": 73.0,
            "temperature": 71.6, # target pushed down
            "target_temp_step": 0.1,
            "hvac_action": "idle", # Premature idle
        },
    )
    mock_sensor_state = State("sensor.1", "73.0")
    proxy._real_state = mock_real_state
    proxy._sensor_states["sensor.1"] = mock_sensor_state
    
    await proxy._async_realign_real_target_from_sensor(trigger_source="cooldown_expired")
    # Overdrive should still be true because we haven't reached target yet (72.6 < 73.0 - 0.1)!
    assert proxy._active_overdrive_cool

    # Case 4: Target is finally met
    mock_sensor_state = State("sensor.1", "72.5")
    proxy._sensor_states["sensor.1"] = mock_sensor_state
    await proxy._async_realign_real_target_from_sensor(trigger_source="cooldown_expired")
    # Target reached, overdrive should deactivate
    assert not proxy._active_overdrive_cool


@pytest.mark.asyncio
async def test_native_temperature_properties(hass):
    """Test that native_* temperature properties match their deprecated aliases."""
    proxy = create_proxy(hass)
    proxy._temperature_unit = "°C"
    proxy._virtual_target_temperature = 21.5

    assert proxy.native_temperature_unit == "°C"
    assert proxy.temperature_unit == proxy.native_temperature_unit

    assert proxy.native_current_temperature == 20.0
    assert proxy.current_temperature == proxy.native_current_temperature

    assert proxy.native_target_temperature == 21.5
    assert proxy.target_temperature == proxy.native_target_temperature

    # Range mode targets
    proxy._virtual_target_temperature_low = 19.0
    proxy._virtual_target_temperature_high = 23.0
    proxy._real_state = State(
        "climate.real",
        HVACMode.HEAT_COOL,
        {
            "current_temperature": 20.0,
            "target_temp_high": 24.0,
            "target_temp_low": 18.0,
            "supported_features": ClimateEntityFeature.TARGET_TEMPERATURE_RANGE,
        },
    )
    proxy._update_real_temperature_limits()

    assert proxy.native_target_temperature is None
    assert proxy.target_temperature is None
    assert proxy.native_target_temperature_low == 19.0
    assert proxy.target_temperature_low == proxy.native_target_temperature_low
    assert proxy.native_target_temperature_high == 23.0
    assert proxy.target_temperature_high == proxy.native_target_temperature_high


@pytest.mark.asyncio
async def test_discover_temperature_unit_and_reserved_attribute(hass):
    """Test that temperature_unit is discovered from real thermostat state attributes and excluded from extra_state_attributes."""
    proxy = create_proxy(hass)

    # Real thermostat state has the new temperature_unit attribute (HA Core 2026.11+)
    hass.states.async_set(
        "climate.real",
        HVACMode.HEAT,
        {
            "current_temperature": 68.0,
            "temperature": 70.0,
            "temperature_unit": "°F",
        },
    )
    proxy._real_state = hass.states.get("climate.real")

    # _discover_temperature_unit should pick up "temperature_unit"
    assert proxy._discover_temperature_unit() == "°F"

    # extra_state_attributes must NOT include "temperature_unit"
    assert "temperature_unit" not in proxy.extra_state_attributes


@pytest.mark.asyncio
async def test_async_entity_id_changed(hass):
    """Test that async_entity_id_changed executes without errors."""
    proxy = create_proxy(hass)
    proxy.entity_id = "climate.test_proxy_new"
    # Should run without error whether or not super() implements it
    proxy.async_entity_id_changed("climate.test_proxy_old")

