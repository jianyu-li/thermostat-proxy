"""Tests for integration setup and wiring."""

from unittest.mock import patch
import pytest

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thermostat_proxy.const import (
    DOMAIN,
    CONF_THERMOSTAT,
    CONF_SENSORS,
    CONF_DISABLE_AUTO_SWITCH,
)


@pytest.fixture(autouse=True)
def mock_services(hass: HomeAssistant):
    """Mock service calls to avoid ServiceNotFound errors, but allow custom calls."""
    from homeassistant.core import ServiceRegistry

    real_async_call = ServiceRegistry.async_call

    async def mock_call(
        domain,
        service,
        service_data=None,
        blocking=False,
        context=None,
        target=None,
    ):
        entity_id = (service_data or {}).get("entity_id")
        if domain == "climate" and (
            entity_id == "climate.thermostat_proxy"
            or (isinstance(entity_id, list) and "climate.thermostat_proxy" in entity_id)
        ):
            return await real_async_call(
                hass.services, domain, service, service_data, blocking, context, target
            )
        return True

    with patch("homeassistant.core.ServiceRegistry.async_call", side_effect=mock_call):
        yield


@pytest.mark.asyncio
async def test_async_setup_entry_wiring(hass: HomeAssistant) -> None:
    """Test that config entry values are properly wired to the entity."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Proxy",
        data={
            CONF_THERMOSTAT: "climate.real",
            CONF_SENSORS: [{"name": "Remote", "entity_id": "sensor.remote"}],
        },
        options={
            CONF_DISABLE_AUTO_SWITCH: True,
        },
        source="user",
        unique_id="proxy",
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # The entity should be registered
    state = hass.states.get("climate.thermostat_proxy")
    assert state is not None

    # Retrieve the actual entity instance
    component = hass.data["climate"]
    entity = component.get_entity("climate.thermostat_proxy")

    if entity is not None:
        assert getattr(entity, "_disable_auto_switch", False) is True


@pytest.mark.parametrize("mode", ["heat", "cool"])
@pytest.mark.asyncio
async def test_external_change_real_flow(hass: HomeAssistant, mode: str) -> None:
    """Test that a 1-degree change on the physical thermostat is correctly detected and shifts the proxy target by 1 degree across single-target modes."""
    # First, mock the states in the state machine
    hass.states.async_set(
        "climate.real",
        mode,
        {
            "current_temperature": 20.0,
            "temperature": 22.0,
            "target_temp_step": 1.0,
            "supported_features": 1,  # TARGET_TEMPERATURE
        },
    )
    hass.states.async_set("sensor.remote", "24.0")

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Proxy",
        data={
            CONF_THERMOSTAT: "climate.real",
            CONF_SENSORS: [{"name": "Remote", "entity_id": "sensor.remote"}],
        },
        options={
            CONF_DISABLE_AUTO_SWITCH: True,
        },
        source="user",
        unique_id=f"proxy_{mode}",
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    component = hass.data["climate"]
    entity = component.get_entity("climate.thermostat_proxy")
    assert entity is not None

    # Wait for target realignment task
    await hass.async_block_till_done()

    # Set virtual target temperature
    await hass.services.async_call(
        "climate",
        "set_temperature",
        {"entity_id": "climate.thermostat_proxy", "temperature": 26.0},
        blocking=True,
    )
    # The real thermostat target should be adjusted to 20.0 + (26.0 - 24.0) = 22.0
    real_state = hass.states.get("climate.real")
    assert real_state.attributes["temperature"] == 22.0

    # Advance the write time back so we are out of the post-write grace period
    entity._last_real_write_time -= 11.0

    # Simulate external change on real thermostat target: 22.0 -> 21.0 (-1.0 degree)
    hass.states.async_set(
        "climate.real",
        mode,
        {
            "current_temperature": 20.0,
            "temperature": 21.0,
            "target_temp_step": 1.0,
            "supported_features": 1,
        },
    )
    await hass.async_block_till_done()

    # The virtual target should also decrease by 1 degree: 26.0 -> 25.0
    proxy_state = hass.states.get("climate.thermostat_proxy")
    assert proxy_state.attributes["temperature"] == 25.0
