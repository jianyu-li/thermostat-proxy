"""Tests simulating scenarios in GitHub issues #31 and #32."""

import time
from unittest.mock import MagicMock
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
    hass.services = MagicMock()
    hass.async_create_task = MagicMock(side_effect=lambda coro, *a, **kw: coro.close())
    return hass


@pytest.mark.parametrize(
    "hvac_mode", [HVACMode.HEAT, HVACMode.COOL, HVACMode.HEAT_COOL, HVACMode.AUTO]
)
@pytest.mark.asyncio
async def test_issue_31_decimal_current_temperature(mock_hass, hvac_mode):
    """Test that a remote sensor with decimals displays decimals for current temperature across all modes."""
    proxy = CustomThermostatEntity(
        hass=mock_hass,
        name="Test Proxy",
        real_thermostat="climate.real",
        sensors=[{"name": "Remote", "entity_id": "sensor.remote"}],
        default_sensor="Remote",
        unique_id="123",
        physical_sensor_name="Physical",
        use_last_active_sensor=False,
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
            "supported_features": (
                ClimateEntityFeature.TARGET_TEMPERATURE
                | ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
            ),
        },
    )
    mock_hass.states.get.side_effect = lambda entity_id: (
        mock_real_state if entity_id == "climate.real" else None
    )
    proxy._real_state = mock_real_state
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
async def test_issue_32_floor_rounding_thermostat_loop(mock_hass, hvac_mode):
    """Test floor-rounding external change suppression across all HVAC modes."""
    proxy = CustomThermostatEntity(
        hass=mock_hass,
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
    mock_real_state = State(
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
    mock_hass.states.get.side_effect = lambda entity_id: (
        mock_real_state if entity_id == "climate.real" else None
    )
    proxy._real_state = mock_real_state
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
