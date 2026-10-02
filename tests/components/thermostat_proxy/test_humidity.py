"""Tests for humidity support in Thermostat Proxy."""

from unittest.mock import MagicMock, patch

import pytest

from custom_components.thermostat_proxy.climate import CustomThermostatEntity
from custom_components.thermostat_proxy.const import (
    ATTR_ACTIVE_HUMIDITY_SENSOR,
    ATTR_ACTIVE_HUMIDITY_SENSOR_ENTITY_ID,
    ATTR_HUMIDITY_OVERDRIVE_ACTIVE,
    CONF_DEFAULT_TARGET_HUMIDITY,
    CONF_MAX_HUMIDITY_OVERCOOL,
    CONF_SENSOR_ENTITY_ID,
    CONF_SENSOR_HUMIDITY_ENTITY_ID,
    CONF_SENSOR_NAME,
    CONF_SENSORS,
    DEFAULT_TARGET_HUMIDITY,
    DOMAIN,
)
from homeassistant import config_entries
from homeassistant.components.climate import ClimateEntityFeature, HVACMode
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State
from homeassistant.data_entry_flow import FlowResultType


def create_proxy_with_humidity(
    hass: HomeAssistant,
    sensors=None,
    default_sensor="Remote",
    max_humidity_overcool=2.0,
    default_target_humidity=50,
):
    """Helper to create a configured CustomThermostatEntity with humidity settings."""
    if sensors is None:
        sensors = [
            {
                CONF_SENSOR_NAME: "Remote",
                CONF_SENSOR_ENTITY_ID: "sensor.remote_temp",
                CONF_SENSOR_HUMIDITY_ENTITY_ID: "sensor.remote_humidity",
            }
        ]

    proxy = CustomThermostatEntity(
        hass=hass,
        name="Test Proxy",
        real_thermostat="climate.real",
        sensors=sensors,
        default_sensor=default_sensor,
        unique_id="humidity_test_123",
        physical_sensor_name="Physical",
        use_last_active_sensor=False,
        max_humidity_overcool=max_humidity_overcool,
        default_target_humidity=default_target_humidity,
    )

    hass.states.async_set(
        "climate.real",
        HVACMode.COOL,
        {
            "current_temperature": 22.0,
            "temperature": 22.0,
            "current_humidity": 55,
            "target_temp_step": 1.0,
            "supported_features": ClimateEntityFeature.TARGET_TEMPERATURE,
        },
    )
    proxy._real_state = hass.states.get("climate.real")
    proxy._update_real_temperature_limits()
    proxy._temperature_unit = "°C"
    proxy._virtual_target_temperature = 22.0
    proxy._selected_sensor_name = default_sensor
    proxy.async_write_ha_state = MagicMock()
    return proxy


@pytest.mark.asyncio
async def test_humidity_supported_features_and_defaults(hass: HomeAssistant):
    """Test TARGET_HUMIDITY feature flag and default humidity properties."""
    proxy = create_proxy_with_humidity(hass)

    assert proxy.supported_features & ClimateEntityFeature.TARGET_HUMIDITY
    assert proxy.min_humidity == 30
    assert proxy.max_humidity == 99
    assert proxy.target_humidity == DEFAULT_TARGET_HUMIDITY


@pytest.mark.asyncio
async def test_current_humidity_remote_sensor(hass: HomeAssistant):
    """Test that current_humidity reads from the active remote humidity sensor."""
    proxy = create_proxy_with_humidity(hass)

    # Set remote humidity sensor state
    hass.states.async_set("sensor.remote_humidity", "45")
    proxy._sensor_humidity_states["sensor.remote_humidity"] = State(
        "sensor.remote_humidity", "45"
    )

    assert proxy.current_humidity == 45


