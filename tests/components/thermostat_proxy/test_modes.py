"""Tests for the Thermostat Proxy mode and overdrive logic."""
from unittest.mock import AsyncMock, MagicMock
import pytest

from homeassistant.core import HomeAssistant, State
from homeassistant.components.climate import HVACMode, ClimateEntityFeature
from homeassistant.const import ATTR_TEMPERATURE

from custom_components.thermostat_proxy.climate import CustomThermostatEntity
from custom_components.thermostat_proxy.const import OVERDRIVE_ADJUSTMENT_HEAT, OVERDRIVE_ADJUSTMENT_COOL

@pytest.fixture
def mock_hass():
    """Mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.states = MagicMock()
    hass.config = MagicMock()
    hass.config.units.temperature_unit = "°C"
    hass.services = AsyncMock()
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
        }
    )
    hass.states.get.side_effect = lambda entity_id: mock_real_state if entity_id == thermostat else None
    proxy._real_state = mock_real_state
    proxy._update_real_temperature_limits()
    proxy._temperature_unit = "°C"
    proxy._sensor_states["sensor.remote"] = State("sensor.remote", "20.0")
    proxy._virtual_target_temperature = 22.0
    proxy._selected_sensor_name = "Remote"
    return proxy

@pytest.mark.asyncio
async def test_overdrive_heat(mock_hass):
    """Test that heat overdrive is applied when physical thermostat is satisfied but remote is cold."""
    proxy = create_proxy(mock_hass)
    
    proxy._real_state = State("climate.real", HVACMode.HEAT, {
        "current_temperature": 24.0,
        "temperature": 24.0, # Physical is satisfied
        "hvac_action": "idle",
        "target_temp_step": 1.0,
        "supported_features": ClimateEntityFeature.TARGET_TEMPERATURE,
    })
    
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
    proxy._real_state = State("climate.real", HVACMode.COOL, {
        "current_temperature": 20.0,
        "temperature": 20.0,
        "hvac_action": "idle",
        "target_temp_step": 1.0,
        "supported_features": ClimateEntityFeature.TARGET_TEMPERATURE,
    })
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
