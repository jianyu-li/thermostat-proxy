"""Tests for the Thermostat Proxy state restoration."""
from unittest.mock import AsyncMock, MagicMock
import pytest

from homeassistant.core import HomeAssistant, State
from homeassistant.components.climate import HVACMode, ClimateEntityFeature

from custom_components.thermostat_proxy.climate import CustomThermostatEntity

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
    return proxy

@pytest.mark.asyncio
async def test_state_restoration(mock_hass):
    """Test restoring state on startup."""
    proxy = create_proxy(mock_hass)
    
    # Mock the restore state methods
    proxy.async_get_last_state = AsyncMock(return_value=State("climate.proxy", HVACMode.HEAT, {
        "temperature": 24.0,
        "preset_mode": "Remote",
    }))
    
    proxy._context = MagicMock()
    proxy._async_write_ha_state = MagicMock()
    proxy._schedule_target_realign = MagicMock()
    
    await proxy._async_restore_state()
    
    assert proxy._virtual_target_temperature == 24.0
    assert proxy._selected_sensor_name == "Remote"
