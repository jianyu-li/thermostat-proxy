"""Test the Thermostat Proxy config flow."""

from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import voluptuous as vol

from custom_components.thermostat_proxy.config_flow import (
    _build_default_sensor_field,
    _extract_entry_runtime_settings,
    _parse_and_validate_runtime_input,
    _target_change_behavior_from_flags,
    _target_change_flags_from_behavior,
    _validate_sensor_submission,
)
from custom_components.thermostat_proxy.const import (
    CONF_COOLDOWN_PERIOD,
    CONF_DEFAULT_SENSOR,
    CONF_DEFAULT_TARGET_HUMIDITY,
    CONF_DISABLE_AUTO_SWITCH,
    CONF_MAX_HUMIDITY_OVERCOOL,
    CONF_MAX_TEMP,
    CONF_MIN_DUAL_TEMP_SPREAD,
    CONF_MIN_TEMP,
    CONF_OVERDRIVE_OFFSET,
    CONF_PHYSICAL_SENSOR_NAME,
    CONF_PHYSICAL_TARGET_CHANGE_BEHAVIOR,
    CONF_PRESERVE_VIRTUAL_TARGET,
    CONF_SENSOR_CHANGE_THRESHOLD,
    CONF_SENSORS,
    CONF_THERMOSTAT,
    DEFAULT_SENSOR_LAST_ACTIVE,
    DOMAIN,
    MAX_COOLDOWN_PERIOD_SECONDS,
    MAX_HUMIDITY_OVERCOOL,
    MAX_MIN_DUAL_TEMP_SPREAD,
    MAX_SENSOR_CHANGE_THRESHOLD,
    MAX_TARGET_HUMIDITY,
    MIN_TARGET_HUMIDITY,
    TARGET_CHANGE_BEHAVIOR_AUTO_SWITCH,
    TARGET_CHANGE_BEHAVIOR_DISABLE_AUTO_SWITCH,
    TARGET_CHANGE_BEHAVIOR_PRESERVE_VIRTUAL_TARGET,
)
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData


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


def test_build_default_sensor_field_no_empty_string() -> None:
    """Verify _build_default_sensor_field does not set an empty string as default choice."""
    # When default_value is "", no default should be set on the Optional schema marker
    field_empty = _build_default_sensor_field(["Sensor 1", "Sensor 2"], "")
    assert field_empty is not None
    vol_key, _ = field_empty
    assert vol_key.default is vol.UNDEFINED

    # When default_value is None, no default should be set
    field_none = _build_default_sensor_field(["Sensor 1", "Sensor 2"], None)
    assert field_none is not None
    vol_key_none, _ = field_none
    assert vol_key_none.default is vol.UNDEFINED

    # When default_value is provided, default should be set
    field_valid = _build_default_sensor_field(["Sensor 1", "Sensor 2"], "Sensor 1")
    assert field_valid is not None
    vol_key_valid, _ = field_valid
    assert vol_key_valid.default() == "Sensor 1"

    # When options list is empty or None, return None
    assert _build_default_sensor_field([], "Sensor 1") is None
    assert _build_default_sensor_field(None, "Sensor 1") is None


