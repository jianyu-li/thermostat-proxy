"""Tests simulating scenarios in GitHub issues #31, #32, and #65."""

import time
from unittest.mock import MagicMock

import pytest

from custom_components.thermostat_proxy.climate import CustomThermostatEntity
from homeassistant.components.climate import ClimateEntityFeature, HVACMode
from homeassistant.components.climate.const import SERVICE_SET_TEMPERATURE
from homeassistant.core import State


@pytest.mark.parametrize(
    "hvac_mode", [HVACMode.HEAT, HVACMode.COOL, HVACMode.HEAT_COOL, HVACMode.AUTO]
)
@pytest.mark.asyncio
async def test_issue_31_decimal_current_temperature(hass, hvac_mode):
    """Test that a remote sensor with decimals displays decimals for current temperature across all modes."""
    proxy = CustomThermostatEntity(
        hass=hass,
        name="Test Proxy",
        real_thermostat="climate.real",
        sensors=[{"name": "Remote", "entity_id": "sensor.remote"}],
        default_sensor="Remote",
        unique_id="123",
        physical_sensor_name="Physical",
        use_last_active_sensor=False,
    )

    hass.states.async_set(
        "climate.real",
        hvac_mode,
        {
            "current_temperature": 20.0,
            "temperature": 22.0,
            "target_temp_low": 20.0,
            "target_temp_high": 24.0,
            "target_temp_step": 1.0,
            "supported_features": (
                ClimateEntityFeature.TARGET_TEMPERATURE
                | ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
            ),
        },
    )
    proxy._real_state = hass.states.get("climate.real")
    proxy._update_real_temperature_limits()

    proxy._temperature_unit = "°C"
    proxy._sensor_states["sensor.remote"] = State("sensor.remote", "22.8")
    proxy._sensor_precisions["sensor.remote"] = 0.1
    proxy._selected_sensor_name = "Remote"
    proxy.async_write_ha_state = MagicMock()

    # Check that the precision property returns 0.1 (not 1.0) so that HA frontend does not truncate/cut the decimals to 22.
    assert proxy.precision == 0.1


@pytest.mark.parametrize(
    "hvac_mode", [HVACMode.HEAT, HVACMode.COOL, HVACMode.HEAT_COOL, HVACMode.AUTO]
)
@pytest.mark.asyncio
async def test_issue_32_floor_rounding_thermostat_loop(hass, hvac_mode):
    """Test floor-rounding external change suppression across all HVAC modes."""
    proxy = CustomThermostatEntity(
        hass=hass,
        name="Test Proxy",
        real_thermostat="climate.real",
        sensors=[{"name": "Remote", "entity_id": "sensor.remote"}],
        default_sensor="Remote",
        unique_id="123",
        physical_sensor_name="Physical",
        use_last_active_sensor=False,
        disable_auto_switch=False,
    )

    # Physical thermostat MTS300 in Celsius mode, target_temp_step = 1.0 (Celsius)
    # The proxy is operating in Fahrenheit, target_temp_step = 1.8 (Fahrenheit)
    hass.states.async_set(
        "climate.real",
        hvac_mode,
        {
            "current_temperature": 75.0,
            "temperature": 73.4,  # floored Celsius value 23.0°C converted to Fahrenheit
            "target_temp_low": 68.0,
            "target_temp_high": 75.0,
            "target_temp_step": 1.8,
            "supported_features": (
                ClimateEntityFeature.TARGET_TEMPERATURE
                | ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
            ),
        },
    )
    proxy._real_state = hass.states.get("climate.real")
    proxy._update_real_temperature_limits()

    proxy._temperature_unit = "°F"
    proxy._sensor_states["sensor.remote"] = State("sensor.remote", "76.0")
    proxy._sensor_precisions["sensor.remote"] = 0.1
    proxy._selected_sensor_name = "Remote"
    proxy._virtual_target_temperature = 76.0
    proxy._target_temp_step = 1.8
    proxy.async_write_ha_state = MagicMock()

    # Proxy adjusts target and sends 74.5°F to real thermostat.
    proxy._last_real_target_temp = 74.5
    proxy._recent_real_target_requests = [(74.5, time.monotonic())]

    # Now, outside the post-write grace period (15 seconds later),
    # the MTS300 reports the floored value: 73.4°F (23.0°C)
    proxy._last_real_write_time = time.monotonic() - 15.0

    # Simulate receiving the state event with target = 73.4
    event = MagicMock()
    event.data = {
        "old_state": State(
            "climate.real",
            hvac_mode,
            {
                "current_temperature": 75.0,
                "temperature": 74.5,
                "target_temp_step": 1.8,
                "supported_features": (
                    ClimateEntityFeature.TARGET_TEMPERATURE
                    | ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
                ),
            },
        ),
        "new_state": State(
            "climate.real",
            hvac_mode,
            {
                "current_temperature": 75.0,
                "temperature": 73.4,
                "target_temp_step": 1.8,
                "supported_features": (
                    ClimateEntityFeature.TARGET_TEMPERATURE
                    | ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
                ),
            },
        ),
    }
    proxy._async_handle_real_state_event(event)

    # Check if the proxy switched to the physical sensor due to false external change detection.
    # If the bug is present, it will switch to "Physical". We assert it should NOT switch (preset remains "Remote").
    assert proxy._selected_sensor_name == "Remote"


