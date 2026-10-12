"""Tests for Thermostat Proxy dual setpoint mode (HEAT_COOL and AUTO)."""

from unittest.mock import AsyncMock, MagicMock
import pytest

from homeassistant.core import HomeAssistant, State, CoreState
from homeassistant.components.climate import HVACMode, ClimateEntityFeature, HVACAction

from custom_components.thermostat_proxy.climate import CustomThermostatEntity





def create_dual_proxy(hass, thermostat="climate.real", hvac_mode=HVACMode.HEAT_COOL):
    """Helper to create a configured CustomThermostatEntity in dual setpoint mode."""
    proxy = CustomThermostatEntity(
        hass=hass,
        name="Test Proxy",
        real_thermostat=thermostat,
        sensors=[{"name": "Remote", "entity_id": "sensor.remote"}],
        default_sensor="Remote",
        unique_id="123",
        physical_sensor_name="Physical",
        use_last_active_sensor=False,
    )
    proxy.entity_id = "climate.test_proxy"
    proxy.async_write_ha_state = MagicMock()

    hass.states.async_set(
        thermostat,
        hvac_mode,
        {
            "current_temperature": 20.0,
            "target_temp_low": 18.0,
            "target_temp_high": 24.0,
            "target_temp_step": 1.0,
            "supported_features": (
                ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
                | ClimateEntityFeature.PRESET_MODE
            ),
        },
    )
    proxy._real_state = hass.states.get(thermostat)
    proxy._update_real_temperature_limits()
    proxy._temperature_unit = "°C"
    proxy._sensor_states["sensor.remote"] = State("sensor.remote", "18.0")
    proxy._virtual_target_temperature_low = 18.0
    proxy._virtual_target_temperature_high = 24.0
    proxy._selected_sensor_name = "Remote"
    return proxy


@pytest.mark.parametrize("hvac_mode", [HVACMode.HEAT_COOL, HVACMode.AUTO])
@pytest.mark.asyncio
async def test_dual_setpoint_preset_mode_switch(hass, hvac_mode):
    """Test switching preset mode in range modes (HEAT_COOL / AUTO)."""
    proxy = create_dual_proxy(hass, hvac_mode=hvac_mode)

    # Preset should allow Remote sensor in range mode
    assert proxy.preset_mode == "Remote"
    assert proxy.target_temperature_low == 18.0
    assert proxy.target_temperature_high == 24.0

    # Switching to physical
    await proxy.async_set_preset_mode("Physical")
    assert proxy.preset_mode == "Physical"

    # Switching back to remote
    await proxy.async_set_preset_mode("Remote")
    assert proxy.preset_mode == "Remote"


@pytest.mark.parametrize("hvac_mode", [HVACMode.HEAT_COOL, HVACMode.AUTO])
@pytest.mark.asyncio
async def test_dual_setpoint_set_temperature(hass, hvac_mode):
    """Test set_temperature with low and high targets across range modes."""
    proxy = create_dual_proxy(hass, hvac_mode=hvac_mode)

    # Physical current = 20.0, Remote sensor = 18.0 (diff = +2.0)
    # Requested remote range: low = 19.0, high = 25.0
    # Expected real target: low = 21.0, high = 27.0
    await proxy.async_set_temperature(target_temp_low=19.0, target_temp_high=25.0)

    assert hass.services.async_call.called
    args, kwargs = hass.services.async_call.call_args
    assert args[0] == "climate"
    assert args[1] == "set_temperature"
    assert args[2]["target_temp_low"] == 21.0
    assert args[2]["target_temp_high"] == 27.0
    assert proxy.target_temperature_low == 19.0
    assert proxy.target_temperature_high == 25.0


@pytest.mark.asyncio
async def test_dual_setpoint_realignment(hass):
    """Test remote sensor realignment in dual setpoint mode."""
    proxy = create_dual_proxy(hass)

    proxy._real_state = State(
        "climate.real",
        HVACMode.HEAT_COOL,
        {
            "current_temperature": 20.0,
            "target_temp_low": 18.0,
            "target_temp_high": 24.0,
            "hvac_action": "heating",
            "target_temp_step": 1.0,
            "supported_features": ClimateEntityFeature.TARGET_TEMPERATURE_RANGE,
        },
    )

    # Remote sensor changes from 18.0 to 16.0 (2° colder than physical 20.0, delta = +4.0)
    proxy._sensor_states["sensor.remote"] = State("sensor.remote", "16.0")

    # Virtual low = 18.0, virtual high = 24.0
    # Calculated real low = 20.0 + (18.0 - 16.0) = 22.0
    # Calculated real high = 20.0 + (24.0 - 16.0) = 28.0
    await proxy._async_realign_real_target_from_sensor()

    assert hass.services.async_call.called
    args, kwargs = hass.services.async_call.call_args
    assert args[0] == "climate"
    assert args[1] == "set_temperature"
    assert args[2]["target_temp_low"] == 22.0
    assert args[2]["target_temp_high"] == 28.0


