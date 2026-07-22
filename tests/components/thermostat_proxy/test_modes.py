"""Tests for the Thermostat Proxy mode and overdrive logic."""

from unittest.mock import AsyncMock, MagicMock
import pytest

from homeassistant.core import HomeAssistant, State, CoreState
from homeassistant.components.climate import HVACMode, ClimateEntityFeature

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


def create_proxy(hass, thermostat="climate.real"):
    """Helper to create a configured CustomThermostatEntity."""
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

    mock_real_state = State(
        thermostat,
        HVACMode.HEAT,
        {
            "current_temperature": 22.0,
            "temperature": 22.0,
            "target_temp_step": 1.0,
            "supported_features": ClimateEntityFeature.TARGET_TEMPERATURE,
        },
    )
    hass.states.get.side_effect = lambda entity_id: (
        mock_real_state if entity_id == thermostat else None
    )
    proxy._real_state = mock_real_state
    proxy._update_real_temperature_limits()
    proxy._temperature_unit = "°C"
    proxy._sensor_states["sensor.remote"] = State("sensor.remote", "20.0")
    proxy._virtual_target_temperature = 22.0
    proxy._selected_sensor_name = "Remote"
    proxy.async_write_ha_state = MagicMock()
    return proxy


@pytest.mark.asyncio
async def test_overdrive_heat(mock_hass):
    """Test that heat overdrive is applied when physical thermostat is satisfied but remote is cold."""
    proxy = create_proxy(mock_hass)

    proxy._real_state = State(
        "climate.real",
        HVACMode.HEAT,
        {
            "current_temperature": 24.0,
            "temperature": 24.0,  # Physical is satisfied
            "hvac_action": "idle",
            "target_temp_step": 1.0,
            "supported_features": ClimateEntityFeature.TARGET_TEMPERATURE,
        },
    )

    # Virtual target = 22.0, remote = 20.0. Diff is +2.0.
    # Calculated target = 24.0 + 2.0 = 26.0.
    # Plus overdrive (1.0) = 27.0.

    await proxy._async_realign_real_target_from_sensor()

    # Verify service call
    assert mock_hass.services.async_call.called
    args, kwargs = mock_hass.services.async_call.call_args
    assert args[0] == "climate"
    assert args[1] == "set_temperature"
    assert args[2]["temperature"] == 27.0


@pytest.mark.asyncio
async def test_overdrive_cool(mock_hass):
    """Test that cool overdrive is applied when physical thermostat is satisfied but remote is hot."""
    proxy = create_proxy(mock_hass)
    proxy._real_state = State(
        "climate.real",
        HVACMode.COOL,
        {
            "current_temperature": 20.0,
            "temperature": 20.0,
            "hvac_action": "idle",
            "target_temp_step": 1.0,
            "supported_features": ClimateEntityFeature.TARGET_TEMPERATURE,
        },
    )
    proxy._virtual_target_temperature = 20.0
    proxy._sensor_states["sensor.remote"] = State("sensor.remote", "22.0")

    # Virtual target = 20.0, remote = 22.0. Diff is -2.0.
    # Calculated target = 20.0 - 2.0 = 18.0.
    # Plus overdrive (-1.0) = 17.0.

    await proxy._async_realign_real_target_from_sensor()

    assert mock_hass.services.async_call.called
    args, kwargs = mock_hass.services.async_call.call_args
    assert args[0] == "climate"
    assert args[1] == "set_temperature"
    assert args[2]["temperature"] == 17.0


@pytest.mark.asyncio
async def test_cool_mode_target_temperature_on_range_capable_thermostat(mock_hass):
    """Test that COOL mode presents single target_temperature on a dual-setpoint capable thermostat."""
    proxy = create_proxy(mock_hass)

    # Real thermostat supports dual setpoints but is currently in COOL mode
    proxy._real_state = State(
        "climate.real",
        HVACMode.COOL,
        {
            "current_temperature": 24.0,
            "temperature": 24.0,
            "target_temp_low": 20.0,
            "target_temp_high": 26.0,
            "target_temp_step": 1.0,
            "supported_features": (
                ClimateEntityFeature.TARGET_TEMPERATURE
                | ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
                | ClimateEntityFeature.PRESET_MODE
            ),
        },
    )
    proxy._update_real_temperature_limits()
    proxy._virtual_target_temperature = 22.0
    proxy._virtual_target_temperature_low = 20.0
    proxy._virtual_target_temperature_high = 26.0

    # In COOL mode, entity must report single target_temperature and None for low/high
    assert not proxy.is_range_mode
    assert proxy.target_temperature == 22.0
    assert proxy.target_temperature_low is None
    assert proxy.target_temperature_high is None

    # Setting target in COOL mode
    await proxy.async_set_temperature(temperature=21.0)

    assert mock_hass.services.async_call.called
    args, kwargs = mock_hass.services.async_call.call_args
    assert args[0] == "climate"
    assert args[1] == "set_temperature"
    assert args[2]["temperature"] == 25.0  # Real target = 24.0 + (21.0 - 20.0) = 25.0
    assert proxy.target_temperature == 21.0


