"""Tests for Thermostat Proxy dual setpoint mode (HEAT_COOL and AUTO)."""

from unittest.mock import AsyncMock, MagicMock
import pytest

from homeassistant.core import HomeAssistant, State, CoreState
from homeassistant.components.climate import HVACMode, ClimateEntityFeature, HVACAction

from custom_components.thermostat_proxy.climate import CustomThermostatEntity


@pytest.fixture
def mock_hass():
    """Mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.state = CoreState.running
    hass.data = {}
    hass.states = MagicMock()
    hass.config = MagicMock()
    hass.config.units.temperature_unit = "°C"
    hass.services = AsyncMock()
    hass.async_create_task.side_effect = lambda coro: coro.close()
    return hass


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

    mock_real_state = State(
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
    hass.states.get.side_effect = lambda entity_id: (
        mock_real_state if entity_id == thermostat else None
    )
    proxy._real_state = mock_real_state
    proxy._update_real_temperature_limits()
    proxy._temperature_unit = "°C"
    proxy._sensor_states["sensor.remote"] = State("sensor.remote", "18.0")
    proxy._virtual_target_temperature_low = 18.0
    proxy._virtual_target_temperature_high = 24.0
    proxy._selected_sensor_name = "Remote"
    return proxy


@pytest.mark.parametrize("hvac_mode", [HVACMode.HEAT_COOL, HVACMode.AUTO])
@pytest.mark.asyncio
async def test_dual_setpoint_preset_mode_switch(mock_hass, hvac_mode):
    """Test switching preset mode in range modes (HEAT_COOL / AUTO)."""
    proxy = create_dual_proxy(mock_hass, hvac_mode=hvac_mode)

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
async def test_dual_setpoint_set_temperature(mock_hass, hvac_mode):
    """Test set_temperature with low and high targets across range modes."""
    proxy = create_dual_proxy(mock_hass, hvac_mode=hvac_mode)

    # Physical current = 20.0, Remote sensor = 18.0 (diff = +2.0)
    # Requested remote range: low = 19.0, high = 25.0
    # Expected real target: low = 21.0, high = 27.0
    await proxy.async_set_temperature(target_temp_low=19.0, target_temp_high=25.0)

    assert mock_hass.services.async_call.called
    args, kwargs = mock_hass.services.async_call.call_args
    assert args[0] == "climate"
    assert args[1] == "set_temperature"
    assert args[2]["target_temp_low"] == 21.0
    assert args[2]["target_temp_high"] == 27.0
    assert proxy.target_temperature_low == 19.0
    assert proxy.target_temperature_high == 25.0


@pytest.mark.asyncio
async def test_dual_setpoint_realignment(mock_hass):
    """Test remote sensor realignment in dual setpoint mode."""
    proxy = create_dual_proxy(mock_hass)

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

    assert mock_hass.services.async_call.called
    args, kwargs = mock_hass.services.async_call.call_args
    assert args[0] == "climate"
    assert args[1] == "set_temperature"
    assert args[2]["target_temp_low"] == 22.0
    assert args[2]["target_temp_high"] == 28.0


@pytest.mark.asyncio
async def test_dual_setpoint_overdrive_heat(mock_hass):
    """Test heat overdrive in dual setpoint mode when remote is cold and system is idle."""
    proxy = create_dual_proxy(mock_hass)

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

    assert mock_hass.services.async_call.called
    args, kwargs = mock_hass.services.async_call.call_args
    assert args[0] == "climate"
    assert args[1] == "set_temperature"
    assert args[2]["target_temp_low"] == 23.0


@pytest.mark.asyncio
async def test_dual_setpoint_overdrive_cool(mock_hass):
    """Test cool overdrive in dual setpoint mode when remote is hot and system is idle."""
    proxy = create_dual_proxy(mock_hass)

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

    assert mock_hass.services.async_call.called
    args, kwargs = mock_hass.services.async_call.call_args
    assert args[0] == "climate"
    assert args[1] == "set_temperature"
    assert args[2]["target_temp_high"] == 17.0


@pytest.mark.asyncio
async def test_dual_setpoint_partial_set_temperature(mock_hass):
    """Test setting only low or high temperature in dual setpoint mode."""
    proxy = create_dual_proxy(mock_hass)

    # Only setting low
    await proxy.async_set_temperature(target_temp_low=19.0)

    assert mock_hass.services.async_call.called
    args, kwargs = mock_hass.services.async_call.call_args
    assert args[0] == "climate"
    assert args[1] == "set_temperature"
    assert args[2]["target_temp_low"] == 21.0
    assert "target_temp_high" not in args[2]
    assert proxy.target_temperature_low == 19.0


@pytest.mark.asyncio
async def test_dual_setpoint_service_error_handling(mock_hass):
    """Test error handling during dual setpoint realignment."""
    proxy = create_dual_proxy(mock_hass)

    proxy._sensor_states["sensor.remote"] = State("sensor.remote", "16.0")

    async def side_effect(domain, service, service_data, blocking=False):
        if domain == "climate":
            raise Exception("502 Bad Gateway")

    mock_hass.services.async_call.side_effect = side_effect

    # Should handle error gracefully without raising
    await proxy._async_realign_real_target_from_sensor()
