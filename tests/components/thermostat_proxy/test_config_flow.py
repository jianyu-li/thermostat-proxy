"""Test the Thermostat Proxy config flow."""

from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thermostat_proxy.config_flow import (
    _extract_entry_runtime_settings,
    _parse_and_validate_runtime_input,
    _target_change_behavior_from_flags,
    _target_change_flags_from_behavior,
    _validate_sensor_submission,
)
from custom_components.thermostat_proxy.const import (
    CONF_COOLDOWN_PERIOD,
    CONF_DEFAULT_SENSOR,
    CONF_DISABLE_AUTO_SWITCH,
    CONF_MAX_TEMP,
    CONF_MIN_DUAL_TEMP_SPREAD,
    CONF_MIN_TEMP,
    CONF_OVERDRIVE_OFFSET,
    CONF_PHYSICAL_SENSOR_NAME,
    CONF_PHYSICAL_TARGET_CHANGE_BEHAVIOR,
    CONF_PRESERVE_VIRTUAL_TARGET,
    CONF_SENSORS,
    CONF_THERMOSTAT,
    DEFAULT_SENSOR_LAST_ACTIVE,
    DOMAIN,
    TARGET_CHANGE_BEHAVIOR_AUTO_SWITCH,
    TARGET_CHANGE_BEHAVIOR_DISABLE_AUTO_SWITCH,
    TARGET_CHANGE_BEHAVIOR_PRESERVE_VIRTUAL_TARGET,
)
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType


@pytest.fixture(autouse=True)
def mock_services():
    """Mock service calls to avoid ServiceNotFound errors."""
    with patch("homeassistant.core.ServiceRegistry.async_call", return_value=True):
        yield


@pytest.mark.parametrize(
    (
        "disable_auto_switch",
        "preserve_virtual_target",
        "behavior",
        "mapped_flags",
    ),
    [
        (False, False, TARGET_CHANGE_BEHAVIOR_AUTO_SWITCH, (False, False)),
        (False, True, TARGET_CHANGE_BEHAVIOR_AUTO_SWITCH, (False, False)),
        (True, False, TARGET_CHANGE_BEHAVIOR_DISABLE_AUTO_SWITCH, (True, False)),
        (True, True, TARGET_CHANGE_BEHAVIOR_PRESERVE_VIRTUAL_TARGET, (True, True)),
    ],
)
def test_target_change_behavior_legacy_mapping(
    disable_auto_switch: bool,
    preserve_virtual_target: bool,
    behavior: str,
    mapped_flags: tuple[bool, bool],
) -> None:
    """Test mapping between the UI behavior and legacy settings."""
    assert (
        _target_change_behavior_from_flags(disable_auto_switch, preserve_virtual_target)
        == behavior
    )
    assert _target_change_flags_from_behavior(behavior) == mapped_flags


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
            CONF_OVERDRIVE_OFFSET: 0.5,
            CONF_PHYSICAL_TARGET_CHANGE_BEHAVIOR: (
                TARGET_CHANGE_BEHAVIOR_PRESERVE_VIRTUAL_TARGET
            ),
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Proxy"
    assert result["data"][CONF_THERMOSTAT] == "climate.real"
    assert result["data"][CONF_SENSORS][0]["name"] == "Remote"
    assert result["data"][CONF_COOLDOWN_PERIOD] == 1800
    assert result["data"][CONF_PHYSICAL_SENSOR_NAME] == "Physical"
    assert result["data"][CONF_MIN_DUAL_TEMP_SPREAD] == 4.0
    assert result["data"][CONF_OVERDRIVE_OFFSET] == 0.5
    assert result["data"]["disable_auto_switch"] is True
    assert result["data"]["preserve_virtual_target"] is True


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
            CONF_OVERDRIVE_OFFSET: 0.5,
            CONF_PHYSICAL_TARGET_CHANGE_BEHAVIOR: (
                TARGET_CHANGE_BEHAVIOR_PRESERVE_VIRTUAL_TARGET
            ),
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["cooldown_period"] == 1800
    assert result["data"]["default_sensor"] == "Remote"
    assert result["data"]["min_dual_temp_spread"] == 4.5
    assert result["data"][CONF_OVERDRIVE_OFFSET] == 0.5
    assert result["data"]["disable_auto_switch"] is True
    assert result["data"]["preserve_virtual_target"] is True


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
            CONF_DISABLE_AUTO_SWITCH: False,
            CONF_PRESERVE_VIRTUAL_TARGET: False,
        },
        options={
            CONF_DISABLE_AUTO_SWITCH: True,
            CONF_PRESERVE_VIRTUAL_TARGET: True,
        },
        unique_id="123",
    )
    entry.add_to_hass(hass)

    # Initialize the reconfigure flow
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
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
    assert entry.data[CONF_DISABLE_AUTO_SWITCH] is True
    assert entry.data[CONF_PRESERVE_VIRTUAL_TARGET] is True
    assert entry.options[CONF_DISABLE_AUTO_SWITCH] is True
    assert entry.options[CONF_PRESERVE_VIRTUAL_TARGET] is True