@pytest.mark.asyncio
async def test_issue_65_trv_snapped_readback_no_upward_drift(hass):
    """Test that a TRV snapping setpoints doesn't cause upward temperature drift."""
    proxy = CustomThermostatEntity(
        hass=hass,
        name="Test Proxy",
        real_thermostat="climate.real",
        sensors=[{"name": "Remote", "entity_id": "sensor.remote"}],
        default_sensor="Remote",
        unique_id="123",
        physical_sensor_name="Physical",
        use_last_active_sensor=False,
    )

    hass.states.async_set(
        "climate.real",
        HVACMode.HEAT,
        {
            "current_temperature": 20.7,
            "temperature": 20.0,
            "target_temp_step": 0.1,
            "hvac_action": "idle",
            "supported_features": ClimateEntityFeature.TARGET_TEMPERATURE,
        },
    )
    proxy._real_state = hass.states.get("climate.real")
    proxy._update_real_temperature_limits()

    proxy._temperature_unit = "°C"
    proxy._sensor_states["sensor.remote"] = State("sensor.remote", "19.8")
    proxy._sensor_precisions["sensor.remote"] = 0.1
    proxy._selected_sensor_name = "Remote"
    proxy._virtual_target_temperature = 20.0
    proxy._target_temp_step = 0.1
    proxy.async_write_ha_state = MagicMock()

    # Initial realignment from sensor: overdrive engages (+1.0°C) and requests 21.9°C
    # 20.7 + (20.0 - 19.8) + 1.0 = 21.9
    await proxy._async_realign_real_target_from_sensor(trigger_source="sensor")

    assert proxy._active_overdrive_heat is True
    assert proxy._last_real_target_temp == 21.9

    # Simulate TRV snapping 21.9°C to 21.5°C and reporting temperature=21.5 within grace period
    proxy._last_real_write_time = time.monotonic() - 10.0
    old_state = proxy._real_state
    new_state = State(
        "climate.real",
        HVACMode.HEAT,
        {
            "current_temperature": 20.7,
            "temperature": 21.5,
            "target_temp_step": 0.1,
            "hvac_action": "idle",
            "supported_features": ClimateEntityFeature.TARGET_TEMPERATURE,
        },
    )
    hass.states.async_set(
        "climate.real",
        new_state.state,
        new_state.attributes,
    )
    event = MagicMock()
    event.data = {"old_state": old_state, "new_state": new_state}
    proxy._real_state = new_state
    proxy._async_handle_real_state_event(event)

    assert proxy._selected_sensor_name == "Remote"
    assert proxy._virtual_target_temperature == 20.0

    # Simulate cooldown / timeout expiring (135s elapsed since write)
    hass.services.async_call.reset_mock()
    proxy._last_real_write_time = time.monotonic() - 135.0

    # Realign while sensor is still 19.8°C and real current is still 20.7°C
    await proxy._async_realign_real_target_from_sensor(trigger_source="sensor")

    # Proxy should recognize TRV is already at snapped target 21.5°C for commanded 21.9°C
    # and should NOT re-write 21.9°C
    set_temp_calls = [
        c
        for c in hass.services.async_call.call_args_list
        if c.args and len(c.args) >= 2 and c.args[1] == SERVICE_SET_TEMPERATURE
    ]
    assert len(set_temp_calls) == 0

    # Simulate TRV reporting temperature=21.5 again outside grace period (135s after write)
    # e.g. when current_temperature updates from 20.7 to 20.6
    proxy._last_real_write_time = time.monotonic() - 135.0
    old_state = proxy._real_state
    new_state = State(
        "climate.real",
        HVACMode.HEAT,
        {
            "current_temperature": 20.6,
            "temperature": 21.5,
            "target_temp_step": 0.1,
            "hvac_action": "idle",
            "supported_features": ClimateEntityFeature.TARGET_TEMPERATURE,
        },
    )
    hass.states.async_set(
        "climate.real",
        new_state.state,
        new_state.attributes,
    )
    event = MagicMock()
    event.data = {"old_state": old_state, "new_state": new_state}
    proxy._real_state = new_state
    proxy._async_handle_real_state_event(event)

    # Verify proxy does NOT treat 21.5°C as an external change
    assert proxy._selected_sensor_name == "Remote"
    assert proxy._virtual_target_temperature == 20.0