@pytest.mark.asyncio
async def test_schema_bounds_validation_options_and_finalize(
    hass: HomeAssistant,
) -> None:
    """Verify that option and finalize schemas reject or accept values within new bounds."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Proxy",
        data={
            CONF_THERMOSTAT: "climate.real",
            CONF_SENSORS: [{"name": "Remote", "entity_id": "sensor.remote"}],
        },
        source="user",
        unique_id="proxy_bounds_test",
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # 1. Options Flow Schema Bounds
    options_res = await hass.config_entries.options.async_init(entry.entry_id)
    assert options_res["type"] == FlowResultType.FORM
    assert options_res["step_id"] == "init"
    options_schema = options_res["data_schema"]

    # Humidity bounds (MIN_TARGET_HUMIDITY=30, MAX_TARGET_HUMIDITY=99)
    assert (
        options_schema({CONF_DEFAULT_TARGET_HUMIDITY: MIN_TARGET_HUMIDITY})[
            CONF_DEFAULT_TARGET_HUMIDITY
        ]
        == MIN_TARGET_HUMIDITY
    )
    assert (
        options_schema({CONF_DEFAULT_TARGET_HUMIDITY: MAX_TARGET_HUMIDITY})[
            CONF_DEFAULT_TARGET_HUMIDITY
        ]
        == MAX_TARGET_HUMIDITY
    )
    assert (
        options_schema({CONF_DEFAULT_TARGET_HUMIDITY: 50})[CONF_DEFAULT_TARGET_HUMIDITY]
        == 50
    )

    with pytest.raises(vol.Invalid):
        options_schema({CONF_DEFAULT_TARGET_HUMIDITY: MIN_TARGET_HUMIDITY - 1})

    with pytest.raises(vol.Invalid):
        options_schema({CONF_DEFAULT_TARGET_HUMIDITY: MAX_TARGET_HUMIDITY + 1})

    # Options flow async_configure rejection with InvalidData
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            options_res["flow_id"],
            user_input={CONF_DEFAULT_TARGET_HUMIDITY: 105},
        )

    # Max humidity overcool (0.0 to MAX_HUMIDITY_OVERCOOL=10.0)
    assert (
        options_schema({CONF_MAX_HUMIDITY_OVERCOOL: 0.0})[CONF_MAX_HUMIDITY_OVERCOOL]
        == 0.0
    )
    assert (
        options_schema({CONF_MAX_HUMIDITY_OVERCOOL: MAX_HUMIDITY_OVERCOOL})[
            CONF_MAX_HUMIDITY_OVERCOOL
        ]
        == MAX_HUMIDITY_OVERCOOL
    )
    with pytest.raises(vol.Invalid):
        options_schema({CONF_MAX_HUMIDITY_OVERCOOL: -0.5})
    with pytest.raises(vol.Invalid):
        options_schema({CONF_MAX_HUMIDITY_OVERCOOL: MAX_HUMIDITY_OVERCOOL + 0.5})

    # Min dual temp spread (0.0 to MAX_MIN_DUAL_TEMP_SPREAD=15.0)
    assert (
        options_schema({CONF_MIN_DUAL_TEMP_SPREAD: 0.0})[CONF_MIN_DUAL_TEMP_SPREAD]
        == 0.0
    )
    assert (
        options_schema({CONF_MIN_DUAL_TEMP_SPREAD: MAX_MIN_DUAL_TEMP_SPREAD})[
            CONF_MIN_DUAL_TEMP_SPREAD
        ]
        == MAX_MIN_DUAL_TEMP_SPREAD
    )
    with pytest.raises(vol.Invalid):
        options_schema({CONF_MIN_DUAL_TEMP_SPREAD: -0.1})
    with pytest.raises(vol.Invalid):
        options_schema({CONF_MIN_DUAL_TEMP_SPREAD: MAX_MIN_DUAL_TEMP_SPREAD + 0.5})

    # Cooldown period (0 to MAX_COOLDOWN_PERIOD_SECONDS=3600)
    assert options_schema({CONF_COOLDOWN_PERIOD: 0})[CONF_COOLDOWN_PERIOD] == 0
    assert (
        options_schema({CONF_COOLDOWN_PERIOD: MAX_COOLDOWN_PERIOD_SECONDS})[
            CONF_COOLDOWN_PERIOD
        ]
        == MAX_COOLDOWN_PERIOD_SECONDS
    )
    with pytest.raises(vol.Invalid):
        options_schema({CONF_COOLDOWN_PERIOD: -1})
    with pytest.raises(vol.Invalid):
        options_schema({CONF_COOLDOWN_PERIOD: MAX_COOLDOWN_PERIOD_SECONDS + 1})

    # Sensor change threshold (0.0 to MAX_SENSOR_CHANGE_THRESHOLD=10.0)
    assert (
        options_schema({CONF_SENSOR_CHANGE_THRESHOLD: 0.0})[
            CONF_SENSOR_CHANGE_THRESHOLD
        ]
        == 0.0
    )
    assert (
        options_schema({CONF_SENSOR_CHANGE_THRESHOLD: MAX_SENSOR_CHANGE_THRESHOLD})[
            CONF_SENSOR_CHANGE_THRESHOLD
        ]
        == MAX_SENSOR_CHANGE_THRESHOLD
    )
    with pytest.raises(vol.Invalid):
        options_schema({CONF_SENSOR_CHANGE_THRESHOLD: -0.1})
    with pytest.raises(vol.Invalid):
        options_schema(
            {CONF_SENSOR_CHANGE_THRESHOLD: MAX_SENSOR_CHANGE_THRESHOLD + 0.5}
        )

    # Overdrive offset (0.0 to 5.0)
    assert options_schema({CONF_OVERDRIVE_OFFSET: 0.0})[CONF_OVERDRIVE_OFFSET] == 0.0
    assert options_schema({CONF_OVERDRIVE_OFFSET: 5.0})[CONF_OVERDRIVE_OFFSET] == 5.0
    with pytest.raises(vol.Invalid):
        options_schema({CONF_OVERDRIVE_OFFSET: -0.5})
    with pytest.raises(vol.Invalid):
        options_schema({CONF_OVERDRIVE_OFFSET: 5.5})

    # 2. Finalize Flow Schema Bounds
    flow_res = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    flow_res = await hass.config_entries.flow.async_configure(
        flow_res["flow_id"],
        {"name": "Proxy 2", "thermostat": "climate.real"},
    )
    flow_res = await hass.config_entries.flow.async_configure(
        flow_res["flow_id"],
        {"action": "add_sensor"},
    )
    flow_res = await hass.config_entries.flow.async_configure(
        flow_res["flow_id"],
        {"name": "Remote", "entity_id": "sensor.remote", "add_another": False},
    )
    flow_res = await hass.config_entries.flow.async_configure(
        flow_res["flow_id"],
        {"action": "finish"},
    )
    assert flow_res["type"] == FlowResultType.FORM
    assert flow_res["step_id"] == "finalize"
    finalize_schema = flow_res["data_schema"]

    # Validate bounds on finalize schema
    assert (
        finalize_schema({CONF_DEFAULT_TARGET_HUMIDITY: MIN_TARGET_HUMIDITY})[
            CONF_DEFAULT_TARGET_HUMIDITY
        ]
        == MIN_TARGET_HUMIDITY
    )
    assert (
        finalize_schema({CONF_DEFAULT_TARGET_HUMIDITY: MAX_TARGET_HUMIDITY})[
            CONF_DEFAULT_TARGET_HUMIDITY
        ]
        == MAX_TARGET_HUMIDITY
    )
    with pytest.raises(vol.Invalid):
        finalize_schema({CONF_DEFAULT_TARGET_HUMIDITY: MIN_TARGET_HUMIDITY - 1})
    with pytest.raises(vol.Invalid):
        finalize_schema({CONF_DEFAULT_TARGET_HUMIDITY: MAX_TARGET_HUMIDITY + 1})

    # Finalize async_configure rejection with InvalidData
    with pytest.raises(InvalidData):
        await hass.config_entries.flow.async_configure(
            flow_res["flow_id"],
            user_input={CONF_DEFAULT_TARGET_HUMIDITY: 105},
        )
