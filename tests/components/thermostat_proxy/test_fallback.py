"""Tests for the Thermostat Proxy fallback behavior."""

from unittest.mock import AsyncMock, MagicMock
import pytest

from homeassistant.core import HomeAssistant, State, CoreState
from homeassistant.components.climate import HVACMode, ClimateEntityFeature
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN

from custom_components.thermostat_proxy.climate import CustomThermostatEntity


@pytest.fixture
def mock_hass():
    """Mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.state = CoreState.running
    hass.states = MagicMock()
    hass.config = MagicMock()
    hass.config.units.temperature_unit = "°C"
    hass.services = AsyncMock()
    hass.async_create_task.side_effect = lambda coro: coro.close()
    return hass


def create_proxy(hass, thermostat="climate.real", hvac_mode=HVACMode.HEAT):
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

    supported = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
        | ClimateEntityFeature.PRESET_MODE
    )

    mock_real_state = State(
        thermostat,
        hvac_mode,
        {
            "current_temperature": 22.0,
            "temperature": 22.0,
            "target_temp_low": 18.0,
            "target_temp_high": 24.0,
            "target_temp_step": 1.0,
            "supported_features": supported,
        },
    )
    hass.states.get.side_effect = lambda entity_id: (
        mock_real_state if entity_id == thermostat else None
    )
    proxy._real_state = mock_real_state
    proxy._update_real_temperature_limits()
    proxy._temperature_unit = "°C"
    proxy._virtual_target_temperature = 22.0
    proxy._virtual_target_temperature_low = 18.0
    proxy._virtual_target_temperature_high = 24.0
    proxy._selected_sensor_name = "Remote"
    proxy._sensor_states["sensor.remote"] = State("sensor.remote", "20.0")
    return proxy


@pytest.mark.parametrize(
    "hvac_mode", [HVACMode.HEAT, HVACMode.COOL, HVACMode.HEAT_COOL, HVACMode.AUTO]
)
@pytest.mark.asyncio
async def test_remote_sensor_unavailable(mock_hass, hvac_mode):
    """Test fallback when remote sensor is unavailable across all modes."""
    proxy = create_proxy(mock_hass, hvac_mode=hvac_mode)

    # Normally, current temp is 20 (remote)
    assert proxy.current_temperature == 20.0

    proxy._sensor_states["sensor.remote"] = State("sensor.remote", STATE_UNAVAILABLE)

    # Fallback to physical (22.0)
    assert proxy.current_temperature == 22.0


@pytest.mark.parametrize(
    "hvac_mode", [HVACMode.HEAT, HVACMode.COOL, HVACMode.HEAT_COOL, HVACMode.AUTO]
)
@pytest.mark.asyncio
async def test_remote_sensor_unknown(mock_hass, hvac_mode):
    """Test fallback when remote sensor is unknown across all modes."""
    proxy = create_proxy(mock_hass, hvac_mode=hvac_mode)

    assert proxy.current_temperature == 20.0

    proxy._sensor_states["sensor.remote"] = State("sensor.remote", STATE_UNKNOWN)

    # Fallback to physical (22.0)
    assert proxy.current_temperature == 22.0
