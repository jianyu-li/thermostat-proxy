"""Tests for the disable_auto_switch configuration."""
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
    hass.data = {}
    hass.config = MagicMock()
    hass.config.units.temperature_unit = "°C"
    hass.services = AsyncMock()
    hass.async_create_task.side_effect = lambda coro: coro.close()
    return hass


def create_proxy(hass, disable_auto_switch=False):
    """Helper to create a configured CustomThermostatEntity."""
    proxy = CustomThermostatEntity(
        hass=hass,
        name="Test Proxy",
        real_thermostat="climate.real",
        sensors=[{"name": "Remote", "entity_id": "sensor.remote"}],
        default_sensor="Remote",
        unique_id="123",
        physical_sensor_name="Physical",
        use_last_active_sensor=False,
        disable_auto_switch=disable_auto_switch,
    )
    
    # Mock physical thermostat state
    mock_real_state = State(
        "climate.real",
        HVACMode.HEAT,
        {
            "current_temperature": 20.0,
            "temperature": 22.0,
            "target_temp_step": 1.0,
            "supported_features": ClimateEntityFeature.TARGET_TEMPERATURE,
        }
    )
    hass.states.get.side_effect = lambda entity_id: mock_real_state if entity_id == "climate.real" else None
    proxy._real_state = mock_real_state
    proxy._update_real_temperature_limits()
    
    proxy._temperature_unit = "°C"
    proxy._sensor_states["sensor.remote"] = State("sensor.remote", "24.0")
    proxy._virtual_target_temperature = 26.0
    proxy._selected_sensor_name = "Remote"
    proxy._last_real_target_temp = 22.0
    proxy.async_write_ha_state = MagicMock()
    return proxy


@pytest.mark.asyncio
async def test_auto_switch_enabled(mock_hass):
    """Test that proxy switches to physical sensor when external change is detected (default)."""
    proxy = create_proxy(mock_hass, disable_auto_switch=False)
    
    # Simulate an external change (real target changes to 23.0, previous was 22.0)
    proxy._handle_external_real_target_change(23.0, 22.0)
    
    # Should switch to the physical sensor
    assert proxy._selected_sensor_name == "Physical"
    # Virtual target should become the real target
    assert proxy._virtual_target_temperature == 23.0


@pytest.mark.asyncio
async def test_auto_switch_disabled(mock_hass):
    """Test that proxy maintains sensor and updates virtual target when auto-switch is disabled."""
    proxy = create_proxy(mock_hass, disable_auto_switch=True)
    
    # Current state: 
    # Sensor temp = 24.0
    # Real current = 20.0
    # Virtual target = 26.0
    # Real target was = 22.0
    
    # Simulate an external change (real target changes to 24.0, previous was 22.0)
    proxy._handle_external_real_target_change(24.0, 22.0)
    
    # Should NOT switch to the physical sensor
    assert proxy._selected_sensor_name == "Remote"
    
    # Virtual target should be updated by the delta: 26.0 + (24.0 - 22.0) = 28.0
    assert proxy._virtual_target_temperature == 28.0