@pytest.mark.asyncio
async def test_dual_setpoint_overdrive_heat(hass):
    """Test heat overdrive in dual setpoint mode when remote is cold and system is idle."""
    proxy = create_dual_proxy(hass)

    # Thermostat is idle, current = 20.0, low = 18.0, high = 24.0
    proxy._real_state = State(
        "climate.real",
        HVACMode.HEAT_COOL,
        {
            "current_temperature": 20.0,
            "target_temp_low": 18.0,
            "target_temp_high": 24.0,
            "hvac_action": HVACAction.IDLE,
            "target_temp_step": 1.0,
            "supported_features": ClimateEntityFeature.TARGET_TEMPERATURE_RANGE,
        },
    )

    # Remote sensor is 16.0, virtual low = 18.0 (wants heat!)
    # Standard calculated real low = 20.0 + (18.0 - 16.0) = 22.0
    # Plus heat overdrive (+1.0) = 23.0
    proxy._sensor_states["sensor.remote"] = State("sensor.remote", "16.0")

    await proxy._async_realign_real_target_from_sensor()

    assert hass.services.async_call.called
    args, kwargs = hass.services.async_call.call_args
    assert args[0] == "climate"
    assert args[1] == "set_temperature"
    assert args[2]["target_temp_low"] == 23.0


@pytest.mark.asyncio
async def test_dual_setpoint_overdrive_cool(hass):
    """Test cool overdrive in dual setpoint mode when remote is hot and system is idle."""
    proxy = create_dual_proxy(hass)

    proxy._real_state = State(
        "climate.real",
        HVACMode.HEAT_COOL,
        {
            "current_temperature": 20.0,
            "target_temp_low": 18.0,
            "target_temp_high": 24.0,
            "hvac_action": HVACAction.IDLE,
            "target_temp_step": 1.0,
            "supported_features": ClimateEntityFeature.TARGET_TEMPERATURE_RANGE,
        },
    )

    # Remote sensor is 26.0, virtual high = 24.0 (wants cooling!)
    # Standard calculated real high = 20.0 + (24.0 - 26.0) = 18.0
    # Plus cool overdrive (-1.0) = 17.0
    proxy._sensor_states["sensor.remote"] = State("sensor.remote", "26.0")

    await proxy._async_realign_real_target_from_sensor()

    assert hass.services.async_call.called
    args, kwargs = hass.services.async_call.call_args
    assert args[0] == "climate"
    assert args[1] == "set_temperature"
    assert args[2]["target_temp_high"] == 17.0


@pytest.mark.asyncio
async def test_dual_setpoint_partial_set_temperature(hass):
    """Test setting only low or high temperature in dual setpoint mode."""
    proxy = create_dual_proxy(hass)

    # Only setting low
    await proxy.async_set_temperature(target_temp_low=19.0)

    assert hass.services.async_call.called
    args, kwargs = hass.services.async_call.call_args
    assert args[0] == "climate"
    assert args[1] == "set_temperature"
    assert args[2]["target_temp_low"] == 21.0
    assert "target_temp_high" not in args[2]
    assert proxy.target_temperature_low == 19.0


@pytest.mark.asyncio
async def test_dual_setpoint_service_error_handling(hass):
    """Test error handling during dual setpoint realignment."""
    proxy = create_dual_proxy(hass)

    proxy._sensor_states["sensor.remote"] = State("sensor.remote", "16.0")

    async def side_effect(domain, service, service_data, blocking=False):
        if domain == "climate":
            raise Exception("502 Bad Gateway")

    hass.services.async_call.side_effect = side_effect

    # Should handle error gracefully without raising
    await proxy._async_realign_real_target_from_sensor()


@pytest.mark.asyncio
async def test_dual_setpoint_overdrive_heat_deadband_enforcement_fahrenheit(hass):
    """Test that heating overdrive preserves the minimum dual setpoint deadband in Fahrenheit."""
    proxy = create_dual_proxy(hass)
    proxy._temperature_unit = "°F"
    proxy._target_temp_step = 0.5

    # Simulate overnight scenario:
    # Real thermostat: current = 63.0, low = 63.0, high = 71.0, idle
    proxy._real_state = State(
        "climate.real",
        HVACMode.HEAT_COOL,
        {
            "current_temperature": 63.0,
            "target_temp_low": 63.0,
            "target_temp_high": 71.0,
            "hvac_action": HVACAction.IDLE,
            "target_temp_step": 0.5,
            "supported_features": ClimateEntityFeature.TARGET_TEMPERATURE_RANGE,
        },
    )

    # Virtual setpoints: low = 68.0, high = 71.0 (3.0° spread)
    proxy._virtual_target_temperature_low = 68.0
    proxy._virtual_target_temperature_high = 71.0

    # Remote bedroom sensor drops to 66.5 (cold, wants heat)
    proxy._sensor_states["sensor.remote"] = State("sensor.remote", "66.5")

    # delta_low = 68.0 - 66.5 = +1.5 -> real low = 63.0 + 1.5 = 64.5
    # Overdrive applies +1.0 -> real low = 65.5
    # delta_high = 71.0 - 66.5 = +4.5 -> real high = 63.0 + 4.5 = 67.5
    # Without deadband enforcement, real spread is 67.5 - 65.5 = 2.0° (< 5.0° default min spread).
    # With deadband enforcement (prioritize heat), high is pushed to 65.5 + 5.0 = 70.5!
    await proxy._async_realign_real_target_from_sensor()

    assert hass.services.async_call.called
    args, kwargs = hass.services.async_call.call_args
    assert args[0] == "climate"
    assert args[1] == "set_temperature"
    assert args[2]["target_temp_low"] == 65.5
    assert args[2]["target_temp_high"] == 70.5
    assert (args[2]["target_temp_high"] - args[2]["target_temp_low"]) >= 5.0

    # Virtual targets on the proxy remain as configured by user
    assert proxy.target_temperature_low == 68.0
    assert proxy.target_temperature_high == 71.0


