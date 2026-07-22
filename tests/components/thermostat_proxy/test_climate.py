"""Tests for the Thermostat Proxy climate platform."""

from unittest.mock import AsyncMock, MagicMock
import pytest

from homeassistant.core import HomeAssistant, State
from homeassistant.components.climate import ClimateEntityFeature, HVACMode
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


def create_proxy(hass, thermostat="climate.real", sensors=None, target_temp_step=1.0):
    """Helper to create a configured CustomThermostatEntity."""
    if sensors is None:
        sensors = [{"name": "Sensor 1", "entity_id": "sensor.1"}]

    proxy = CustomThermostatEntity(
        hass=hass,
        name="Test Proxy",
        real_thermostat=thermostat,
        sensors=sensors,
        default_sensor="Sensor 1",
        unique_id="123",
        physical_sensor_name="Physical",
        use_last_active_sensor=False,
    )

    # Mock physical thermostat state
    mock_real_state = State(
        thermostat,
        HVACMode.HEAT,
        {
            "current_temperature": 20.0,
            "temperature": 22.0,
            "target_temp_step": target_temp_step,
            "supported_features": ClimateEntityFeature.TARGET_TEMPERATURE,
        },
    )
    hass.states.get.side_effect = lambda entity_id: (
        mock_real_state if entity_id == thermostat else None
    )
    proxy._real_state = mock_real_state
    proxy._update_real_temperature_limits()

    return proxy


@pytest.mark.asyncio
async def test_infer_sensor_precision(mock_hass):
    """Test inference of sensor precision from state string."""
    proxy = create_proxy(mock_hass)

    assert proxy._infer_sensor_precision(State("sensor.1", "22.8")) == 0.1
    assert proxy._infer_sensor_precision(State("sensor.1", "22.85")) == 0.01
    assert proxy._infer_sensor_precision(State("sensor.1", "22.0")) == 0.1
    assert proxy._infer_sensor_precision(State("sensor.1", "22")) == 1.0
    assert (
        proxy._infer_sensor_precision(State("sensor.1", "unknown")) == 0.1
    )  # DEFAULT_PRECISION


@pytest.mark.asyncio
async def test_effective_precision_coarsest_wins(mock_hass):
    """Test that precision and target_temp_step use the coarsest available."""
    proxy = create_proxy(mock_hass, target_temp_step=0.5)

    # Sensor 1 reports 1.0 precision
    mock_hass.states.get.side_effect = lambda entity_id: (
        State(entity_id, "22") if entity_id == "sensor.1" else proxy._real_state
    )

    proxy._sensor_states["sensor.1"] = State("sensor.1", "22")
    proxy._sensor_precisions["sensor.1"] = proxy._infer_sensor_precision(
        State("sensor.1", "22")
    )
    proxy._selected_sensor_name = "Sensor 1"

    # Thermostat is 0.5, Sensor is 1.0 -> Effective is 1.0
    assert proxy.precision == 1.0
    assert proxy.target_temperature_step == 1.0

    # Switch to high precision sensor
    proxy._sensor_states["sensor.1"] = State("sensor.1", "22.85")
    proxy._sensor_precisions["sensor.1"] = proxy._infer_sensor_precision(
        State("sensor.1", "22.85")
    )

    # Thermostat is 0.5, Sensor is 0.01 -> Display precision is 0.01, target step is 0.5
    assert proxy.precision == 0.01
    assert proxy.target_temperature_step == 0.5


@pytest.mark.asyncio
async def test_log_formatting_preserves_decimals(mock_hass):
    """Test that math formatting methods preserve exactly one decimal place."""
    proxy = create_proxy(mock_hass)
    proxy._precision_override = 0.5

    # Output should always have .1f
    res = proxy._format_math_sensor_virtual(22.0, 20.0, "°C")
    assert res == "22.0°C - 20.0°C = 2.0°C"

    res = proxy._format_math_real_adjustment(
        25.0, 22.5, 20.0, 27.5, "°C", overdrive_adjust=1.0
    )
    assert res == "25.0°C - 2.5°C (+1.0 overdrive) = 27.5°C"


@pytest.mark.asyncio
async def test_pending_request_tolerance_covers_step(mock_hass):
    """Test that _pending_request_tolerance does not incorrectly incorporate target_temp_step to avoid ignoring manual changes."""
    proxy = create_proxy(mock_hass, target_temp_step=0.5)
    proxy._sensor_precisions["sensor.1"] = 0.5
    # With 0.5 precision, precision / 2 is 0.25.
    # It should not use step (0.5), so tolerance should be 0.25.
    tolerance = proxy._pending_request_tolerance()
    assert tolerance == 0.25
