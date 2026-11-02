"""Tests for swing passthrough."""

import pytest

from custom_components.thermostat_proxy.climate import CustomThermostatEntity
from homeassistant.components.climate import ClimateEntityFeature, HVACMode


def create_proxy(hass):
    """Return a proxy wrapping a swing-capable climate entity."""
    hass.states.async_set(
        "climate.real",
        HVACMode.COOL,
        {
            "current_temperature": 24.0,
            "temperature": 23.0,
            "target_temp_step": 0.5,
            "supported_features": (
                ClimateEntityFeature.TARGET_TEMPERATURE
                | ClimateEntityFeature.SWING_MODE
                | ClimateEntityFeature.SWING_HORIZONTAL_MODE
            ),
            "swing_mode": "stop",
            "swing_modes": ["stop", "swing"],
            "swing_horizontal_mode": "stop",
            "swing_horizontal_modes": ["stop", "swing"],
        },
    )
    proxy = CustomThermostatEntity(
        hass=hass,
        name="Test Proxy",
        real_thermostat="climate.real",
        sensors=[{"name": "Remote", "entity_id": "sensor.remote"}],
        default_sensor="Remote",
        unique_id="123",
        physical_sensor_name="Physical",
        use_last_active_sensor=False,
    )
    proxy._real_state = hass.states.get("climate.real")
    proxy._update_real_temperature_limits()
    return proxy


@pytest.mark.asyncio
async def test_swing_features_and_state_are_forwarded(hass):
    """Expose the physical entity's swing capabilities and state."""
    proxy = create_proxy(hass)

    assert proxy.supported_features & ClimateEntityFeature.SWING_MODE
    assert proxy.supported_features & ClimateEntityFeature.SWING_HORIZONTAL_MODE
    assert proxy.swing_mode == "stop"
    assert proxy.swing_modes == ["stop", "swing"]
    assert proxy.swing_horizontal_mode == "stop"
    assert proxy.swing_horizontal_modes == ["stop", "swing"]


@pytest.mark.asyncio
async def test_vertical_swing_is_forwarded(hass):
    """Forward vertical swing commands to the physical entity."""
    proxy = create_proxy(hass)

    await proxy.async_set_swing_mode("swing")

    hass.services.async_call.assert_awaited_with(
        "climate",
        "set_swing_mode",
        {"entity_id": "climate.real", "swing_mode": "swing"},
        blocking=True,
    )


@pytest.mark.asyncio
async def test_horizontal_swing_is_forwarded(hass):
    """Forward horizontal swing commands to the physical entity."""
    proxy = create_proxy(hass)

    await proxy.async_set_swing_horizontal_mode("swing")

    hass.services.async_call.assert_awaited_with(
        "climate",
        "set_swing_horizontal_mode",
        {
            "entity_id": "climate.real",
            "swing_horizontal_mode": "swing",
        },
        blocking=True,
    )