@pytest.mark.asyncio
async def test_current_humidity_fallback_when_preset_lacks_humidity_sensor(
    hass: HomeAssistant,
):
    """Test fallback to physical thermostat humidity when preset has no humidity sensor."""
    sensors = [
        {
            CONF_SENSOR_NAME: "Temp Only",
            CONF_SENSOR_ENTITY_ID: "sensor.remote_temp",
            CONF_SENSOR_HUMIDITY_ENTITY_ID: None,
        }
    ]
    proxy = create_proxy_with_humidity(
        hass, sensors=sensors, default_sensor="Temp Only"
    )

    # Real thermostat has current_humidity: 55
    assert proxy.current_humidity == 55
    assert (
        proxy.extra_state_attributes[ATTR_ACTIVE_HUMIDITY_SENSOR]
        == proxy._physical_sensor_name
    )
    assert (
        proxy.extra_state_attributes[ATTR_ACTIVE_HUMIDITY_SENSOR_ENTITY_ID]
        == proxy._real_entity_id
    )


@pytest.mark.asyncio
async def test_current_humidity_fallback_when_remote_unavailable(
    hass: HomeAssistant,
):
    """Test fallback to physical thermostat when remote humidity sensor is unavailable/unknown."""
    proxy = create_proxy_with_humidity(hass)

    # Unavailable remote humidity sensor
    proxy._sensor_humidity_states["sensor.remote_humidity"] = State(
        "sensor.remote_humidity", STATE_UNAVAILABLE
    )
    assert proxy.current_humidity == 55

    # Unknown remote humidity sensor
    proxy._sensor_humidity_states["sensor.remote_humidity"] = State(
        "sensor.remote_humidity", STATE_UNKNOWN
    )
    assert proxy.current_humidity == 55

    # Invalid non-numeric state
    proxy._sensor_humidity_states["sensor.remote_humidity"] = State(
        "sensor.remote_humidity", "not_a_number"
    )
    assert proxy.current_humidity == 55


@pytest.mark.asyncio
async def test_current_humidity_none_when_physical_lacks_humidity(
    hass: HomeAssistant,
):
    """Test that current_humidity is None when fallback physical thermostat has no humidity."""
    sensors = [
        {
            CONF_SENSOR_NAME: "Temp Only",
            CONF_SENSOR_ENTITY_ID: "sensor.remote_temp",
            CONF_SENSOR_HUMIDITY_ENTITY_ID: None,
        }
    ]
    proxy = create_proxy_with_humidity(
        hass, sensors=sensors, default_sensor="Temp Only"
    )

    # Real thermostat without current_humidity
    hass.states.async_set(
        "climate.real",
        HVACMode.COOL,
        {
            "current_temperature": 22.0,
            "temperature": 22.0,
            "target_temp_step": 1.0,
        },
    )
    proxy._real_state = hass.states.get("climate.real")

    assert proxy.current_humidity is None


@pytest.mark.asyncio
async def test_preset_switching_switches_humidity_sensor(hass: HomeAssistant):
    """Test that changing preset mode updates both temperature and humidity active sensors."""
    sensors = [
        {
            CONF_SENSOR_NAME: "Living Room",
            CONF_SENSOR_ENTITY_ID: "sensor.lr_temp",
            CONF_SENSOR_HUMIDITY_ENTITY_ID: "sensor.lr_humidity",
        },
        {
            CONF_SENSOR_NAME: "Bedroom",
            CONF_SENSOR_ENTITY_ID: "sensor.br_temp",
            CONF_SENSOR_HUMIDITY_ENTITY_ID: None,
        },
    ]
    proxy = create_proxy_with_humidity(
        hass, sensors=sensors, default_sensor="Living Room"
    )

    hass.states.async_set("sensor.lr_temp", "21.0")
    proxy._sensor_states["sensor.lr_temp"] = State("sensor.lr_temp", "21.0")
    hass.states.async_set("sensor.br_temp", "20.0")
    proxy._sensor_states["sensor.br_temp"] = State("sensor.br_temp", "20.0")

    hass.states.async_set("sensor.lr_humidity", "42")
    proxy._sensor_humidity_states["sensor.lr_humidity"] = State(
        "sensor.lr_humidity", "42"
    )

    assert proxy.current_humidity == 42
    assert proxy.extra_state_attributes[ATTR_ACTIVE_HUMIDITY_SENSOR] == "Living Room"
    assert (
        proxy.extra_state_attributes[ATTR_ACTIVE_HUMIDITY_SENSOR_ENTITY_ID]
        == "sensor.lr_humidity"
    )

    # Switch preset to Bedroom (no humidity sensor)
    await proxy.async_set_preset_mode("Bedroom")

    assert proxy.current_humidity == 55  # Falls back to physical thermostat
    assert (
        proxy.extra_state_attributes[ATTR_ACTIVE_HUMIDITY_SENSOR]
        == proxy._physical_sensor_name
    )
    assert (
        proxy.extra_state_attributes[ATTR_ACTIVE_HUMIDITY_SENSOR_ENTITY_ID]
        == proxy._real_entity_id
    )


