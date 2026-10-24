"""Tests for integration setup and wiring."""

from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import voluptuous as vol

from custom_components.thermostat_proxy.climate import (
    PLATFORM_SCHEMA,
    _extract_entity_config,
    async_setup_platform,
)
from custom_components.thermostat_proxy.const import (
    CONF_COOLDOWN_PERIOD,
    CONF_DEFAULT_SENSOR,
    CONF_DEFAULT_TARGET_HUMIDITY,
    CONF_DISABLE_AUTO_SWITCH,
    CONF_MAX_HUMIDITY_OVERCOOL,
    CONF_MAX_SYNC_OFFSET,
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
    DEFAULT_MAX_SYNC_OFFSET,
    DEFAULT_SENSOR_LAST_ACTIVE,
    DOMAIN,
    PHYSICAL_SENSOR_NAME,
    TARGET_CHANGE_BEHAVIOR_AUTO_SWITCH,
    TARGET_CHANGE_BEHAVIOR_DISABLE_AUTO_SWITCH,
    TARGET_CHANGE_BEHAVIOR_PRESERVE_VIRTUAL_TARGET,
)
from custom_components.thermostat_proxy.helpers import (
    extract_entity_config,
    extract_runtime_settings,
)
from homeassistant.core import HomeAssistant


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
            CONF_PRESERVE_VIRTUAL_TARGET: True,
            CONF_OVERDRIVE_OFFSET: 0.0,
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
        assert getattr(entity, "_preserve_virtual_target", False) is True
        assert getattr(entity, "_overdrive_offset", None) == 0.0


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
    await entity.async_set_temperature(temperature=26.0)
    # The real thermostat target should be adjusted to 20.0 + (26.0 - 24.0) = 22.0
    real_state = hass.states.get("climate.real")
    assert real_state.attributes["temperature"] == 22.0

    # Advance the write time back so we are out of the post-write grace period
    entity._last_real_write_time -= 46.0

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


@pytest.mark.asyncio
async def test_setup_platform(hass: HomeAssistant) -> None:
    """Test legacy YAML setup."""
    config = {
        "name": "YAML Proxy",
        "thermostat": "climate.real",
        "sensors": [{"name": "Remote", "entity_id": "sensor.remote"}],
        "default_sensor": "Remote",
    }

    entities = []

    def add_entities(new_entities):
        entities.extend(new_entities)

    await async_setup_platform(hass, config, add_entities, None)

    assert len(entities) == 1
    assert entities[0].name == "YAML Proxy"


