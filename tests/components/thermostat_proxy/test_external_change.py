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


def create_proxy(hass, disable_auto_switch=False, hvac_mode=HVACMode.HEAT):
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

    supported = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
        | ClimateEntityFeature.PRESET_MODE
    )

    mock_real_state = State(
        "climate.real",
        hvac_mode,
        {
            "current_temperature": 20.0,
            "temperature": 22.0,
            "target_temp_low": 18.0,
            "target_temp_high": 24.0,
            "target_temp_step": 1.0,
            "supported_features": supported,
        },
    )
    hass.states.get.side_effect = lambda entity_id: (
        mock_real_state if entity_id == "climate.real" else None
    )
    proxy._real_state = mock_real_state
    proxy._update_real_temperature_limits()

    proxy._temperature_unit = "°C"
    proxy._sensor_states["sensor.remote"] = State("sensor.remote", "24.0")
    proxy._virtual_target_temperature = 26.0
    proxy._virtual_target_temperature_low = 18.0
    proxy._virtual_target_temperature_high = 24.0
    proxy._selected_sensor_name = "Remote"
    proxy._last_real_target_temp = 22.0
    proxy._last_real_target_temp_low = 18.0
    proxy._last_real_target_temp_high = 24.0
    proxy.async_write_ha_state = MagicMock()
    return proxy


@pytest.mark.parametrize(
    "hvac_mode", [HVACMode.HEAT, HVACMode.COOL, HVACMode.HEAT_COOL, HVACMode.AUTO]
)
@pytest.mark.asyncio
async def test_auto_switch_enabled(mock_hass, hvac_mode):
    """Test that proxy switches to physical sensor when external change is detected in all modes."""
    proxy = create_proxy(mock_hass, disable_auto_switch=False, hvac_mode=hvac_mode)

    if hvac_mode in (HVACMode.HEAT_COOL, HVACMode.AUTO):
        proxy._detect_external_dual_target_change(19.0, 24.0, was_not_controlling=False)
        assert proxy._selected_sensor_name == "Physical"
        assert proxy._virtual_target_temperature_low == 19.0
    else:
        proxy._handle_external_real_target_change(23.0, 22.0)
        assert proxy._selected_sensor_name == "Physical"
        assert proxy._virtual_target_temperature == 23.0


@pytest.mark.parametrize(
    "hvac_mode", [HVACMode.HEAT, HVACMode.COOL, HVACMode.HEAT_COOL, HVACMode.AUTO]
)
@pytest.mark.asyncio
async def test_auto_switch_disabled(mock_hass, hvac_mode):
    """Test that proxy maintains sensor and updates virtual targets when auto-switch is disabled across all modes."""
    proxy = create_proxy(mock_hass, disable_auto_switch=True, hvac_mode=hvac_mode)

    if hvac_mode in (HVACMode.HEAT_COOL, HVACMode.AUTO):
        proxy._detect_external_dual_target_change(20.0, 24.0, was_not_controlling=False)
        assert proxy._selected_sensor_name == "Remote"
        # Real low changed +2.0 (18.0 -> 20.0), virtual low 18.0 + 2.0 = 20.0
        assert proxy._virtual_target_temperature_low == 20.0
    else:
        proxy._handle_external_real_target_change(24.0, 22.0)
        assert proxy._selected_sensor_name == "Remote"
        # Virtual target updated by delta: 26.0 + (24.0 - 22.0) = 28.0
        assert proxy._virtual_target_temperature == 28.0


@pytest.mark.asyncio
async def test_external_change_updates_last_real_write_time(mock_hass):
    """Test that handling an external change when auto-switch is disabled updates _last_real_write_time."""
    proxy = create_proxy(mock_hass, disable_auto_switch=True, hvac_mode=HVACMode.COOL)
    initial_write_time = proxy._last_real_write_time

    proxy._handle_external_real_target_change(21.0, 22.0)

    assert proxy._virtual_target_temperature == 25.0
    assert proxy._last_real_write_time > initial_write_time


@pytest.mark.asyncio
async def test_disable_auto_switch_logbook_math(mock_hass):
    """Test logbook message formatting for external changes when disable_auto_switch is enabled."""
    proxy = create_proxy(mock_hass, disable_auto_switch=True, hvac_mode=HVACMode.HEAT)
    proxy.entity_id = "climate.custom_thermostat"
    proxy.name = "Custom Thermostat"

    await proxy._async_log_virtual_target_sync(
        virtual_target=25.0, real_target=21.0, previous_real_target=22.0
    )

    mock_hass.services.async_call.assert_called_once()
    call_args = mock_hass.services.async_call.call_args[0]
    domain, service, data = call_args
    assert domain == "logbook"
    assert "26.0°C - 1.0°C = 25.0°C" in data["message"] or "virtual_target=25.0°C" in data["message"]

