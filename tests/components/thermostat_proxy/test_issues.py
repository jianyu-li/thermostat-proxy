"""Tests simulating scenarios in GitHub issues #31, #32, #65, #76, and #81."""

import time
from unittest.mock import MagicMock

import pytest

from custom_components.thermostat_proxy.climate import CustomThermostatEntity
from homeassistant.components.climate import ClimateEntityFeature, HVACMode
from homeassistant.components.climate.const import SERVICE_SET_TEMPERATURE
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import State


@pytest.mark.parametrize(
    "hvac_mode", [HVACMode.HEAT, HVACMode.COOL, HVACMode.HEAT_COOL, HVACMode.AUTO]
)
@pytest.mark.asyncio
async def test_issue_31_decimal_current_temperature(hass, hvac_mode):
    """Test that a remote sensor with decimals displays decimals for current temperature across all modes."""
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

    hass.states.async_set(
        "climate.real",
        hvac_mode,
        {
            "current_temperature": 20.0,
            "temperature": 22.0,
            "target_temp_low": 20.0,
            "target_temp_high": 24.0,
            "target_temp_step": 1.0,
            "supported_features": (
                ClimateEntityFeature.TARGET_TEMPERATURE
                | ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
            ),
        },
    )
    proxy._real_state = hass.states.get("climate.real")
    proxy._update_real_temperature_limits()

    proxy._temperature_unit = "°C"
    proxy._sensor_states["sensor.remote"] = State("sensor.remote", "22.8")
    proxy._sensor_precisions["sensor.remote"] = 0.1
    proxy._selected_sensor_name = "Remote"
    proxy.async_write_ha_state = MagicMock()

    # Check that the precision property returns 0.1 (not 1.0) so that HA frontend does not truncate/cut the decimals to 22.
    assert proxy.precision == 0.1


@pytest.mark.parametrize(
    "hvac_mode", [HVACMode.HEAT, HVACMode.COOL, HVACMode.HEAT_COOL, HVACMode.AUTO]
)
@pytest.mark.asyncio
async def test_issue_32_floor_rounding_thermostat_loop(hass, hvac_mode):
    """Test floor-rounding external change suppression across all HVAC modes."""
    proxy = CustomThermostatEntity(
        hass=hass,
        name="Test Proxy",
        real_thermostat="climate.real",
        sensors=[{"name": "Remote", "entity_id": "sensor.remote"}],
        default_sensor="Remote",
        unique_id="123",
        physical_sensor_name="Physical",
        use_last_active_sensor=False,
        disable_auto_switch=False,
    )

    # Physical thermostat MTS300 in Celsius mode, target_temp_step = 1.0 (Celsius)
    # The proxy is operating in Fahrenheit, target_temp_step = 1.8 (Fahrenheit)
    hass.states.async_set(
        "climate.real",
        hvac_mode,
        {
            "current_temperature": 75.0,
            "temperature": 73.4,  # floored Celsius value 23.0°C converted to Fahrenheit
            "target_temp_low": 68.0,
            "target_temp_high": 75.0,
            "target_temp_step": 1.8,
            "supported_features": (
                ClimateEntityFeature.TARGET_TEMPERATURE
                | ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
            ),
        },
    )
    proxy._real_state = hass.states.get("climate.real")
    proxy._update_real_temperature_limits()

    proxy._temperature_unit = "°F"
    proxy._sensor_states["sensor.remote"] = State("sensor.remote", "76.0")
    proxy._sensor_precisions["sensor.remote"] = 0.1
    proxy._selected_sensor_name = "Remote"
    proxy._virtual_target_temperature = 76.0
    proxy._target_temp_step = 1.8
    proxy.async_write_ha_state = MagicMock()

    # Proxy adjusts target and sends 74.5°F to real thermostat.
    proxy._last_real_target_temp = 74.5
    proxy._recent_real_target_requests = [(74.5, time.monotonic())]

    # Now, outside the post-write grace period (15 seconds later),
    # the MTS300 reports the floored value: 73.4°F (23.0°C)
    proxy._last_real_write_time = time.monotonic() - 15.0

    # Simulate receiving the state event with target = 73.4
    event = MagicMock()
    event.data = {
        "old_state": State(
            "climate.real",
            hvac_mode,
            {
                "current_temperature": 75.0,
                "temperature": 74.5,
                "target_temp_step": 1.8,
                "supported_features": (
                    ClimateEntityFeature.TARGET_TEMPERATURE
                    | ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
                ),
            },
        ),
        "new_state": State(
            "climate.real",
            hvac_mode,
            {
                "current_temperature": 75.0,
                "temperature": 73.4,
                "target_temp_step": 1.8,
                "supported_features": (
                    ClimateEntityFeature.TARGET_TEMPERATURE
                    | ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
                ),
            },
        ),
    }
    proxy._async_handle_real_state_event(event)

    # Check if the proxy switched to the physical sensor due to false external change detection.
    # If the bug is present, it will switch to "Physical". We assert it should NOT switch (preset remains "Remote").
    assert proxy._selected_sensor_name == "Remote"