@pytest.mark.asyncio
async def test_entry_options_override_data(hass: HomeAssistant) -> None:
    """Test that entry.options properly overrides entry.data, including None resets."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Proxy",
        data={
            CONF_THERMOSTAT: "climate.real",
            CONF_SENSORS: [{"name": "Remote", "entity_id": "sensor.remote"}],
            CONF_MIN_TEMP: 18.0,
            CONF_MAX_TEMP: 26.0,
            CONF_MAX_SYNC_OFFSET: 5.0,
            CONF_COOLDOWN_PERIOD: 60,
            CONF_OVERDRIVE_OFFSET: 1.5,
            CONF_SENSOR_CHANGE_THRESHOLD: 0.2,
            CONF_MAX_HUMIDITY_OVERCOOL: 1.0,
            CONF_DEFAULT_TARGET_HUMIDITY: 40,
            CONF_MIN_DUAL_TEMP_SPREAD: 2.0,
        },
        options={
            CONF_MIN_TEMP: None,
            CONF_MAX_TEMP: None,
            CONF_MAX_SYNC_OFFSET: None,
            CONF_MIN_DUAL_TEMP_SPREAD: None,
            CONF_COOLDOWN_PERIOD: 120,
            CONF_OVERDRIVE_OFFSET: 0.5,
            CONF_PHYSICAL_TARGET_CHANGE_BEHAVIOR: TARGET_CHANGE_BEHAVIOR_PRESERVE_VIRTUAL_TARGET,
            CONF_SENSOR_CHANGE_THRESHOLD: 0.5,
            CONF_MAX_HUMIDITY_OVERCOOL: 3.0,
            CONF_DEFAULT_TARGET_HUMIDITY: 60,
        },
        source="user",
        unique_id="proxy_override_none",
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    component = hass.data["climate"]
    entity = component.get_entity("climate.thermostat_proxy")
    assert entity is not None

    assert entity._user_min_temp is None
    assert entity._user_max_temp is None
    assert entity._max_sync_offset is None
    assert entity._min_dual_temp_spread is None
    assert entity._cooldown_period == 120.0
    assert entity._overdrive_offset == 0.5
    assert entity._disable_auto_switch is True
    assert entity._preserve_virtual_target is True
    assert entity._sensor_change_threshold == 0.5
    assert entity._max_humidity_overcool == 3.0
    assert entity._default_target_humidity == 60


@pytest.mark.asyncio
async def test_entry_options_override_values(hass: HomeAssistant) -> None:
    """Test that entry.options overrides numeric values from entry.data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Proxy",
        data={
            CONF_THERMOSTAT: "climate.real",
            CONF_SENSORS: [{"name": "Remote", "entity_id": "sensor.remote"}],
            CONF_MIN_TEMP: 18.0,
            CONF_MAX_TEMP: 26.0,
            CONF_MAX_SYNC_OFFSET: 5.0,
        },
        options={
            CONF_MIN_TEMP: 15.0,
            CONF_MAX_TEMP: 28.0,
            CONF_MAX_SYNC_OFFSET: 8.0,
        },
        source="user",
        unique_id="proxy_override_values",
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    component = hass.data["climate"]
    entity = component.get_entity("climate.thermostat_proxy")
    assert entity is not None

    assert entity._user_min_temp == 15.0
    assert entity._user_max_temp == 28.0
    assert entity._max_sync_offset == 8.0


@pytest.mark.asyncio
async def test_setup_platform_with_behavior_and_last_active(
    hass: HomeAssistant,
) -> None:
    """Test YAML setup with physical_target_change_behavior and last active sensor."""
    config = {
        "name": "YAML Proxy Advanced",
        "thermostat": "climate.real",
        "sensors": [{"name": "Remote", "entity_id": "sensor.remote"}],
        "default_sensor": DEFAULT_SENSOR_LAST_ACTIVE,
        "physical_target_change_behavior": TARGET_CHANGE_BEHAVIOR_PRESERVE_VIRTUAL_TARGET,
        "max_humidity_overcool": 3.0,
        "default_target_humidity": 45,
    }

    entities = []

    def add_entities(new_entities):
        entities.extend(new_entities)

    await async_setup_platform(hass, config, add_entities, None)

    assert len(entities) == 1
    entity = entities[0]
    assert entity.name == "YAML Proxy Advanced"
    assert entity._use_last_active_sensor is True
    assert entity._configured_default_sensor is None
    assert entity._disable_auto_switch is True
    assert entity._preserve_virtual_target is True
    assert entity._max_humidity_overcool == 3.0
    assert entity._default_target_humidity == 45


@pytest.mark.parametrize(
    ("behavior", "expected_disable", "expected_preserve"),
    [
        (TARGET_CHANGE_BEHAVIOR_AUTO_SWITCH, False, False),
        (TARGET_CHANGE_BEHAVIOR_DISABLE_AUTO_SWITCH, True, False),
        (TARGET_CHANGE_BEHAVIOR_PRESERVE_VIRTUAL_TARGET, True, True),
    ],
)
@pytest.mark.asyncio
async def test_setup_platform_target_change_behaviors(
    hass: HomeAssistant,
    behavior: str,
    expected_disable: bool,
    expected_preserve: bool,
) -> None:
    """Test YAML setup with various physical target change behaviors."""
    config = {
        "name": "YAML Proxy Behavior",
        "thermostat": "climate.real",
        "sensors": [{"name": "Remote", "entity_id": "sensor.remote"}],
        "physical_target_change_behavior": behavior,
    }

    entities = []
    await async_setup_platform(hass, config, entities.extend, None)

    assert len(entities) == 1
    entity = entities[0]
    assert entity._disable_auto_switch is expected_disable
    assert entity._preserve_virtual_target is expected_preserve


