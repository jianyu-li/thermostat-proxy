"""Tests for a separate measurement at the physical thermostat's location."""

from unittest.mock import MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thermostat_proxy.climate import (
    PLATFORM_SCHEMA,
    CustomThermostatEntity,
)
from custom_components.thermostat_proxy.const import (
    CONF_PHYSICAL_TEMPERATURE_SENSOR,
    DOMAIN,
)
from custom_components.thermostat_proxy.helpers import extract_entity_config
from homeassistant.components.climate import HVACMode
from homeassistant.core import State
from homeassistant.data_entry_flow import FlowResultType


def create_proxy(hass):
    """Create a proxy with a separate, precise physical measurement."""
    proxy = CustomThermostatEntity(
        hass=hass,
        name="Test Proxy",
        real_thermostat="climate.real",
        sensors=[{"name": "Remote", "entity_id": "sensor.remote"}],
        default_sensor="Remote",
        unique_id="test",
        physical_sensor_name="Physical",
        use_last_active_sensor=False,
        physical_temperature_sensor="sensor.physical",
        overdrive_offset=0.0,
    )
    proxy._real_state = State(
        "climate.real",
        HVACMode.HEAT,
        {
            "current_temperature": 71.0,
            "temperature": 70.0,
            "temperature_unit": "°F",
            "target_temp_step": 0.1,
        },
    )
    proxy._update_real_temperature_limits()
    proxy._temperature_unit = "°F"
    proxy._sensor_states["sensor.remote"] = State("sensor.remote", "69.8")
    proxy.async_write_ha_state = MagicMock()
    proxy._schedule_target_realign = MagicMock()
    return proxy


@pytest.mark.parametrize("preset", ["Remote", "Physical"])
@pytest.mark.asyncio
async def test_precise_reference_for_every_preset(hass, preset):
    proxy = create_proxy(hass)
    hass.states.async_set("sensor.physical", "70.52", {"unit_of_measurement": "°F"})
    proxy._selected_sensor_name = preset
    assert proxy._get_real_current_temperature() == 70.52
    assert proxy._get_active_sensor_temperature() == (
        70.52 if preset == "Physical" else 69.8
    )


@pytest.mark.parametrize(
    "value", [None, "unknown", "unavailable", "bad", "nan", "inf", "-inf"]
)
@pytest.mark.asyncio
async def test_invalid_measurement_falls_back(hass, value):
    proxy = create_proxy(hass)
    if value is not None:
        hass.states.async_set("sensor.physical", value, {"unit_of_measurement": "°F"})
    assert proxy._get_real_current_temperature() == 71.0


@pytest.mark.parametrize("unit", [None, "invalid"])
@pytest.mark.asyncio
async def test_invalid_units_fall_back(hass, unit):
    proxy = create_proxy(hass)
    hass.states.async_set("sensor.physical", "70.52", {"unit_of_measurement": unit})
    assert proxy._get_real_current_temperature() == 71.0


@pytest.mark.parametrize(
    "source,target,value,expected",
    [("°C", "°F", "21.4", 70.52), ("°F", "°C", "70.52", 21.4)],
)
@pytest.mark.asyncio
async def test_unit_conversion(hass, source, target, value, expected):
    proxy = create_proxy(hass)
    proxy._temperature_unit = target
    hass.states.async_set("sensor.physical", value, {"unit_of_measurement": source})
    assert proxy._get_real_current_temperature() == pytest.approx(expected)


@pytest.mark.parametrize("state", ["unknown", "unavailable"])
@pytest.mark.asyncio
async def test_sensor_does_not_mask_thermostat_outage(hass, state):
    proxy = create_proxy(hass)
    hass.states.async_set("sensor.physical", "70.52", {"unit_of_measurement": "°F"})
    proxy._real_state = State("climate.real", state)
    assert proxy._get_real_current_temperature() is None


@pytest.mark.asyncio
async def test_measurement_listener_and_cleanup(hass):
    proxy = create_proxy(hass)
    await proxy._async_subscribe_to_states()
    hass.states.async_set("sensor.physical", "70.52", {"unit_of_measurement": "°F"})
    await hass.async_block_till_done()
    proxy._schedule_target_realign.assert_called_once_with(trigger_source="real")
    assert proxy._selected_sensor_name == "Remote"
    assert proxy._virtual_target_temperature is None
    assert not hass.services.async_call.called
    await proxy.async_will_remove_from_hass()
    proxy._schedule_target_realign.reset_mock()
    hass.states.async_set("sensor.physical", "70.7", {"unit_of_measurement": "°F"})
    await hass.async_block_till_done()
    proxy._schedule_target_realign.assert_not_called()


