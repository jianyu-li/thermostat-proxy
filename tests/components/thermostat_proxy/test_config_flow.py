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
    CONF_MIN_DUAL_TEMP_SPREAD,
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
            "min_dual_temp_spread": 4.0,
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Proxy"
    assert result["data"][CONF_THERMOSTAT] == "climate.real"
    assert result["data"][CONF_SENSORS][0]["name"] == "Remote"
    assert result["data"][CONF_COOLDOWN_PERIOD] == 1800
    assert result["data"][CONF_PHYSICAL_SENSOR_NAME] == "Physical"
    assert result["data"][CONF_MIN_DUAL_TEMP_SPREAD] == 4.0


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
            "min_dual_temp_spread": 4.5,
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["cooldown_period"] == 1800
    assert result["data"]["default_sensor"] == "Remote"
    assert result["data"]["min_dual_temp_spread"] == 4.5


@pytest.mark.asyncio
async def test_user_flow_replace_sensor(hass: HomeAssistant) -> None:
    """Test replacing a sensor in the config flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Proxy", "thermostat": "climate.real"},
    )

    # Add a sensor
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"action": "add_sensor"},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Remote", "entity_id": "sensor.remote", "add_another": False},
    )
    assert result["step_id"] == "manage_sensors"

    # Replace sensor action — select target
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"action": "replace_sensor"},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "replace_sensor"

    # Select which sensor to replace
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"target_sensor": "Remote"},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "replace_sensor_details"

    # Replace sensor with new name and entity
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "New Remote",
            "entity_id": "sensor.new_remote",
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "manage_sensors"

    # Finish
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"action": "finish"},
    )
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
    assert result["data"][CONF_SENSORS][0]["name"] == "New Remote"
    assert result["data"][CONF_SENSORS][0]["entity_id"] == "sensor.new_remote"


@pytest.mark.asyncio
async def test_replace_sensor_keep_name(hass: HomeAssistant) -> None:
    """Test replacing only the entity while keeping the pre-populated name."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Proxy", "thermostat": "climate.real"},
    )

    # Add a sensor
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"action": "add_sensor"},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Remote", "entity_id": "sensor.remote", "add_another": False},
    )

    # Replace sensor — select target
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"action": "replace_sensor"},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"target_sensor": "Remote"},
    )
    assert result["step_id"] == "replace_sensor_details"

    # Submit with same name, different entity
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Remote",
            "entity_id": "sensor.kitchen",
        },
    )
    assert result["step_id"] == "manage_sensors"

    # Finish
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"action": "finish"},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "cooldown_period": 1800,
            "physical_sensor_name": "Physical",
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SENSORS][0]["name"] == "Remote"
    assert result["data"][CONF_SENSORS][0]["entity_id"] == "sensor.kitchen"

@pytest.mark.asyncio
async def test_reconfigure_flow(hass: HomeAssistant) -> None:
    """Test the reconfigure flow."""
    # Create an existing entry
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "name": "Proxy",
            "thermostat": "climate.real",
            "sensors": [{"name": "Remote", "entity_id": "sensor.remote"}],
            "default_sensor": "Remote",
        },
        unique_id="123",
    )
    entry.add_to_hass(hass)

    # Initialize the reconfigure flow
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    
    assert result["type"] == "form"
    assert result["step_id"] == "reconfigure"

    # Submit the first step
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "New Proxy", "thermostat": "climate.new_real"},
    )
    
    assert result2["type"] == "form"
    assert result2["step_id"] == "manage_sensors"
    
    # Submit manage sensors
    result3 = await hass.config_entries.flow.async_configure(
        result2["flow_id"],
        {"action": "finish"},
    )
    
    assert result3["type"] == "form"
    assert result3["step_id"] == "finalize"
    
    # Submit finalize
    result4 = await hass.config_entries.flow.async_configure(
        result3["flow_id"],
        {},
    )
    
    assert result4["type"] == "abort"
    assert result4["reason"] == "reconfigure_successful"
    
    # Check the updated entry
    assert entry.data["name"] == "New Proxy"
    assert entry.data["thermostat"] == "climate.new_real"