def test_platform_schema_validation() -> None:
    """Test PLATFORM_SCHEMA validation with all new options."""
    raw_config = {
        "platform": "thermostat_proxy",
        "thermostat": "climate.real",
        "sensors": [{"name": "Remote", "entity_id": "sensor.remote"}],
        "max_humidity_overcool": 2.5,
        "default_target_humidity": 55,
        "physical_target_change_behavior": "preserve_virtual_target",
    }
    validated = PLATFORM_SCHEMA(raw_config)
    assert validated["max_humidity_overcool"] == 2.5
    assert validated["default_target_humidity"] == 55
    assert validated["physical_target_change_behavior"] == "preserve_virtual_target"


def test_platform_schema_invalid_options() -> None:
    """Test PLATFORM_SCHEMA rejection of invalid behavior and humidity."""
    with pytest.raises(vol.Invalid):
        PLATFORM_SCHEMA(
            {
                "platform": "thermostat_proxy",
                "thermostat": "climate.real",
                "sensors": [{"name": "Remote", "entity_id": "sensor.remote"}],
                "physical_target_change_behavior": "unknown_behavior",
            }
        )

    with pytest.raises(vol.Invalid):
        PLATFORM_SCHEMA(
            {
                "platform": "thermostat_proxy",
                "thermostat": "climate.real",
                "sensors": [{"name": "Remote", "entity_id": "sensor.remote"}],
                "default_target_humidity": 20,  # Below min 30
            }
        )

    with pytest.raises(vol.Invalid):
        PLATFORM_SCHEMA(
            {
                "platform": "thermostat_proxy",
                "thermostat": "climate.real",
                "sensors": [{"name": "Remote", "entity_id": "sensor.remote"}],
                "default_target_humidity": 105,  # Above max 99
            }
        )


def test_extract_entity_config_helper() -> None:
    """Test _extract_entity_config helper logic directly."""
    cfg = _extract_entity_config({})
    assert cfg["max_sync_offset"] == DEFAULT_MAX_SYNC_OFFSET
    assert cfg["disable_auto_switch"] is False
    assert cfg["preserve_virtual_target"] is False
    assert cfg["use_last_active_sensor"] is False
    assert cfg["physical_sensor_name"] == "Physical Entity"

    # Test custom physical sensor name
    cfg_custom = _extract_entity_config(
        {CONF_PHYSICAL_SENSOR_NAME: "Custom Thermostat"}
    )
    assert cfg_custom["physical_sensor_name"] == "Custom Thermostat"

    # Test invalid default sensor when valid_sensor_names provided
    cfg_invalid = _extract_entity_config(
        {CONF_DEFAULT_SENSOR: "MissingSensor"},
        valid_sensor_names=["Remote", "Physical Entity"],
        entry_id="test_entry_123",
    )
    assert cfg_invalid["default_sensor"] is None

    # Test valid default sensor
    cfg_valid = _extract_entity_config(
        {CONF_DEFAULT_SENSOR: "Remote"},
        valid_sensor_names=["Remote", "Physical Entity"],
        entry_id="test_entry_123",
    )
    assert cfg_valid["default_sensor"] == "Remote"