@pytest.mark.asyncio
async def test_async_set_humidity(hass: HomeAssistant):
    """Test setting target humidity and range clamping."""
    proxy = create_proxy_with_humidity(hass)

    await proxy.async_set_humidity(45)
    assert proxy.target_humidity == 45

    # Clamp below min
    await proxy.async_set_humidity(20)
    assert proxy.target_humidity == 30

    # Clamp above max
    await proxy.async_set_humidity(110)
    assert proxy.target_humidity == 99


@pytest.mark.asyncio
async def test_humidity_state_restoration(hass: HomeAssistant):
    """Test that target humidity is restored from previous state."""
    proxy = create_proxy_with_humidity(hass)

    last_state = State(
        "climate.proxy",
        HVACMode.COOL,
        {
            "temperature": 21.0,
            "humidity": 48,
        },
    )

    with patch.object(proxy, "async_get_last_state", return_value=last_state):
        await proxy._async_restore_state()

    assert proxy.target_humidity == 48


@pytest.mark.asyncio
async def test_humidity_overdrive_cool_mode(hass: HomeAssistant):
    """Test humidity overdrive in COOL mode when temperature is satisfied but humidity is high."""
    proxy = create_proxy_with_humidity(hass)

    # Physical is idle and satisfied
    proxy._real_state = State(
        "climate.real",
        HVACMode.COOL,
        {
            "current_temperature": 22.0,
            "temperature": 22.0,
            "hvac_action": "idle",
            "target_temp_step": 1.0,
            "supported_features": ClimateEntityFeature.TARGET_TEMPERATURE,
        },
    )
    proxy._virtual_target_temperature = 22.0
    proxy._virtual_target_humidity = 50
    # Remote temp satisfied: 22.0 == target
    proxy._sensor_states["sensor.remote_temp"] = State("sensor.remote_temp", "22.0")
    # Remote humidity is 55 (> 50 + deadband 2.0)
    hass.states.async_set("sensor.remote_humidity", "55")
    proxy._sensor_humidity_states["sensor.remote_humidity"] = State(
        "sensor.remote_humidity", "55"
    )

    await proxy._async_realign_real_target_from_sensor()

    # Temperature delta is 0.0, but overdrive adjust is -1.0
    # Calculated real target = 22.0 - 1.0 = 21.0
    assert hass.services.async_call.called
    args, _ = hass.services.async_call.call_args
    assert args[0] == "climate"
    assert args[1] == "set_temperature"
    assert args[2]["temperature"] == 21.0
    assert proxy.extra_state_attributes[ATTR_HUMIDITY_OVERDRIVE_ACTIVE] is True