@pytest.mark.asyncio
async def test_issue_65_trv_snapped_readback_no_upward_drift(hass):
    """Test that a TRV snapping setpoints doesn't cause upward temperature drift."""
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

    hass.states.async_set(
        "climate.real",
        HVACMode.HEAT,
        {
            "current_temperature": 20.7,
            "temperature": 20.0,
            "target_temp_step": 0.1,
            "hvac_action": "idle",
            "supported_features": ClimateEntityFeature.TARGET_TEMPERATURE,
        },
    )
    proxy._real_state = hass.states.get("climate.real")
    proxy._update_real_temperature_limits()

    proxy._temperature_unit = "°C"
    proxy._sensor_states["sensor.remote"] = State("sensor.remote", "19.8")
    proxy._sensor_precisions["sensor.remote"] = 0.1
    proxy._selected_sensor_name = "Remote"
    proxy._virtual_target_temperature = 20.0
    proxy._target_temp_step = 0.1
    proxy.async_write_ha_state = MagicMock()

    # Initial realignment from sensor: overdrive engages (+1.0°C) and requests 21.9°C
    # 20.7 + (20.0 - 19.8) + 1.0 = 21.9
    await proxy._async_realign_real_target_from_sensor(trigger_source="sensor")

    assert proxy._active_overdrive_heat is True
    assert proxy._last_real_target_temp == 21.9

    # Simulate TRV snapping 21.9°C to 21.5°C and reporting temperature=21.5 within grace period
    proxy._last_real_write_time = time.monotonic() - 10.0
    old_state = proxy._real_state
    new_state = State(
        "climate.real",
        HVACMode.HEAT,
        {
            "current_temperature": 20.7,
            "temperature": 21.5,
            "target_temp_step": 0.1,
            "hvac_action": "idle",
            "supported_features": ClimateEntityFeature.TARGET_TEMPERATURE,
        },
    )
    hass.states.async_set(
        "climate.real",
        new_state.state,
        new_state.attributes,
    )
    event = MagicMock()
    event.data = {"old_state": old_state, "new_state": new_state}
    proxy._real_state = new_state
    proxy._async_handle_real_state_event(event)

    assert proxy._selected_sensor_name == "Remote"
    assert proxy._virtual_target_temperature == 20.0

    # Simulate cooldown / timeout expiring (135s elapsed since write)
    hass.services.async_call.reset_mock()
    proxy._last_real_write_time = time.monotonic() - 135.0

    # Realign while sensor is still 19.8°C and real current is still 20.7°C
    await proxy._async_realign_real_target_from_sensor(trigger_source="sensor")

    # Proxy should recognize TRV is already at snapped target 21.5°C for commanded 21.9°C
    # and should NOT re-write 21.9°C
    set_temp_calls = [
        c
        for c in hass.services.async_call.call_args_list
        if c.args and len(c.args) >= 2 and c.args[1] == SERVICE_SET_TEMPERATURE
    ]
    assert len(set_temp_calls) == 0

    # Simulate TRV reporting temperature=21.5 again outside grace period (135s after write)
    # e.g. when current_temperature updates from 20.7 to 20.6
    proxy._last_real_write_time = time.monotonic() - 135.0
    old_state = proxy._real_state
    new_state = State(
        "climate.real",
        HVACMode.HEAT,
        {
            "current_temperature": 20.6,
            "temperature": 21.5,
            "target_temp_step": 0.1,
            "hvac_action": "idle",
            "supported_features": ClimateEntityFeature.TARGET_TEMPERATURE,
        },
    )
    hass.states.async_set(
        "climate.real",
        new_state.state,
        new_state.attributes,
    )
    event = MagicMock()
    event.data = {"old_state": old_state, "new_state": new_state}
    proxy._real_state = new_state
    proxy._async_handle_real_state_event(event)

    # Verify proxy does NOT treat 21.5°C as an external change
    assert proxy._selected_sensor_name == "Remote"
    assert proxy._virtual_target_temperature == 20.0