@pytest.mark.asyncio
async def test_heat_mode_target_temperature_on_range_capable_thermostat(mock_hass):
    """Test that HEAT mode presents single target_temperature on a dual-setpoint capable thermostat."""
    proxy = create_proxy(mock_hass)

    proxy._real_state = State(
        "climate.real",
        HVACMode.HEAT,
        {
            "current_temperature": 20.0,
            "temperature": 20.0,
            "target_temp_low": 18.0,
            "target_temp_high": 24.0,
            "target_temp_step": 1.0,
            "supported_features": (
                ClimateEntityFeature.TARGET_TEMPERATURE
                | ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
            ),
        },
    )
    proxy._update_real_temperature_limits()
    proxy._virtual_target_temperature = 21.0
    proxy._virtual_target_temperature_low = 18.0
    proxy._virtual_target_temperature_high = 24.0

    assert not proxy.is_range_mode
    assert proxy.target_temperature == 21.0
    assert proxy.target_temperature_low is None
    assert proxy.target_temperature_high is None


@pytest.mark.asyncio
async def test_heat_cool_mode_target_temperatures(mock_hass):
    """Test that HEAT_COOL mode presents range targets and None for single target_temperature."""
    proxy = create_proxy(mock_hass)

    proxy._real_state = State(
        "climate.real",
        HVACMode.HEAT_COOL,
        {
            "current_temperature": 22.0,
            "target_temp_low": 18.0,
            "target_temp_high": 24.0,
            "target_temp_step": 1.0,
            "supported_features": (
                ClimateEntityFeature.TARGET_TEMPERATURE
                | ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
            ),
        },
    )
    proxy._update_real_temperature_limits()
    proxy._virtual_target_temperature = 21.0
    proxy._virtual_target_temperature_low = 18.0
    proxy._virtual_target_temperature_high = 24.0

    assert proxy.is_range_mode
    assert proxy.target_temperature is None
    assert proxy.target_temperature_low == 18.0
    assert proxy.target_temperature_high == 24.0


@pytest.mark.asyncio
async def test_mode_transition_target_sync(mock_hass):
    """Test that switching from HEAT_COOL to COOL adopts high setpoint and from HEAT_COOL to HEAT adopts low setpoint."""
    proxy = create_proxy(mock_hass)

    # Initial state: HEAT_COOL mode with low=18.0, high=24.0, stale virtual_target=15.0
    old_state = State("climate.real", HVACMode.HEAT_COOL, {"temperature": None})
    new_state = State("climate.real", HVACMode.COOL, {"temperature": 24.0})
    event = MagicMock()
    event.data = {"old_state": old_state, "new_state": new_state}

    proxy._virtual_target_temperature = 15.0  # stale value
    proxy._virtual_target_temperature_low = 18.0
    proxy._virtual_target_temperature_high = 24.0

    proxy._async_handle_real_state_event(event)

    # Switching to COOL must adopt high target (24.0), not stale target (15.0)
    assert proxy._virtual_target_temperature == 24.0


@pytest.mark.asyncio
async def test_mode_change_suppresses_external_target_change(mock_hass):
    """Test that a mode change on the physical thermostat does not trigger false external change detection."""
    proxy = create_proxy(mock_hass)

    proxy._selected_sensor_name = "Remote"
    proxy._last_real_target_temp = 22.0  # target in HEAT mode

    # Real thermostat transitions from HEAT (22.0) to COOL (18.0)
    old_state = State("climate.real", HVACMode.HEAT, {"temperature": 22.0})
    new_state = State("climate.real", HVACMode.COOL, {"temperature": 18.0})
    event = MagicMock()
    event.data = {"old_state": old_state, "new_state": new_state}

    proxy._async_handle_real_state_event(event)

    # Should NOT switch preset to Physical due to false external change
    assert proxy._selected_sensor_name == "Remote"
    # Last real target updated to new mode's setpoint (18.0)
    assert proxy._last_real_target_temp == 18.0