@pytest.mark.asyncio
async def test_reconfigure_flow_preserves_options_overrides(
    hass: HomeAssistant,
) -> None:
    """Test that reconfigure flow preserves runtime settings overridden in options."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "name": "Proxy",
            "thermostat": "climate.real",
            CONF_SENSORS: [
                {"name": "Remote 1", "entity_id": "sensor.remote1"},
                {"name": "Remote 2", "entity_id": "sensor.remote2"},
            ],
            CONF_DEFAULT_SENSOR: "Remote 1",
            CONF_COOLDOWN_PERIOD: 300,
            CONF_MIN_TEMP: 15.0,
            CONF_MAX_TEMP: 25.0,
            CONF_OVERDRIVE_OFFSET: 1.0,
        },
        options={
            CONF_DEFAULT_SENSOR: "Remote 2",
            CONF_COOLDOWN_PERIOD: 1800,
            CONF_MIN_TEMP: 18.0,
            CONF_MAX_TEMP: 28.0,
            CONF_OVERDRIVE_OFFSET: 2.5,
        },
        unique_id="12345",
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Proxy", "thermostat": "climate.real"},
    )
    assert result2["type"] == FlowResultType.FORM
    assert result2["step_id"] == "manage_sensors"

    result3 = await hass.config_entries.flow.async_configure(
        result2["flow_id"],
        {"action": "finish"},
    )
    assert result3["type"] == FlowResultType.FORM
    assert result3["step_id"] == "finalize"

    # Verify that the schema presented to the user has options values as defaults
    schema_defaults = {
        marker.schema: marker.default()
        for marker in result3["data_schema"].schema
        if hasattr(marker, "default") and callable(marker.default)
    }
    assert schema_defaults[CONF_DEFAULT_SENSOR] == "Remote 2"
    assert schema_defaults[CONF_COOLDOWN_PERIOD] == 1800
    assert schema_defaults[CONF_MIN_TEMP] == 18.0
    assert schema_defaults[CONF_MAX_TEMP] == 28.0
    assert schema_defaults[CONF_OVERDRIVE_OFFSET] == 2.5

    # Submitting finalize without overriding any values preserves options overrides
    result4 = await hass.config_entries.flow.async_configure(
        result3["flow_id"],
        {},
    )
    assert result4["type"] == FlowResultType.ABORT
    assert result4["reason"] == "reconfigure_successful"

    assert entry.data[CONF_DEFAULT_SENSOR] == "Remote 2"
    assert entry.data[CONF_COOLDOWN_PERIOD] == 1800
    assert entry.data[CONF_MIN_TEMP] == 18.0
    assert entry.data[CONF_MAX_TEMP] == 28.0
    assert entry.data[CONF_OVERDRIVE_OFFSET] == 2.5

    assert entry.options[CONF_DEFAULT_SENSOR] == "Remote 2"
    assert entry.options[CONF_COOLDOWN_PERIOD] == 1800
    assert entry.options[CONF_MIN_TEMP] == 18.0
    assert entry.options[CONF_MAX_TEMP] == 28.0
    assert entry.options[CONF_OVERDRIVE_OFFSET] == 2.5


def test_validate_sensor_submission() -> None:
    """Test sensor collision and reserved name validation."""
    sensors = [
        {
            "name": "Living Room",
            "entity_id": "sensor.living_room",
            "humidity_entity_id": "sensor.living_room_humidity",
        }
    ]

    # Reserved physical name (default or custom)
    assert (
        _validate_sensor_submission(
            sensors, "Custom Physical", "Physical Entity", "sensor.temp", None
        )
        == "reserved_sensor_name"
    )
    assert (
        _validate_sensor_submission(
            sensors, "Custom Physical", "custom physical", "sensor.temp", None
        )
        == "reserved_sensor_name"
    )

    # Duplicate name
    assert (
        _validate_sensor_submission(
            sensors, "Physical", "Living Room", "sensor.bedroom", None
        )
        == "duplicate_sensor_name"
    )

    # Duplicate entity id
    assert (
        _validate_sensor_submission(
            sensors, "Physical", "Bedroom", "sensor.living_room", None
        )
        == "duplicate_sensor_entity"
    )

    # Duplicate humidity entity id
    assert (
        _validate_sensor_submission(
            sensors,
            "Physical",
            "Bedroom",
            "sensor.bedroom",
            "sensor.living_room_humidity",
        )
        == "duplicate_sensor_entity"
    )

    # Excluded name (replacing an existing sensor keeping its own name/entity)
    assert (
        _validate_sensor_submission(
            sensors,
            "Physical",
            "Living Room",
            "sensor.living_room_new",
            None,
            exclude_name="Living Room",
        )
        is None
    )

    # Valid submission
    assert (
        _validate_sensor_submission(
            sensors, "Physical", "Bedroom", "sensor.bedroom", "sensor.bedroom_humidity"
        )
        is None
    )


def test_parse_and_validate_runtime_input() -> None:
    """Test parsing and validating runtime input."""
    # Invalid default sensor
    data, error = _parse_and_validate_runtime_input(
        {"default_sensor": "Nonexistent"},
        available_default_options=["Living Room"],
        fallback_disable_auto_switch=False,
        fallback_preserve_virtual_target=False,
    )
    assert error == "invalid_default_sensor"
    assert data == {}

    # Invalid temp range
    data, error = _parse_and_validate_runtime_input(
        {"min_temp": 25.0, "max_temp": 20.0},
        available_default_options=["Living Room"],
        fallback_disable_auto_switch=False,
        fallback_preserve_virtual_target=False,
    )
    assert error == "invalid_temp_range"
    assert data == {}

    # Valid input with last active sensor
    data, error = _parse_and_validate_runtime_input(
        {
            "default_sensor": DEFAULT_SENSOR_LAST_ACTIVE,
            "min_temp": 18.0,
            "max_temp": 26.0,
            "cooldown_period": 600,
        },
        available_default_options=["Living Room"],
        fallback_disable_auto_switch=False,
        fallback_preserve_virtual_target=False,
    )
    assert error is None
    assert data["default_sensor"] == DEFAULT_SENSOR_LAST_ACTIVE
    assert data["use_last_active_sensor"] is True
    assert data["min_temp"] == 18.0
    assert data["max_temp"] == 26.0
    assert data["cooldown_period"] == 600


def test_extract_entry_runtime_settings() -> None:
    """Test extracting runtime settings with options merging and last active normalization."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_DEFAULT_SENSOR: "Sensor A",
            CONF_COOLDOWN_PERIOD: 300,
            CONF_MIN_TEMP: 15.0,
            CONF_DISABLE_AUTO_SWITCH: False,
        },
        options={
            CONF_DEFAULT_SENSOR: DEFAULT_SENSOR_LAST_ACTIVE,
            CONF_COOLDOWN_PERIOD: 900,
            CONF_DISABLE_AUTO_SWITCH: True,
        },
    )
    settings = _extract_entry_runtime_settings(entry)
    assert settings[CONF_DEFAULT_SENSOR] is None
    assert settings["use_last_active_sensor"] is True
    assert settings[CONF_COOLDOWN_PERIOD] == 900
    assert settings[CONF_MIN_TEMP] == 15.0
    assert settings[CONF_DISABLE_AUTO_SWITCH] is True