@pytest.mark.asyncio
async def test_issue_65_no_overdrive_on_physical_preset(hass):
    """Test that overdrive does not engage when physical sensor preset is active."""
    proxy = CustomThermostatEntity(
        hass=hass,
        name="Test Proxy",
        real_thermostat="climate.real",
        sensors=[{"name": "Remote", "entity_id": "sensor.remote"}],
        default_sensor="Physical",
        unique_id="123",
        physical_sensor_name="Physical",
        use_last_active_sensor=False,
    )

    hass.states.async_set(
        "climate.real",
        HVACMode.HEAT,
        {
            "current_temperature": 20.0,
            "temperature": 21.5,
            "target_temp_step": 0.5,
            "hvac_action": "idle",
            "supported_features": ClimateEntityFeature.TARGET_TEMPERATURE,
        },
    )
    proxy._real_state = hass.states.get("climate.real")
    proxy._update_real_temperature_limits()

    proxy._temperature_unit = "°C"
    proxy._selected_sensor_name = "Physical"
    proxy._virtual_target_temperature = 21.5
    proxy.async_write_ha_state = MagicMock()
    hass.services.async_call.reset_mock()

    await proxy._async_realign_real_target_from_sensor(trigger_source="real")

    assert proxy._active_overdrive_heat is False
    set_temp_calls = [
        c
        for c in hass.services.async_call.call_args_list
        if c.args and len(c.args) >= 2 and c.args[1] == SERVICE_SET_TEMPERATURE
    ]
    if set_temp_calls:
        target = set_temp_calls[0].args[2].get("temperature")
        assert target != 22.5


@pytest.mark.asyncio
async def test_issue_65_overdrive_disabled_when_offset_zero(hass):
    """Test that overdrive is disabled when overdrive_offset is 0.0."""
    proxy = CustomThermostatEntity(
        hass=hass,
        name="Test Proxy",
        real_thermostat="climate.real",
        sensors=[{"name": "Remote", "entity_id": "sensor.remote"}],
        default_sensor="Remote",
        unique_id="123",
        physical_sensor_name="Physical",
        use_last_active_sensor=False,
        overdrive_offset=0.0,
    )

    hass.states.async_set(
        "climate.real",
        HVACMode.HEAT,
        {
            "current_temperature": 20.5,
            "temperature": 20.5,
            "target_temp_step": 0.5,
            "hvac_action": "idle",
            "supported_features": ClimateEntityFeature.TARGET_TEMPERATURE,
        },
    )
    proxy._real_state = hass.states.get("climate.real")
    proxy._update_real_temperature_limits()

    proxy._temperature_unit = "°C"
    proxy._sensor_states["sensor.remote"] = State("sensor.remote", "19.0")
    proxy._sensor_precisions["sensor.remote"] = 0.1
    proxy._selected_sensor_name = "Remote"
    proxy._virtual_target_temperature = 20.0
    proxy.async_write_ha_state = MagicMock()
    hass.services.async_call.reset_mock()

    await proxy._async_realign_real_target_from_sensor(trigger_source="sensor")

    assert proxy._active_overdrive_heat is False
    assert proxy._last_real_target_temp == 21.5
    set_temp_calls = [
        c
        for c in hass.services.async_call.call_args_list
        if c.args and len(c.args) >= 2 and c.args[1] == SERVICE_SET_TEMPERATURE
    ]
    assert len(set_temp_calls) == 1
    assert set_temp_calls[0].args[2].get("temperature") == 21.5


@pytest.mark.parametrize("state", [HVACMode.OFF, "unavailable", "unknown"])
@pytest.mark.asyncio
async def test_issue_76_skip_realign_when_physical_thermostat_off_or_unavailable(
    hass, state
):
    """Test that target realignment is skipped while physical thermostat is off or unavailable."""
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
    proxy.entity_id = "climate.test_proxy"

    # Set up climate.real in HEAT mode initially
    hass.states.async_set(
        "climate.real",
        HVACMode.HEAT,
        {
            "current_temperature": 20.0,
            "temperature": 20.0,
            "target_temp_step": 0.5,
            "hvac_action": "idle",
            "supported_features": ClimateEntityFeature.TARGET_TEMPERATURE,
        },
    )
    proxy._real_state = hass.states.get("climate.real")
    proxy._update_real_temperature_limits()

    proxy._temperature_unit = "°C"
    proxy._sensor_states["sensor.remote"] = State("sensor.remote", "19.0")
    proxy._sensor_precisions["sensor.remote"] = 0.1
    proxy._selected_sensor_name = "Remote"
    proxy._virtual_target_temperature = 22.0
    proxy._target_temp_step = 0.5
    proxy.async_write_ha_state = MagicMock()
    proxy._last_acted_sensor_temp = None

    # Verify cooldown callback is cancelled and cleared if pending when entering `state`
    mock_cooldown_unsub = MagicMock()
    proxy._cooldown_timer_unsub = mock_cooldown_unsub

    # Transition climate.real from HVACMode.HEAT to `state` via _async_handle_real_state_event
    old_state = proxy._real_state
    new_attributes = (
        {
            "current_temperature": 20.0,
            "temperature": 20.0,
            "target_temp_step": 0.5,
            "supported_features": ClimateEntityFeature.TARGET_TEMPERATURE,
        }
        if state not in ("unavailable", "unknown")
        else {}
    )
    hass.states.async_set("climate.real", state, new_attributes)
    new_state = hass.states.get("climate.real")

    event = MagicMock()
    event.data = {"old_state": old_state, "new_state": new_state}
    proxy._async_handle_real_state_event(event)
    await hass.async_block_till_done()

    mock_cooldown_unsub.assert_called_once()
    assert proxy._cooldown_timer_unsub is None

    # Assert climate.set_temperature was NOT called
    set_temp_calls = [
        c
        for c in hass.services.async_call.call_args_list
        if c.args and len(c.args) >= 2 and c.args[1] == SERVICE_SET_TEMPERATURE
    ]
    assert len(set_temp_calls) == 0

    # Trigger _async_realign_real_target_from_sensor for each trigger source
    for trigger_source in ("sensor", "real", "preset"):
        mock_unsub = MagicMock()
        proxy._cooldown_timer_unsub = mock_unsub

        await proxy._async_realign_real_target_from_sensor(
            trigger_source=trigger_source
        )

        mock_unsub.assert_called_once()
        assert proxy._cooldown_timer_unsub is None
        assert proxy._last_acted_sensor_temp is None

    # Verify realignment without pending cooldown also leaves timer None and skips write
    await proxy._async_realign_real_target_from_sensor(trigger_source="sensor")
    assert proxy._cooldown_timer_unsub is None
    assert proxy._last_acted_sensor_temp is None

    # Assert climate.set_temperature was NOT called throughout
    set_temp_calls = [
        c
        for c in hass.services.async_call.call_args_list
        if c.args and len(c.args) >= 2 and c.args[1] == SERVICE_SET_TEMPERATURE
    ]
    assert len(set_temp_calls) == 0