@pytest.mark.asyncio
async def test_dual_setpoint_overdrive_cool_deadband_enforcement_fahrenheit(hass):
    """Test that cooling overdrive preserves the minimum dual setpoint deadband in Fahrenheit."""
    proxy = create_dual_proxy(hass)
    proxy._temperature_unit = "°F"
    proxy._target_temp_step = 0.5

    proxy._real_state = State(
        "climate.real",
        HVACMode.HEAT_COOL,
        {
            "current_temperature": 72.0,
            "target_temp_low": 66.0,
            "target_temp_high": 74.0,
            "hvac_action": HVACAction.IDLE,
            "target_temp_step": 0.5,
            "supported_features": ClimateEntityFeature.TARGET_TEMPERATURE_RANGE,
        },
    )

    proxy._virtual_target_temperature_low = 68.0
    proxy._virtual_target_temperature_high = 71.0

    # Remote sensor is hot (74.0, wants cool)
    proxy._sensor_states["sensor.remote"] = State("sensor.remote", "74.0")

    # delta_high = 71.0 - 74.0 = -3.0 -> real high = 72.0 - 3.0 = 69.0
    # Overdrive applies -1.0 -> real high = 68.0
    # delta_low = 68.0 - 74.0 = -6.0 -> real low = 72.0 - 6.0 = 66.0
    # Spread would be 68.0 - 66.0 = 2.0° (< 5.0° min spread).
    # With deadband enforcement (prioritize cool), low is pushed down to 68.0 - 5.0 = 63.0!
    await proxy._async_realign_real_target_from_sensor()

    assert hass.services.async_call.called
    args, kwargs = hass.services.async_call.call_args
    assert args[0] == "climate"
    assert args[1] == "set_temperature"
    assert args[2]["target_temp_high"] == 68.0
    assert args[2]["target_temp_low"] == 63.0
    assert (args[2]["target_temp_high"] - args[2]["target_temp_low"]) >= 5.0


@pytest.mark.asyncio
async def test_dual_setpoint_set_temperature_deadband_enforcement(hass):
    """Test that async_set_temperature enforces min dual spread when user requests narrow targets."""
    proxy = create_dual_proxy(hass)
    proxy._temperature_unit = "°F"
    proxy._target_temp_step = 0.5
    proxy._min_dual_temp_spread = 5.0

    # Physical current = 70.0, Remote current = 70.0 (delta = 0)
    # Requested remote range: low = 68.0, high = 70.0 (spread = 2.0 < 5.0)
    proxy._sensor_states["sensor.remote"] = State("sensor.remote", "70.0")
    proxy._real_state = State(
        "climate.real",
        HVACMode.HEAT_COOL,
        {
            "current_temperature": 70.0,
            "target_temp_low": 68.0,
            "target_temp_high": 75.0,
            "target_temp_step": 0.5,
            "supported_features": ClimateEntityFeature.TARGET_TEMPERATURE_RANGE,
        },
    )

    await proxy.async_set_temperature(target_temp_low=68.0, target_temp_high=70.0)

    assert hass.services.async_call.called
    args, kwargs = hass.services.async_call.call_args
    assert args[0] == "climate"
    assert args[1] == "set_temperature"
    assert (args[2]["target_temp_high"] - args[2]["target_temp_low"]) >= 5.0


@pytest.mark.asyncio
async def test_dual_setpoint_no_false_unavailable_entities(hass):
    """Test that real thermostat is not marked unavailable in range mode when ATTR_TEMPERATURE is None."""
    proxy = create_dual_proxy(hass)

    # In dual setpoint mode, the physical thermostat has target_temp_low/high, but temperature is None
    proxy._real_state = State(
        "climate.real",
        HVACMode.HEAT_COOL,
        {
            "current_temperature": 20.0,
            "target_temp_low": 18.0,
            "target_temp_high": 24.0,
            "target_temp_step": 1.0,
            "supported_features": ClimateEntityFeature.TARGET_TEMPERATURE_RANGE,
        },
    )

    # Calling _get_real_target_temperature() should return None (expected in range mode)
    # but must NOT mark the real entity as unhealthy!
    assert proxy._get_real_target_temperature() is None
    assert proxy._get_real_target_temperature_low() == 18.0
    assert proxy._get_real_target_temperature_high() == 24.0

    # unavailable_entities must remain empty
    assert proxy.extra_state_attributes["unavailable_entities"] == []
    assert proxy._entity_health.get("climate.real") is True

