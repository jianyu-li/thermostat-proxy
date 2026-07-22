"""Test the Thermostat Proxy config flow."""

from unittest.mock import patch
import pytest

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thermostat_proxy.const import (
    DOMAIN,
    CONF_THERMOSTAT,
    CONF_SENSORS,
    CONF_PHYSICAL_SENSOR_NAME,
    CONF_COOLDOWN_PERIOD,
)


@pytest.fixture(autouse=True)
def mock_services():
    """Mock service calls to avoid ServiceNotFound errors."""
    with patch("homeassistant.core.ServiceRegistry.async_call", return_value=True):
        yield


@pytest.mark.asyncio
async def test_user_flow_success(hass: HomeAssistant) -> None:
    """Test the full user setup flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Proxy", "thermostat": "climate.real"},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "manage_sensors"

    # Add a sensor
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"action": "add_sensor"},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "sensors"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Remote", "entity_id": "sensor.remote", "add_another": False},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "manage_sensors"

    # Finish
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"action": "finish"},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "finalize"

    # Finalize
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "cooldown_period": 1800,
            "physical_sensor_name": "Physical",
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Proxy"
    assert result["data"][CONF_THERMOSTAT] == "climate.real"
    assert result["data"][CONF_SENSORS][0]["name"] == "Remote"
    assert result["data"][CONF_COOLDOWN_PERIOD] == 1800
    assert result["data"][CONF_PHYSICAL_SENSOR_NAME] == "Physical"


@pytest.mark.asyncio
async def test_options_flow(hass: HomeAssistant) -> None:
    """Test updating options."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Proxy",
        data={
            CONF_THERMOSTAT: "climate.real",
            CONF_SENSORS: [{"name": "Remote", "entity_id": "sensor.remote"}],
        },
        source="user",
        unique_id="proxy",
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "cooldown_period": 1800,
            "default_sensor": "Remote",
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["cooldown_period"] == 1800
    assert result["data"]["default_sensor"] == "Remote"