@pytest.mark.asyncio
async def test_issue_76_realign_resumes_when_physical_thermostat_turns_on(hass):
    """Test that target realignment resumes when physical thermostat turns back on."""
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
    proxy.entity_id = "climate.test_proxy"

    # Start with climate.real in HVACMode.OFF, remote sensor 19.0°C, virtual target 22.0°C
    hass.states.async_set(
        "climate.real",
        HVACMode.OFF,
        {
            "current_temperature": 20.0,
            "temperature": 20.0,
            "target_temp_step": 0.5,
            "hvac_action": "off",
            "supported_features": ClimateEntityFeature.TARGET_TEMPERATURE,
        },
    )
    proxy._real_state = hass.states.get("climate.real")
    proxy._update_real_temperature_limits()

    proxy._temperature_unit = "°C"
    proxy._sensor_states["sensor.remote"] = State("sensor.remote", "19.0")
    proxy._sensor_precisions["sensor.remote"] = 0.1
    proxy._selected_sensor_name = "Remote"
    proxy._virtual_target_temperature = 22.0
    proxy._target_temp_step = 0.5
    proxy.async_write_ha_state = MagicMock()
    hass.services.async_call.reset_mock()

    # Simulate remote sensor changing to 18.5°C while off -> verify no set_temperature call is made
    sensor_event = MagicMock()
    sensor_event.data = {
        "entity_id": "sensor.remote",
        "new_state": State("sensor.remote", "18.5"),
    }
    proxy._async_handle_sensor_state_event(sensor_event)
    await hass.async_block_till_done()

    set_temp_calls = [
        c
        for c in hass.services.async_call.call_args_list
        if c.args and len(c.args) >= 2 and c.args[1] == SERVICE_SET_TEMPERATURE
    ]
    assert len(set_temp_calls) == 0

    # Transition climate.real from HVACMode.OFF to HVACMode.HEAT (current_temperature=20.0, temperature=20.0)
    old_state = proxy._real_state
    new_attrs = {
        "current_temperature": 20.0,
        "temperature": 20.0,
        "target_temp_step": 0.5,
        "hvac_action": "idle",
        "supported_features": ClimateEntityFeature.TARGET_TEMPERATURE,
    }
    hass.states.async_set("climate.real", HVACMode.HEAT, new_attrs)
    new_state = hass.states.get("climate.real")

    event = MagicMock()
    event.data = {"old_state": old_state, "new_state": new_state}
    proxy._async_handle_real_state_event(event)
    await hass.async_block_till_done()

    # Verify that automatic target realignment now fires and calls climate.set_temperature with expected offset target
    # Remote sensor 18.5°C, virtual target 22.0°C -> delta +3.5°C
    # Real current 20.0°C + delta 3.5°C = 23.5°C + 1.0°C overdrive = 24.5°C
    set_temp_calls = [
        c
        for c in hass.services.async_call.call_args_list
        if c.args and len(c.args) >= 2 and c.args[1] == SERVICE_SET_TEMPERATURE
    ]
    assert len(set_temp_calls) == 1
    assert set_temp_calls[0].args[2].get("temperature") == 24.5
    assert proxy._last_real_target_temp == 24.5


def _issue_81_set_temp_calls(hass):
    """Return all climate.set_temperature service calls recorded on hass."""
    return [
        c
        for c in hass.services.async_call.call_args_list
        if c.args and len(c.args) >= 2 and c.args[1] == SERVICE_SET_TEMPERATURE
    ]