@pytest.mark.asyncio
async def test_async_setup_entry_missing_sensors(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test setup entry skipping when sensors list is missing or empty."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Proxy",
        data={
            CONF_THERMOSTAT: "climate.real",
            CONF_SENSORS: [],
        },
        source="user",
        unique_id="proxy_no_sensors",
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("climate.thermostat_proxy") is None
    assert "missing sensors; skipping Thermostat Proxy creation" in caplog.text


@pytest.mark.asyncio
async def test_async_setup_entry_invalid_default_sensor_fallback(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test fallback when configured default sensor is not in valid sensors."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Proxy",
        data={
            CONF_THERMOSTAT: "climate.real",
            CONF_SENSORS: [{"name": "Remote", "entity_id": "sensor.remote"}],
            CONF_DEFAULT_SENSOR: "MissingSensor",
        },
        source="user",
        unique_id="proxy_invalid_sensor",
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    component = hass.data["climate"]
    entity = component.get_entity("climate.thermostat_proxy")
    assert entity is not None
    assert entity._configured_default_sensor is None
    assert (
        f"Default sensor 'MissingSensor' not in config entry {entry.entry_id}"
        in caplog.text
    )


@pytest.mark.asyncio
async def test_max_sync_offset_zero_disables_clamping_and_allows_delta(
    hass: HomeAssistant,
) -> None:
    """Test that max_sync_offset=0 does not pin target to ref_target and allows deltas."""
    hass.states.async_set(
        "climate.real",
        "heat",
        {
            "current_temperature": 20.0,
            "temperature": 20.0,
            "min_temp": 5.0,
            "max_temp": 35.0,
            "target_temp_step": 1.0,
            "supported_features": 1,  # TARGET_TEMPERATURE
        },
    )
    hass.states.async_set("sensor.remote", "15.0")

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Proxy",
        data={
            CONF_THERMOSTAT: "climate.real",
            CONF_SENSORS: [{"name": "Remote", "entity_id": "sensor.remote"}],
        },
        options={
            CONF_MAX_SYNC_OFFSET: 0,
            CONF_DISABLE_AUTO_SWITCH: True,
            CONF_OVERDRIVE_OFFSET: 0.0,
        },
        source="user",
        unique_id="proxy_offset_zero",
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    component = hass.data["climate"]
    entity = component.get_entity("climate.thermostat_proxy")
    assert entity is not None
    assert entity._max_sync_offset is None

    # Direct safety clamp check: with max_sync_offset disabled (None),
    # an offset of +5.0 (calculated 25.0 vs ref 20.0) or -5.0 (15.0 vs ref 20.0)
    # is NOT clamped to ref_target 20.0.
    assert entity._apply_safety_clamp(25.0, reference_target=20.0) == 25.0
    assert entity._apply_safety_clamp(15.0, reference_target=20.0) == 15.0

    # Wait for target realignment task
    await hass.async_block_till_done()

    # Set virtual target temperature to 20.0.
    # Remote sensor is 15.0, delta is 20.0 - 15.0 = +5.0 degrees.
    # Real current is 20.0, so real target should adjust to 20.0 + 5.0 = 25.0 degrees.
    # If max_sync_offset=0 pinned or clamped to ref_target (20.0 ± 0), real target would stay 20.0.
    await entity.async_set_temperature(temperature=20.0)
    await hass.async_block_till_done()

    assert entity._last_commanded_real_target == 25.0
    proxy_state = hass.states.get("climate.thermostat_proxy")
    assert proxy_state is not None
    assert proxy_state.attributes["real_target_temperature"] == 25.0

    # Test cooling delta (-5.0 degrees)
    hass.states.async_set("sensor.remote", "25.0")
    entity._last_real_write_time -= 46.0  # clear write grace period

    # Remote sensor is 25.0, virtual target is 20.0, delta is 20.0 - 25.0 = -5.0 degrees.
    # Real current is 20.0, so real target should adjust to 20.0 + (-5.0) = 15.0 degrees.
    await entity.async_set_temperature(temperature=20.0)
    await hass.async_block_till_done()

    assert entity._last_commanded_real_target == 15.0
    proxy_state = hass.states.get("climate.thermostat_proxy")
    assert proxy_state is not None
    assert proxy_state.attributes["real_target_temperature"] == 15.0


def test_extract_runtime_settings_behaviors_and_offsets() -> None:
    """Test extract_runtime_settings behavior resolution, legacy flags, and offset normalization."""
    # 1. Behavior selector values
    cfg_auto = extract_runtime_settings(
        {CONF_PHYSICAL_TARGET_CHANGE_BEHAVIOR: TARGET_CHANGE_BEHAVIOR_AUTO_SWITCH}
    )
    assert cfg_auto[CONF_DISABLE_AUTO_SWITCH] is False
    assert cfg_auto[CONF_PRESERVE_VIRTUAL_TARGET] is False

    cfg_disable = extract_runtime_settings(
        {
            CONF_PHYSICAL_TARGET_CHANGE_BEHAVIOR: TARGET_CHANGE_BEHAVIOR_DISABLE_AUTO_SWITCH
        }
    )
    assert cfg_disable[CONF_DISABLE_AUTO_SWITCH] is True
    assert cfg_disable[CONF_PRESERVE_VIRTUAL_TARGET] is False

    cfg_preserve = extract_runtime_settings(
        {
            CONF_PHYSICAL_TARGET_CHANGE_BEHAVIOR: TARGET_CHANGE_BEHAVIOR_PRESERVE_VIRTUAL_TARGET
        }
    )
    assert cfg_preserve[CONF_DISABLE_AUTO_SWITCH] is True
    assert cfg_preserve[CONF_PRESERVE_VIRTUAL_TARGET] is True

    # 2. Legacy boolean flags when behavior is omitted
    cfg_legacy_true_true = extract_runtime_settings(
        {CONF_DISABLE_AUTO_SWITCH: True, CONF_PRESERVE_VIRTUAL_TARGET: True}
    )
    assert cfg_legacy_true_true[CONF_DISABLE_AUTO_SWITCH] is True
    assert cfg_legacy_true_true[CONF_PRESERVE_VIRTUAL_TARGET] is True

    cfg_legacy_true_false = extract_runtime_settings(
        {CONF_DISABLE_AUTO_SWITCH: True, CONF_PRESERVE_VIRTUAL_TARGET: False}
    )
    assert cfg_legacy_true_false[CONF_DISABLE_AUTO_SWITCH] is True
    assert cfg_legacy_true_false[CONF_PRESERVE_VIRTUAL_TARGET] is False

    cfg_legacy_false = extract_runtime_settings(
        {CONF_DISABLE_AUTO_SWITCH: False, CONF_PRESERVE_VIRTUAL_TARGET: False}
    )
    assert cfg_legacy_false[CONF_DISABLE_AUTO_SWITCH] is False
    assert cfg_legacy_false[CONF_PRESERVE_VIRTUAL_TARGET] is False

    # Behavior key takes precedence over legacy flags if both present
    cfg_both = extract_runtime_settings(
        {
            CONF_PHYSICAL_TARGET_CHANGE_BEHAVIOR: TARGET_CHANGE_BEHAVIOR_AUTO_SWITCH,
            CONF_DISABLE_AUTO_SWITCH: True,
            CONF_PRESERVE_VIRTUAL_TARGET: True,
        }
    )
    assert cfg_both[CONF_DISABLE_AUTO_SWITCH] is False
    assert cfg_both[CONF_PRESERVE_VIRTUAL_TARGET] is False

    # 3. max_sync_offset conversions
    assert (
        extract_runtime_settings({CONF_MAX_SYNC_OFFSET: 0})[CONF_MAX_SYNC_OFFSET]
        is None
    )
    assert (
        extract_runtime_settings({CONF_MAX_SYNC_OFFSET: 0.0})[CONF_MAX_SYNC_OFFSET]
        is None
    )
    assert (
        extract_runtime_settings({CONF_MAX_SYNC_OFFSET: "0"})[CONF_MAX_SYNC_OFFSET]
        is None
    )
    assert (
        extract_runtime_settings({CONF_MAX_SYNC_OFFSET: None})[CONF_MAX_SYNC_OFFSET]
        is None
    )
    assert (
        extract_runtime_settings({CONF_MAX_SYNC_OFFSET: 5.5})[CONF_MAX_SYNC_OFFSET]
        == 5.5
    )
    assert extract_runtime_settings({})[CONF_MAX_SYNC_OFFSET] == DEFAULT_MAX_SYNC_OFFSET

    # 3b. min_temp, max_temp, and min_dual_temp_spread zero-to-None conversions
    assert extract_runtime_settings({CONF_MIN_TEMP: 0})[CONF_MIN_TEMP] is None
    assert extract_runtime_settings({CONF_MIN_TEMP: 0.0})[CONF_MIN_TEMP] is None
    assert extract_runtime_settings({CONF_MIN_TEMP: 16.5})[CONF_MIN_TEMP] == 16.5
    assert extract_runtime_settings({CONF_MAX_TEMP: 0})[CONF_MAX_TEMP] is None
    assert extract_runtime_settings({CONF_MAX_TEMP: 0.0})[CONF_MAX_TEMP] is None
    assert extract_runtime_settings({CONF_MAX_TEMP: 28.5})[CONF_MAX_TEMP] == 28.5
    assert (
        extract_runtime_settings({CONF_MIN_DUAL_TEMP_SPREAD: 0})[
            CONF_MIN_DUAL_TEMP_SPREAD
        ]
        is None
    )
    assert (
        extract_runtime_settings({CONF_MIN_DUAL_TEMP_SPREAD: 0.0})[
            CONF_MIN_DUAL_TEMP_SPREAD
        ]
        is None
    )
    assert (
        extract_runtime_settings({CONF_MIN_DUAL_TEMP_SPREAD: 4.0})[
            CONF_MIN_DUAL_TEMP_SPREAD
        ]
        == 4.0
    )

    # 4. default_sensor vs last active
    cfg_last = extract_runtime_settings(
        {CONF_DEFAULT_SENSOR: DEFAULT_SENSOR_LAST_ACTIVE}
    )
    assert cfg_last[CONF_DEFAULT_SENSOR] is None
    assert cfg_last["use_last_active_sensor"] is True

    cfg_sensor = extract_runtime_settings({CONF_DEFAULT_SENSOR: "Remote Sensor"})
    assert cfg_sensor[CONF_DEFAULT_SENSOR] == "Remote Sensor"
    assert cfg_sensor["use_last_active_sensor"] is False


def test_extract_entity_config_physical_sensor_name() -> None:
    """Test extract_entity_config physical sensor name resolution."""
    # Explicit parameter passed
    cfg_explicit = extract_entity_config(
        {},
        physical_sensor_name="Explicit Thermostat",
    )
    assert cfg_explicit["physical_sensor_name"] == "Explicit Thermostat"

    # Explicit parameter overrides config dict value
    cfg_override = extract_entity_config(
        {CONF_PHYSICAL_SENSOR_NAME: "From Config"},
        physical_sensor_name="Explicit Overrides",
    )
    assert cfg_override["physical_sensor_name"] == "Explicit Overrides"

    # Derived from config dict when explicit parameter is None
    cfg_config = extract_entity_config(
        {CONF_PHYSICAL_SENSOR_NAME: "From Config"},
        physical_sensor_name=None,
    )
    assert cfg_config["physical_sensor_name"] == "From Config"

    # Default fallback when neither is provided
    cfg_default = extract_entity_config({})
    assert cfg_default["physical_sensor_name"] == PHYSICAL_SENSOR_NAME


def test_extract_entity_config_default_sensor_fallback_and_offsets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test extract_entity_config default sensor validation warning and offset parsing."""
    valid_sensors = ["Living Room", "Bedroom"]

    # Invalid sensor with entry_id logs source with entry_id
    caplog.clear()
    cfg_entry = extract_entity_config(
        {CONF_DEFAULT_SENSOR: "Kitchen"},
        valid_sensor_names=valid_sensors,
        entry_id="entry_456",
    )
    assert cfg_entry["default_sensor"] is None
    assert (
        "Default sensor 'Kitchen' not in config entry entry_456; falling back to first sensor"
        in caplog.text
    )

    # Invalid sensor without entry_id logs source as 'configuration'
    caplog.clear()
    cfg_no_entry = extract_entity_config(
        {CONF_DEFAULT_SENSOR: "Kitchen"},
        valid_sensor_names=valid_sensors,
        entry_id=None,
    )
    assert cfg_no_entry["default_sensor"] is None
    assert (
        "Default sensor 'Kitchen' not in configuration; falling back to first sensor"
        in caplog.text
    )

    # Valid sensor in valid_sensors produces no warning
    caplog.clear()
    cfg_valid = extract_entity_config(
        {CONF_DEFAULT_SENSOR: "Living Room"},
        valid_sensor_names=valid_sensors,
        entry_id="entry_456",
    )
    assert cfg_valid["default_sensor"] == "Living Room"
    assert "Default sensor" not in caplog.text

    # max_sync_offset: 0 and 0.0 converted to None
    cfg_zero = extract_entity_config({CONF_MAX_SYNC_OFFSET: 0})
    assert cfg_zero["max_sync_offset"] is None

    cfg_zero_float = extract_entity_config({CONF_MAX_SYNC_OFFSET: 0.0})
    assert cfg_zero_float["max_sync_offset"] is None