@pytest.mark.asyncio
async def test_humidity_overdrive_respects_max_overcool_limit(
    hass: HomeAssistant,
):
    """Test that humidity overdrive stops when temperature reaches target - max_humidity_overcool."""
    proxy = create_proxy_with_humidity(hass, max_humidity_overcool=2.0)

    proxy._real_state = State(
        "climate.real",
        HVACMode.COOL,
        {
            "current_temperature": 20.0,
            "temperature": 20.0,
            "hvac_action": "idle",
            "target_temp_step": 1.0,
            "supported_features": ClimateEntityFeature.TARGET_TEMPERATURE,
        },
    )
    proxy._virtual_target_temperature = 22.0
    proxy._virtual_target_humidity = 50

    # Remote temp is already at 20.0 (virtual_target 22.0 - max_overcool 2.0)
    proxy._sensor_states["sensor.remote_temp"] = State("sensor.remote_temp", "20.0")
    # Humidity is high
    hass.states.async_set("sensor.remote_humidity", "65")
    proxy._sensor_humidity_states["sensor.remote_humidity"] = State(
        "sensor.remote_humidity", "65"
    )

    await proxy._async_realign_real_target_from_sensor()

    # Overdrive should NOT be active because cooling past limit is forbidden
    assert proxy._active_overdrive_humidity is False
    assert proxy.extra_state_attributes[ATTR_HUMIDITY_OVERDRIVE_ACTIVE] is False


@pytest.mark.asyncio
async def test_no_humidity_overdrive_without_remote_humidity_sensor(
    hass: HomeAssistant,
):
    """Test all-or-nothing rule: preset without remote humidity sensor never triggers humidity overdrive."""
    sensors = [
        {
            CONF_SENSOR_NAME: "Temp Only",
            CONF_SENSOR_ENTITY_ID: "sensor.remote_temp",
            CONF_SENSOR_HUMIDITY_ENTITY_ID: None,
        }
    ]
    proxy = create_proxy_with_humidity(
        hass, sensors=sensors, default_sensor="Temp Only"
    )

    # Real thermostat has high humidity (75%) and is idle
    proxy._real_state = State(
        "climate.real",
        HVACMode.COOL,
        {
            "current_temperature": 22.0,
            "temperature": 22.0,
            "current_humidity": 75,
            "hvac_action": "idle",
            "target_temp_step": 1.0,
            "supported_features": ClimateEntityFeature.TARGET_TEMPERATURE,
        },
    )
    proxy._virtual_target_temperature = 22.0
    proxy._virtual_target_humidity = 50
    proxy._sensor_states["sensor.remote_temp"] = State("sensor.remote_temp", "22.0")

    await proxy._async_realign_real_target_from_sensor()

    # Should NOT trigger humidity overdrive
    assert proxy._active_overdrive_humidity is False
    assert proxy.extra_state_attributes[ATTR_HUMIDITY_OVERDRIVE_ACTIVE] is False


@pytest.mark.asyncio
async def test_humidity_sensor_state_change_listener(hass: HomeAssistant):
    """Test that state change event on humidity sensor triggers proxy update."""
    proxy = create_proxy_with_humidity(hass)

    event = MagicMock()
    event.data = {
        "entity_id": "sensor.remote_humidity",
        "new_state": State("sensor.remote_humidity", "60"),
    }

    with patch.object(proxy, "_schedule_target_realign") as mock_schedule:
        proxy._async_handle_humidity_sensor_state_event(event)
        assert proxy._sensor_humidity_states["sensor.remote_humidity"].state == "60"
        mock_schedule.assert_called_once_with(trigger_source="humidity")
        assert proxy.async_write_ha_state.called


@pytest.mark.asyncio
async def test_config_flow_with_humidity_sensor(hass: HomeAssistant):
    """Test config flow adding sensor with humidity entity id."""
    with patch("homeassistant.core.ServiceRegistry.async_call", return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"name": "Proxy", "thermostat": "climate.real"},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"action": "add_sensor"},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "name": "Living Room",
                "entity_id": "sensor.lr_temp",
                "humidity_entity_id": "sensor.lr_humidity",
                "add_another": False,
            },
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "manage_sensors"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"action": "finish"},
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "finalize"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "cooldown_period": 1800,
                "physical_sensor_name": "Physical",
                "max_humidity_overcool": 1.5,
                "default_target_humidity": 45,
            },
        )
        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert (
            result["data"][CONF_SENSORS][0][CONF_SENSOR_HUMIDITY_ENTITY_ID]
            == "sensor.lr_humidity"
        )
        assert result["data"][CONF_MAX_HUMIDITY_OVERCOOL] == 1.5
        assert result["data"][CONF_DEFAULT_TARGET_HUMIDITY] == 45