def _create_issue_81_proxy(
    hass,
    *,
    hvac_mode: HVACMode = HVACMode.HEAT,
    real_attrs: dict,
    remote_temp: str = "22.2",
    disable_auto_switch: bool = True,
    cooldown_period: int = 0,
    sensor_change_threshold: float = 0.0,
) -> CustomThermostatEntity:
    """Create and initialize a CustomThermostatEntity for Issue #81 tests."""
    proxy = CustomThermostatEntity(
        hass=hass,
        name="Playroom Proxy",
        real_thermostat="climate.playroom",
        sensors=[{"name": "Remote", "entity_id": "sensor.remote"}],
        default_sensor="Remote",
        unique_id="issue-81",
        physical_sensor_name="Physical Entity",
        use_last_active_sensor=False,
        disable_auto_switch=disable_auto_switch,
        cooldown_period=cooldown_period,
        sensor_change_threshold=sensor_change_threshold,
    )
    proxy.entity_id = "climate.playroom_proxy"
    hass.states.async_set("climate.playroom", hvac_mode, real_attrs)
    proxy._real_state = hass.states.get("climate.playroom")
    proxy._update_real_temperature_limits()
    proxy._temperature_unit = "°C"
    proxy._sensor_states["sensor.remote"] = State("sensor.remote", remote_temp)
    proxy._sensor_precisions["sensor.remote"] = 0.1
    proxy._update_sensor_health_from_state(
        "sensor.remote", proxy._sensor_states["sensor.remote"]
    )
    proxy._selected_sensor_name = "Remote"
    proxy.async_write_ha_state = MagicMock()
    return proxy


@pytest.mark.parametrize("disable_auto_switch", [True, False])
@pytest.mark.asyncio
async def test_issue_81_optimistic_revert_during_sensor_fallback_single_setpoint(
    hass, disable_auto_switch
):
    """Stale optimistic revert during sensor fallback must not inflate virtual_target."""
    base_attrs = {
        "current_temperature": 30.6,
        "temperature": 30.0,
        "target_temp_step": 1.0,
        "min_temp": 5.0,
        "max_temp": 35.0,
        "hvac_action": "idle",
        "supported_features": (
            ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
        ),
    }
    proxy = _create_issue_81_proxy(
        hass,
        real_attrs=base_attrs,
        remote_temp="22.2",
        disable_auto_switch=disable_auto_switch,
    )
    proxy._virtual_target_temperature = 22.0
    proxy._last_real_target_temp = 30.0
    hass.services.async_call.reset_mock()

    # 1. Remote sensor goes unavailable -> fallback writes 22.0
    sensor_event = MagicMock()
    sensor_event.data = {
        "entity_id": "sensor.remote",
        "new_state": State("sensor.remote", STATE_UNAVAILABLE),
    }
    proxy._async_handle_sensor_state_event(sensor_event)
    await hass.async_block_till_done()

    assert proxy._is_in_sensor_fallback() is True
    calls = _issue_81_set_temp_calls(hass)
    assert len(calls) == 1
    assert calls[0].args[2]["temperature"] == 22.0

    # 2. Optimistic integration echo (30.0 -> 22.0) consumes pending request
    old_state = proxy._real_state
    optimistic_attrs = {**base_attrs, "temperature": 22.0}
    hass.states.async_set("climate.playroom", HVACMode.HEAT, optimistic_attrs)
    real_event = MagicMock()
    real_event.data = {
        "old_state": old_state,
        "new_state": hass.states.get("climate.playroom"),
    }
    proxy._async_handle_real_state_event(real_event)
    await hass.async_block_till_done()
    assert proxy._recent_real_target_requests == []

    # 3. Past 45s grace period, hub poll returns unchanged 30.0 (command dropped)
    proxy._last_real_write_time = time.monotonic() - 120.0
    hass.services.async_call.reset_mock()
    old_state = proxy._real_state
    reverted_attrs = {**base_attrs, "current_temperature": 30.5, "temperature": 30.0}
    hass.states.async_set("climate.playroom", HVACMode.HEAT, reverted_attrs)
    revert_event = MagicMock()
    revert_event.data = {
        "old_state": old_state,
        "new_state": hass.states.get("climate.playroom"),
    }
    proxy._async_handle_real_state_event(revert_event)
    await hass.async_block_till_done()

    assert proxy._virtual_target_temperature == 22.0
    assert proxy._selected_sensor_name == "Remote"
    retry_calls = _issue_81_set_temp_calls(hass)
    assert len(retry_calls) == 1
    assert retry_calls[0].args[2]["temperature"] == 22.0

    # 4. Physical thermostat reflects 22.0, then remote sensor recovers to 22.2
    hass.states.async_set(
        "climate.playroom",
        HVACMode.HEAT,
        {**reverted_attrs, "temperature": 22.0},
    )
    proxy._real_state = hass.states.get("climate.playroom")
    proxy._last_real_target_temp = 22.0
    hass.services.async_call.reset_mock()

    recovery_event = MagicMock()
    recovery_event.data = {
        "entity_id": "sensor.remote",
        "new_state": State("sensor.remote", "22.2"),
    }
    proxy._async_handle_sensor_state_event(recovery_event)
    await hass.async_block_till_done()

    assert proxy._virtual_target_temperature == 22.0
    assert proxy._selected_sensor_name == "Remote"
    assert proxy._is_in_sensor_fallback() is False
    assert proxy._awaiting_fallback_recovery is False
    recovery_calls = _issue_81_set_temp_calls(hass)
    assert len(recovery_calls) == 1
    assert recovery_calls[0].args[2]["temperature"] == 30.0