@pytest.mark.asyncio
async def test_issue_65_no_overdrive_on_physical_preset(hass):
    """Test that overdrive does not engage when physical sensor preset is active."""
    proxy = CustomThermostatEntity(
        hass=hass,
        name="Test Proxy",
        real_thermostat="climate.real",
        sensors=[{"name": "Remote", "entity_id": "sensor.remote"}],
        default_sensor="Physical",
        unique_id="123",
        physical_sensor_name="Physical",
        use_last_active_sensor=False,
    )

    hass.states.async_set(
        "climate.real",
        HVACMode.HEAT,
        {
            "current_temperature": 20.0,
            "temperature": 21.5,
            "target_temp_step": 0.5,
            "hvac_action": "idle",
            "supported_features": ClimateEntityFeature.TARGET_TEMPERATURE,
        },
    )
    proxy._real_state = hass.states.get("climate.real")
    proxy._update_real_temperature_limits()

    proxy._temperature_unit = "°C"
    proxy._selected_sensor_name = "Physical"
    proxy._virtual_target_temperature = 21.5
    proxy.async_write_ha_state = MagicMock()
    hass.services.async_call.reset_mock()

    await proxy._async_realign_real_target_from_sensor(trigger_source="real")

    assert proxy._active_overdrive_heat is False
    set_temp_calls = [
        c
        for c in hass.services.async_call.call_args_list
        if c.args and len(c.args) >= 2 and c.args[1] == SERVICE_SET_TEMPERATURE
    ]
    if set_temp_calls:
        target = set_temp_calls[0].args[2].get("temperature")
        assert target != 22.5


@pytest.mark.asyncio
async def test_issue_65_overdrive_disabled_when_offset_zero(hass):
    """Test that overdrive is disabled when overdrive_offset is 0.0."""
    proxy = CustomThermostatEntity(
        hass=hass,
        name="Test Proxy",
        real_thermostat="climate.real",
        sensors=[{"name": "Remote", "entity_id": "sensor.remote"}],
        default_sensor="Remote",
        unique_id="123",
        physical_sensor_name="Physical",
        use_last_active_sensor=False,
        overdrive_offset=0.0,
    )

    hass.states.async_set(
        "climate.real",
        HVACMode.HEAT,
        {
            "current_temperature": 20.5,
            "temperature": 20.5,
            "target_temp_step": 0.5,
            "hvac_action": "idle",
            "supported_features": ClimateEntityFeature.TARGET_TEMPERATURE,
        },
    )
    proxy._real_state = hass.states.get("climate.real")
    proxy._update_real_temperature_limits()

    proxy._temperature_unit = "°C"
    proxy._sensor_states["sensor.remote"] = State("sensor.remote", "19.0")
    proxy._sensor_precisions["sensor.remote"] = 0.1
    proxy._selected_sensor_name = "Remote"
    proxy._virtual_target_temperature = 20.0
    proxy.async_write_ha_state = MagicMock()
    hass.services.async_call.reset_mock()

    await proxy._async_realign_real_target_from_sensor(trigger_source="sensor")

    assert proxy._active_overdrive_heat is False
    assert proxy._last_real_target_temp == 21.5
    set_temp_calls = [
        c
        for c in hass.services.async_call.call_args_list
        if c.args and len(c.args) >= 2 and c.args[1] == SERVICE_SET_TEMPERATURE
    ]
    assert len(set_temp_calls) == 1
    assert set_temp_calls[0].args[2].get("temperature") == 21.5