def test_config_extraction_and_yaml_validation():
    assert extract_entity_config({})["physical_temperature_sensor"] is None
    cfg = {
        "platform": DOMAIN,
        "thermostat": "climate.real",
        "sensors": [{"name": "Remote", "entity_id": "sensor.remote"}],
        CONF_PHYSICAL_TEMPERATURE_SENSOR: "sensor.physical",
    }
    validated = PLATFORM_SCHEMA(cfg)
    assert (
        extract_entity_config(validated)["physical_temperature_sensor"]
        == "sensor.physical"
    )


@pytest.mark.parametrize("selected", ["sensor.physical", None])
@pytest.mark.asyncio
async def test_options_save_and_clear(hass, selected):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "name": "Proxy",
            "thermostat": "climate.real",
            "sensors": [{"name": "Remote", "entity_id": "sensor.remote"}],
        },
        options={CONF_PHYSICAL_TEMPERATURE_SENSOR: "sensor.previous"},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    fields = {str(key): key for key in result["data_schema"].schema}
    assert (
        fields[CONF_PHYSICAL_TEMPERATURE_SENSOR].description["suggested_value"]
        == "sensor.previous"
    )
    user_input = {CONF_PHYSICAL_TEMPERATURE_SENSOR: selected} if selected else {}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=user_input
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PHYSICAL_TEMPERATURE_SENSOR] == selected


@pytest.mark.asyncio
async def test_offset_uses_precise_reference(hass):
    """A remote target is offset against the precise physical measurement."""
    proxy = create_proxy(hass)
    proxy._virtual_target_temperature = 70.0
    proxy._min_temp = 50.0
    proxy._max_temp = 90.0
    hass.states.async_set("sensor.physical", "70.52", {"unit_of_measurement": "°F"})
    await proxy._async_realign_real_target_from_sensor(trigger_source="sensor")
    args = hass.services.async_call.call_args
    assert args.args[0:2] == ("climate", "set_temperature")
    assert args.args[2]["temperature"] == pytest.approx(70.7)


def test_reconfigure_updates_existing_option():
    """An old options value must not override a newly reconfigured sensor."""
    from custom_components.thermostat_proxy.config_flow import _sync_reconfigure_options

    entry = MockConfigEntry(
        domain=DOMAIN, options={CONF_PHYSICAL_TEMPERATURE_SENSOR: "sensor.previous"}
    )
    updated = _sync_reconfigure_options(
        entry, {CONF_PHYSICAL_TEMPERATURE_SENSOR: "sensor.new"}
    )
    assert updated[CONF_PHYSICAL_TEMPERATURE_SENSOR] == "sensor.new"


@pytest.mark.asyncio
async def test_physical_temperature_sensor_health_and_unavailable_entities(hass):
    proxy = create_proxy(hass)
    hass.states.async_set("sensor.physical", "unavailable")
    assert proxy._get_real_current_temperature() == 71.0
    assert proxy._entity_health.get("sensor.physical") is False
    assert "sensor.physical" in proxy.extra_state_attributes["unavailable_entities"]

    hass.states.async_set("sensor.physical", "70.52", {"unit_of_measurement": "°F"})
    assert proxy._get_real_current_temperature() == 70.52
    assert proxy._entity_health.get("sensor.physical") is True
    assert "sensor.physical" not in proxy.extra_state_attributes["unavailable_entities"]


@pytest.mark.asyncio
async def test_physical_preset_display_precision_with_physical_temperature_sensor(hass):
    proxy = create_proxy(hass)
    proxy._real_state = State(
        "climate.real",
        HVACMode.HEAT,
        {
            "current_temperature": 71.0,
            "temperature": 70.0,
            "temperature_unit": "°F",
            "target_temp_step": 1.0,
        },
    )
    proxy._update_real_temperature_limits()
    hass.states.async_set("sensor.physical", "70.52", {"unit_of_measurement": "°F"})
    proxy._get_real_current_temperature()
    proxy._selected_sensor_name = "Physical"
    assert proxy.precision == 0.1
    assert proxy.target_temperature_step == 1.0


@pytest.mark.asyncio
async def test_physical_preset_respects_sensor_change_threshold_on_physical_sensor_events(
    hass,
):
    proxy = create_proxy(hass)
    proxy._selected_sensor_name = "Physical"
    await proxy._async_subscribe_to_states()
    hass.states.async_set("sensor.physical", "70.52", {"unit_of_measurement": "°F"})
    await hass.async_block_till_done()
    proxy._schedule_target_realign.assert_called_once_with(trigger_source="sensor")
    await proxy.async_will_remove_from_hass()


@pytest.mark.asyncio
async def test_options_rejects_remote_sensor_as_physical_temperature_sensor(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "name": "Proxy",
            "thermostat": "climate.real",
            "sensors": [{"name": "Remote", "entity_id": "sensor.remote"}],
        },
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={CONF_PHYSICAL_TEMPERATURE_SENSOR: "sensor.remote"},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "duplicate_sensor_entity"}