@pytest.mark.parametrize("disable_auto_switch", [True, False])
@pytest.mark.asyncio
async def test_issue_81_optimistic_revert_during_sensor_fallback_dual_setpoint(
    hass, disable_auto_switch
):
    """Stale optimistic revert in dual-setpoint fallback must not inflate targets."""
    base_attrs = {
        "current_temperature": 28.0,
        "target_temp_low": 28.0,
        "target_temp_high": 32.0,
        "target_temp_step": 1.0,
        "min_temp": 10.0,
        "max_temp": 35.0,
        "hvac_action": "idle",
        "supported_features": (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
            | ClimateEntityFeature.PRESET_MODE
        ),
    }
    proxy = _create_issue_81_proxy(
        hass,
        hvac_mode=HVACMode.HEAT_COOL,
        real_attrs=base_attrs,
        remote_temp="20.0",
        disable_auto_switch=disable_auto_switch,
    )
    proxy._virtual_target_temperature_low = 20.0
    proxy._virtual_target_temperature_high = 24.0
    proxy._last_real_target_temp_low = 28.0
    proxy._last_real_target_temp_high = 32.0
    hass.services.async_call.reset_mock()

    # 1. Sensor goes unavailable -> fallback writes low=20.0, high=24.0
    sensor_event = MagicMock()
    sensor_event.data = {
        "entity_id": "sensor.remote",
        "new_state": State("sensor.remote", STATE_UNAVAILABLE),
    }
    proxy._async_handle_sensor_state_event(sensor_event)
    await hass.async_block_till_done()

    calls = _issue_81_set_temp_calls(hass)
    assert len(calls) == 1
    assert calls[0].args[2]["target_temp_low"] == 20.0
    assert calls[0].args[2]["target_temp_high"] == 24.0

    # 2. Optimistic state update consumes both pending requests
    old_state = proxy._real_state
    hass.states.async_set(
        "climate.playroom",
        HVACMode.HEAT_COOL,
        {**base_attrs, "target_temp_low": 20.0, "target_temp_high": 24.0},
    )
    real_event = MagicMock()
    real_event.data = {
        "old_state": old_state,
        "new_state": hass.states.get("climate.playroom"),
    }
    proxy._async_handle_real_state_event(real_event)
    await hass.async_block_till_done()
    assert proxy._recent_real_target_requests == []

    # 3. Past grace period, poll reverts 20.0/24.0 -> 28.0/32.0
    proxy._last_real_write_time = time.monotonic() - 120.0
    hass.services.async_call.reset_mock()
    old_state = proxy._real_state
    hass.states.async_set("climate.playroom", HVACMode.HEAT_COOL, base_attrs)
    revert_event = MagicMock()
    revert_event.data = {
        "old_state": old_state,
        "new_state": hass.states.get("climate.playroom"),
    }
    proxy._async_handle_real_state_event(revert_event)
    await hass.async_block_till_done()

    assert proxy._virtual_target_temperature_low == 20.0
    assert proxy._virtual_target_temperature_high == 24.0
    assert proxy._selected_sensor_name == "Remote"
    retry_calls = _issue_81_set_temp_calls(hass)
    assert len(retry_calls) == 1
    assert retry_calls[0].args[2]["target_temp_low"] == 20.0
    assert retry_calls[0].args[2]["target_temp_high"] == 24.0


@pytest.mark.asyncio
async def test_issue_81_post_recovery_cooldown_suppresses_stale_revert(hass):
    """Stale revert arriving after sensor recovery during cooldown must be ignored."""
    base_attrs = {
        "current_temperature": 30.6,
        "temperature": 30.0,
        "target_temp_step": 1.0,
        "min_temp": 5.0,
        "max_temp": 35.0,
        "hvac_action": "idle",
        "supported_features": (
            ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
        ),
    }
    proxy = _create_issue_81_proxy(
        hass,
        real_attrs=base_attrs,
        remote_temp="22.2",
        disable_auto_switch=True,
        cooldown_period=180,
    )
    proxy._virtual_target_temperature = 22.0
    proxy._last_real_target_temp = 30.0
    hass.services.async_call.reset_mock()

    # 1. Sensor unavailable -> fallback writes 22.0
    sensor_event = MagicMock()
    sensor_event.data = {
        "entity_id": "sensor.remote",
        "new_state": State("sensor.remote", STATE_UNAVAILABLE),
    }
    proxy._async_handle_sensor_state_event(sensor_event)
    await hass.async_block_till_done()

    # 2. Optimistic update sets real temperature to 22.0 (consumes pending)
    old_state = proxy._real_state
    hass.states.async_set(
        "climate.playroom",
        HVACMode.HEAT,
        {**base_attrs, "temperature": 22.0},
    )
    real_event = MagicMock()
    real_event.data = {
        "old_state": old_state,
        "new_state": hass.states.get("climate.playroom"),
    }
    proxy._async_handle_real_state_event(real_event)
    await hass.async_block_till_done()
    assert proxy._recent_real_target_requests == []

    # 3. Past 45s grace period, still within 180s cooldown, sensor recovers
    proxy._last_real_write_time = time.monotonic() - 110.0
    recovery_event = MagicMock()
    recovery_event.data = {
        "entity_id": "sensor.remote",
        "new_state": State("sensor.remote", "22.2"),
    }
    proxy._async_handle_sensor_state_event(recovery_event)
    await hass.async_block_till_done()

    assert proxy._awaiting_fallback_recovery is True
    assert proxy._cooldown_timer_unsub is not None

    # 4. Stale revert poll (22.0 -> 30.0) arrives before cooldown expires
    old_state = proxy._real_state
    hass.states.async_set(
        "climate.playroom",
        HVACMode.HEAT,
        {**base_attrs, "current_temperature": 30.5, "temperature": 30.0},
    )
    revert_event = MagicMock()
    revert_event.data = {
        "old_state": old_state,
        "new_state": hass.states.get("climate.playroom"),
    }
    proxy._async_handle_real_state_event(revert_event)
    await hass.async_block_till_done()

    assert proxy._virtual_target_temperature == 22.0
    assert proxy._selected_sensor_name == "Remote"

    # 5. Cooldown expires and retry runs
    proxy._last_real_write_time = time.monotonic() - 200.0
    proxy._async_cooldown_retry(None)
    await hass.async_block_till_done()

    assert proxy._awaiting_fallback_recovery is False
    assert proxy._virtual_target_temperature == 22.0


@pytest.mark.asyncio
async def test_issue_81_explicit_physical_preset_still_syncs_external_changes(hass):
    """Explicitly selecting Physical Entity must still sync manual target changes."""
    base_attrs = {
        "current_temperature": 22.0,
        "temperature": 22.0,
        "target_temp_step": 1.0,
        "min_temp": 5.0,
        "max_temp": 35.0,
        "supported_features": (
            ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
        ),
    }
    proxy = _create_issue_81_proxy(
        hass,
        real_attrs=base_attrs,
        remote_temp="22.0",
        disable_auto_switch=False,
    )
    proxy._selected_sensor_name = "Physical Entity"
    proxy._virtual_target_temperature = 22.0
    proxy._last_real_target_temp = 22.0
    proxy._last_real_write_time = time.monotonic() - 120.0

    assert proxy._is_in_sensor_fallback() is False

    old_state = proxy._real_state
    hass.states.async_set(
        "climate.playroom",
        HVACMode.HEAT,
        {**base_attrs, "temperature": 25.0},
    )
    event = MagicMock()
    event.data = {
        "old_state": old_state,
        "new_state": hass.states.get("climate.playroom"),
    }
    proxy._async_handle_real_state_event(event)
    await hass.async_block_till_done()

    assert proxy._is_in_sensor_fallback() is False
    assert proxy._virtual_target_temperature == 25.0


@pytest.mark.asyncio
async def test_issue_81_manual_external_change_resumes_after_recovery_grace(hass):
    """Manual physical target changes must sync normally once recovery grace expires."""
    base_attrs = {
        "current_temperature": 30.6,
        "temperature": 30.0,
        "target_temp_step": 1.0,
        "min_temp": 5.0,
        "max_temp": 35.0,
        "hvac_action": "idle",
        "supported_features": (
            ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
        ),
    }
    proxy = _create_issue_81_proxy(
        hass,
        real_attrs=base_attrs,
        remote_temp="22.2",
        disable_auto_switch=True,
    )
    proxy._virtual_target_temperature = 22.0
    proxy._last_real_target_temp = 30.0

    # Fall back then recover
    unavailable_event = MagicMock()
    unavailable_event.data = {
        "entity_id": "sensor.remote",
        "new_state": State("sensor.remote", STATE_UNAVAILABLE),
    }
    proxy._async_handle_sensor_state_event(unavailable_event)
    await hass.async_block_till_done()

    recovery_event = MagicMock()
    recovery_event.data = {
        "entity_id": "sensor.remote",
        "new_state": State("sensor.remote", "22.2"),
    }
    proxy._async_handle_sensor_state_event(recovery_event)
    await hass.async_block_till_done()

    # Expire both post-write and post-recovery grace periods
    proxy._last_real_write_time = time.monotonic() - 120.0
    proxy._fallback_recovery_grace_until = time.monotonic() - 120.0
    proxy._recent_real_target_requests = []

    old_state = proxy._real_state
    hass.states.async_set(
        "climate.playroom",
        HVACMode.HEAT,
        {**base_attrs, "temperature": 32.0},
    )
    manual_event = MagicMock()
    manual_event.data = {
        "old_state": old_state,
        "new_state": hass.states.get("climate.playroom"),
    }
    proxy._async_handle_real_state_event(manual_event)
    await hass.async_block_till_done()

    assert proxy._virtual_target_temperature == 24.0


@pytest.mark.asyncio
async def test_issue_81_fallback_and_recovery_bypass_sensor_change_threshold(hass):
    """Fallback and recovery transitions must reset _last_acted_sensor_temp."""
    base_attrs = {
        "current_temperature": 22.4,
        "temperature": 23.5,
        "target_temp_step": 0.5,
        "min_temp": 5.0,
        "max_temp": 35.0,
        "hvac_action": "heating",
        "supported_features": (
            ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
        ),
    }
    proxy = _create_issue_81_proxy(
        hass,
        hvac_mode=HVACMode.HEAT,
        real_attrs=base_attrs,
        remote_temp="22.1",
        disable_auto_switch=True,
        sensor_change_threshold=1.0,
    )
    proxy._virtual_target_temperature = 23.0
    proxy._last_acted_sensor_temp = 22.1
    hass.services.async_call.reset_mock()

    # Sensor goes unavailable; abs(22.4 - 22.1) = 0.3 < threshold (1.0)
    unavailable_event = MagicMock()
    unavailable_event.data = {
        "entity_id": "sensor.remote",
        "new_state": State("sensor.remote", STATE_UNAVAILABLE),
    }
    proxy._async_handle_sensor_state_event(unavailable_event)
    await hass.async_block_till_done()

    fallback_calls = _issue_81_set_temp_calls(hass)
    assert len(fallback_calls) == 1
    assert fallback_calls[0].args[2]["temperature"] == 23.0

    # Update physical thermostat to 23.0, then recover sensor; abs(22.1 - 22.4) < 1.0
    hass.states.async_set(
        "climate.playroom",
        HVACMode.HEAT,
        {**base_attrs, "temperature": 23.0},
    )
    proxy._real_state = hass.states.get("climate.playroom")
    hass.services.async_call.reset_mock()

    recovery_event = MagicMock()
    recovery_event.data = {
        "entity_id": "sensor.remote",
        "new_state": State("sensor.remote", "22.1"),
    }
    proxy._async_handle_sensor_state_event(recovery_event)
    await hass.async_block_till_done()

    recovery_calls = _issue_81_set_temp_calls(hass)
    assert len(recovery_calls) == 1
    assert recovery_calls[0].args[2]["temperature"] == 23.5
    assert proxy._awaiting_fallback_recovery is False


@pytest.mark.asyncio
async def test_issue_81_inflight_fallback_write_does_not_clear_recovery_flag(hass):
    """Sensor recovery mid-fallback write must not clear _awaiting_fallback_recovery."""
    base_attrs = {
        "current_temperature": 30.6,
        "temperature": 30.0,
        "target_temp_step": 1.0,
        "min_temp": 5.0,
        "max_temp": 35.0,
        "hvac_action": "idle",
        "supported_features": (
            ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
        ),
    }
    proxy = _create_issue_81_proxy(
        hass,
        hvac_mode=HVACMode.HEAT,
        real_attrs=base_attrs,
        remote_temp="22.2",
        disable_auto_switch=True,
    )
    proxy._virtual_target_temperature = 22.0
    proxy._last_real_target_temp = 30.0

    # Enter fallback directly
    proxy._sensor_states["sensor.remote"] = State("sensor.remote", STATE_UNAVAILABLE)
    proxy._update_sensor_health_from_state(
        "sensor.remote", proxy._sensor_states["sensor.remote"]
    )
    assert proxy._is_in_sensor_fallback() is True

    proxy._schedule_target_realign = MagicMock()

    async def _recover_during_fallback_write(domain, service, data=None, **kwargs):
        if (
            domain == "climate"
            and service == SERVICE_SET_TEMPERATURE
            and data
            and data.get("temperature") == 22.0
        ):
            recovery_event = MagicMock()
            recovery_event.data = {
                "entity_id": "sensor.remote",
                "new_state": State("sensor.remote", "22.2"),
            }
            proxy._async_handle_sensor_state_event(recovery_event)

    hass.services.async_call.side_effect = _recover_during_fallback_write

    await proxy._async_realign_real_target_from_sensor(trigger_source="sensor")

    assert proxy._is_in_sensor_fallback() is False
    assert proxy._awaiting_fallback_recovery is True
