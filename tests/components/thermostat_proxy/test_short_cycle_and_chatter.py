"""Regression tests for anti-short-cycling guard, rounding hysteresis, and trigger preservation."""

import asyncio
import logging
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.thermostat_proxy.climate import (
    REAL_ROUNDING_HYSTERESIS_FRACTION,
    CustomThermostatEntity,
)
from homeassistant.components.climate import ClimateEntityFeature, HVACAction, HVACMode
from homeassistant.core import State
from homeassistant.util import dt as dt_util


def _climate_set_calls(hass):
    """Return all recorded climate.set_temperature service calls."""
    return [
        call
        for call in hass.services.async_call.call_args_list
        if call.args[:2] == ("climate", "set_temperature")
    ]


def _make_proxy(
    hass,
    *,
    hvac_mode: HVACMode = HVACMode.HEAT_COOL,
    real_attrs: dict | None = None,
    remote_temp: str = "68.972",
    physical_sensor_temp: str | None = None,
    sensors: list[dict] | None = None,
    **kwargs,
) -> CustomThermostatEntity:
    """Create a configured proxy entity for short-cycle and chatter tests."""
    if sensors is None:
        sensors = [{"name": "Remote", "entity_id": "sensor.remote"}]

    physical_temp_entity = (
        "sensor.physical" if physical_sensor_temp is not None else None
    )
    proxy = CustomThermostatEntity(
        hass=hass,
        name="Test Proxy",
        real_thermostat="climate.real",
        sensors=sensors,
        default_sensor="Remote",
        unique_id="short_cycle_test",
        physical_sensor_name="Physical",
        use_last_active_sensor=False,
        physical_temperature_sensor=physical_temp_entity,
        **kwargs,
    )
    proxy.entity_id = "climate.test_proxy"
    proxy.async_write_ha_state = MagicMock()

    default_features = ClimateEntityFeature.PRESET_MODE
    if hvac_mode in (HVACMode.HEAT_COOL, HVACMode.AUTO):
        default_features |= ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
    else:
        default_features |= ClimateEntityFeature.TARGET_TEMPERATURE

    attrs = {
        "current_temperature": 68.0,
        "temperature_unit": "°F",
        "min_temp": 50.0,
        "max_temp": 90.0,
        "target_temp_step": 1.0,
        "supported_features": default_features,
    }
    if real_attrs:
        attrs.update(real_attrs)

    hass.states.async_set("climate.real", hvac_mode, attrs)
    proxy._real_state = hass.states.get("climate.real")
    proxy._update_real_temperature_limits()
    proxy._temperature_unit = "°F"

    hass.states.async_set("sensor.remote", remote_temp, {"unit_of_measurement": "°F"})
    proxy._sensor_states["sensor.remote"] = hass.states.get("sensor.remote")
    proxy._selected_sensor_name = "Remote"

    if physical_sensor_temp is not None:
        hass.states.async_set(
            "sensor.physical", physical_sensor_temp, {"unit_of_measurement": "°F"}
        )

    return proxy


def _set_real_state(
    hass, proxy: CustomThermostatEntity, hvac_mode: HVACMode, attrs: dict
) -> None:
    """Update both HA state and cached _real_state on the proxy."""
    hass.states.async_set("climate.real", hvac_mode, attrs)
    proxy._real_state = hass.states.get("climate.real")


@pytest.mark.asyncio
async def test_dual_heating_real_drop_does_not_short_cycle_when_sensor_below_target(
    hass,
):
    """Do not lower dual Low setpoint below current_real_low while actively heating."""
    base_attrs = {
        "current_temperature": 68.0,
        "target_temp_low": 68.0,
        "target_temp_high": 73.0,
        "hvac_action": HVACAction.HEATING,
        "temperature_unit": "°F",
        "min_temp": 50.0,
        "max_temp": 90.0,
        "target_temp_step": 1.0,
        "supported_features": (
            ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
            | ClimateEntityFeature.PRESET_MODE
        ),
    }
    proxy = _make_proxy(
        hass,
        hvac_mode=HVACMode.HEAT_COOL,
        real_attrs=base_attrs,
        remote_temp="68.972",
    )
    proxy._virtual_target_temperature_low = 69.0
    proxy._virtual_target_temperature_high = 74.0

    # Real thermostat temperature ticks down 68 -> 67 while heating is active
    _set_real_state(
        hass,
        proxy,
        HVACMode.HEAT_COOL,
        {**base_attrs, "current_temperature": 67.0},
    )

    await proxy._async_realign_real_target_from_sensor(trigger_source="real")

    assert _climate_set_calls(hass) == []


@pytest.mark.asyncio
async def test_dual_heating_real_drop_does_not_short_cycle_with_decimal_physical_sensor(
    hass,
):
    """Decimal physical_temperature_sensor drop must not lower active heating setpoint."""
    base_attrs = {
        "current_temperature": 68.0,
        "target_temp_low": 68.0,
        "target_temp_high": 73.0,
        "hvac_action": HVACAction.HEATING,
        "temperature_unit": "°F",
        "min_temp": 50.0,
        "max_temp": 90.0,
        "target_temp_step": 1.0,
        "supported_features": (
            ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
            | ClimateEntityFeature.PRESET_MODE
        ),
    }
    proxy = _make_proxy(
        hass,
        hvac_mode=HVACMode.HEAT_COOL,
        real_attrs=base_attrs,
        remote_temp="68.972",
        physical_sensor_temp="67.64",
    )
    proxy._virtual_target_temperature_low = 69.0
    proxy._virtual_target_temperature_high = 74.0

    hass.states.async_set("sensor.physical", "67.46", {"unit_of_measurement": "°F"})
    await proxy._async_realign_real_target_from_sensor(trigger_source="real")

    assert _climate_set_calls(hass) == []


@pytest.mark.parametrize("release_temp", ["68.0", "68.2"])
@pytest.mark.asyncio
async def test_dual_heating_real_drop_at_exact_target_holds_but_sensor_update_releases(
    hass, release_temp
):
    """At exact target, trigger_source='real' holds Low=67 but trigger_source='sensor' releases."""
    base_attrs = {
        "current_temperature": 66.0,
        "target_temp_low": 67.0,
        "target_temp_high": 73.0,
        "hvac_action": HVACAction.HEATING,
        "temperature_unit": "°F",
        "min_temp": 50.0,
        "max_temp": 90.0,
        "target_temp_step": 1.0,
        "supported_features": (
            ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
            | ClimateEntityFeature.PRESET_MODE
        ),
    }
    proxy = _make_proxy(
        hass,
        hvac_mode=HVACMode.HEAT_COOL,
        real_attrs=base_attrs,
        remote_temp="68.0",
    )
    proxy._virtual_target_temperature_low = 68.0
    proxy._virtual_target_temperature_high = 74.0

    # Real sensor tick at exact target must hold Low=67
    await proxy._async_realign_real_target_from_sensor(trigger_source="real")
    assert _climate_set_calls(hass) == []

    # Remote sensor event at/above target must release the guard and lower Low
    proxy._sensor_states["sensor.remote"] = State("sensor.remote", release_temp)
    await proxy._async_realign_real_target_from_sensor(trigger_source="sensor")

    calls = _climate_set_calls(hass)
    assert len(calls) == 1
    # At 68.2, calc_low=65.8 triggers _prevent_satisfied_rounding_crossover (66.0 -> 65.0).
    expected_low = 66.0 if release_temp == "68.0" else 65.0
    assert calls[0].args[2]["target_temp_low"] == expected_low


@pytest.mark.asyncio
async def test_dual_heating_allows_lowering_when_remote_sensor_warms_past_target(hass):
    """When remote sensor warms strictly past virtual_low, heating stops normally."""
    base_attrs = {
        "current_temperature": 67.0,
        "target_temp_low": 68.0,
        "target_temp_high": 73.0,
        "hvac_action": HVACAction.HEATING,
        "temperature_unit": "°F",
        "min_temp": 50.0,
        "max_temp": 90.0,
        "target_temp_step": 1.0,
        "supported_features": (
            ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
            | ClimateEntityFeature.PRESET_MODE
        ),
    }
    proxy = _make_proxy(
        hass,
        hvac_mode=HVACMode.HEAT_COOL,
        real_attrs=base_attrs,
        remote_temp="68.8",
    )
    proxy._virtual_target_temperature_low = 68.0
    proxy._virtual_target_temperature_high = 74.0

    await proxy._async_realign_real_target_from_sensor(trigger_source="real")

    calls = _climate_set_calls(hass)
    assert len(calls) == 1
    assert calls[0].args[2]["target_temp_low"] == 66.0


@pytest.mark.asyncio
async def test_dual_cooling_real_rise_does_not_short_cycle_and_releases_when_cooled(
    hass,
):
    """Do not raise dual High setpoint during active cooling until remote sensor cools."""
    base_attrs = {
        "current_temperature": 75.0,
        "target_temp_low": 68.0,
        "target_temp_high": 74.0,
        "hvac_action": HVACAction.COOLING,
        "temperature_unit": "°F",
        "min_temp": 50.0,
        "max_temp": 90.0,
        "target_temp_step": 1.0,
        "supported_features": (
            ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
            | ClimateEntityFeature.PRESET_MODE
        ),
    }
    proxy = _make_proxy(
        hass,
        hvac_mode=HVACMode.HEAT_COOL,
        real_attrs=base_attrs,
        remote_temp="74.1",
    )
    proxy._virtual_target_temperature_low = 68.0
    proxy._virtual_target_temperature_high = 74.0

    # Sensor is still above virtual_high (74.1 > 74.0): hold High=74
    await proxy._async_realign_real_target_from_sensor(trigger_source="real")
    assert _climate_set_calls(hass) == []

    # At exact target (74.0), trigger_source="real" also holds High=74
    proxy._sensor_states["sensor.remote"] = State("sensor.remote", "74.0")
    await proxy._async_realign_real_target_from_sensor(trigger_source="real")
    assert _climate_set_calls(hass) == []

    # Remote sensor cools below target (73.2 < 74.0): release and raise High above real_current
    proxy._sensor_states["sensor.remote"] = State("sensor.remote", "73.2")
    await proxy._async_realign_real_target_from_sensor(trigger_source="real")

    calls = _climate_set_calls(hass)
    assert len(calls) == 1
    assert calls[0].args[2]["target_temp_high"] == 76.0


@pytest.mark.asyncio
async def test_single_heat_and_cool_active_cycle_guards_and_manual_override(hass):
    """Single HEAT/COOL modes guard real ticks mid-cycle, while manual set_temperature acts immediately."""
    # Single HEAT mode
    heat_attrs = {
        "current_temperature": 67.0,
        "temperature": 68.0,
        "hvac_action": HVACAction.HEATING,
        "temperature_unit": "°F",
        "min_temp": 50.0,
        "max_temp": 90.0,
        "target_temp_step": 1.0,
        "supported_features": (
            ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
        ),
    }
    heat_proxy = _make_proxy(
        hass,
        hvac_mode=HVACMode.HEAT,
        real_attrs=heat_attrs,
        remote_temp="68.8",
    )
    heat_proxy._virtual_target_temperature = 69.0

    await heat_proxy._async_realign_real_target_from_sensor(trigger_source="real")
    assert _climate_set_calls(hass) == []

    # Manual temperature change must stop heating immediately
    await heat_proxy.async_set_temperature(temperature=65.0)
    calls = _climate_set_calls(hass)
    assert len(calls) == 1
    assert calls[0].args[2]["temperature"] == 63.0

    hass.services.async_call.reset_mock()

    # Single COOL mode
    cool_attrs = {
        "current_temperature": 76.0,
        "temperature": 75.0,
        "hvac_action": HVACAction.COOLING,
        "temperature_unit": "°F",
        "min_temp": 50.0,
        "max_temp": 90.0,
        "target_temp_step": 1.0,
        "supported_features": (
            ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
        ),
    }
    cool_proxy = _make_proxy(
        hass,
        hvac_mode=HVACMode.COOL,
        real_attrs=cool_attrs,
        remote_temp="74.2",
    )
    cool_proxy._virtual_target_temperature = 74.0

    await cool_proxy._async_realign_real_target_from_sensor(trigger_source="real")
    assert _climate_set_calls(hass) == []

    # Manual temperature change must stop cooling immediately
    await cool_proxy.async_set_temperature(temperature=78.0)
    calls = _climate_set_calls(hass)
    assert len(calls) == 1
    assert calls[0].args[2]["temperature"] == 80.0


@pytest.mark.asyncio
async def test_single_cool_humidity_overdrive_holds_active_cooling_on_real_rise(hass):
    """Humidity overdrive holds active cooling setpoint when real_current rises even if temp <= target."""
    cool_attrs = {
        "current_temperature": 75.0,
        "temperature": 73.0,
        "hvac_action": HVACAction.COOLING,
        "temperature_unit": "°F",
        "min_temp": 50.0,
        "max_temp": 90.0,
        "target_temp_step": 1.0,
        "supported_features": (
            ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
        ),
    }
    sensors = [
        {
            "name": "Remote",
            "entity_id": "sensor.remote",
            "humidity_entity_id": "sensor.humidity",
        }
    ]
    proxy = _make_proxy(
        hass,
        hvac_mode=HVACMode.COOL,
        real_attrs=cool_attrs,
        remote_temp="73.5",
        sensors=sensors,
        max_humidity_overcool=2.0,
        default_target_humidity=50,
    )
    proxy._virtual_target_temperature = 74.0
    proxy._virtual_target_humidity = 50
    proxy._active_overdrive_humidity = True
    hass.states.async_set("sensor.humidity", "65")
    proxy._sensor_humidity_states["sensor.humidity"] = State("sensor.humidity", "65")

    # Calculated target = 75.0 + 0.0 - 1.0 = 74.0 > current_real (73.0),
    # but active humidity overdrive must keep cooling setpoint at 73.0.
    await proxy._async_realign_real_target_from_sensor(trigger_source="real")
    assert proxy._active_overdrive_humidity is True
    assert _climate_set_calls(hass) == []

    # Once humidity is satisfied, overdrive ends and guard releases
    hass.states.async_set("sensor.humidity", "45")
    proxy._sensor_humidity_states["sensor.humidity"] = State("sensor.humidity", "45")
    await proxy._async_realign_real_target_from_sensor(trigger_source="real")
    assert proxy._active_overdrive_humidity is False
    calls = _climate_set_calls(hass)
    assert len(calls) == 1
    assert calls[0].args[2]["temperature"] == 76.0


@pytest.mark.asyncio
async def test_active_cycle_guard_respects_safety_limits(hass):
    """Held active-cycle targets are still clamped to user limits and max_sync_offset."""
    # Case 1: Heating current_real_target exceeds user_max_temp
    heat_attrs = {
        "current_temperature": 71.0,
        "temperature": 78.0,
        "hvac_action": HVACAction.HEATING,
        "temperature_unit": "°F",
        "min_temp": 50.0,
        "max_temp": 90.0,
        "target_temp_step": 1.0,
        "supported_features": (
            ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
        ),
    }
    proxy_user_max = _make_proxy(
        hass,
        hvac_mode=HVACMode.HEAT,
        real_attrs=heat_attrs,
        remote_temp="69.5",
        user_max_temp=75.0,
    )
    proxy_user_max._virtual_target_temperature = 70.0

    await proxy_user_max._async_realign_real_target_from_sensor(trigger_source="real")
    calls = _climate_set_calls(hass)
    assert len(calls) == 1
    assert calls[0].args[2]["temperature"] == 75.0

    hass.services.async_call.reset_mock()

    # Case 2: Heating current_real_target exceeds virtual_target + max_sync_offset
    proxy_sync_offset = _make_proxy(
        hass,
        hvac_mode=HVACMode.HEAT,
        real_attrs=heat_attrs,
        remote_temp="69.5",
        max_sync_offset=4.0,
    )
    proxy_sync_offset._virtual_target_temperature = 70.0

    await proxy_sync_offset._async_realign_real_target_from_sensor(
        trigger_source="real"
    )
    calls = _climate_set_calls(hass)
    assert len(calls) == 1
    assert calls[0].args[2]["temperature"] == 74.0

    hass.services.async_call.reset_mock()

    # Case 3: Cooling current_real_target falls below user_min_temp
    cool_attrs = {
        "current_temperature": 66.0,
        "temperature": 60.0,
        "hvac_action": HVACAction.COOLING,
        "temperature_unit": "°F",
        "min_temp": 50.0,
        "max_temp": 90.0,
        "target_temp_step": 1.0,
        "supported_features": (
            ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
        ),
    }
    proxy_user_min = _make_proxy(
        hass,
        hvac_mode=HVACMode.COOL,
        real_attrs=cool_attrs,
        remote_temp="70.5",
        user_min_temp=65.0,
    )
    proxy_user_min._virtual_target_temperature = 70.0

    await proxy_user_min._async_realign_real_target_from_sensor(trigger_source="real")
    calls = _climate_set_calls(hass)
    assert len(calls) == 1
    assert calls[0].args[2]["temperature"] == 65.0


@pytest.mark.asyncio
async def test_real_rounding_hysteresis_absorbs_half_step_jitter(hass):
    """Physical sensor jitter across the 0.5*step rounding boundary is absorbed until 0.75*step."""
    assert REAL_ROUNDING_HYSTERESIS_FRACTION == 0.25

    base_attrs = {
        "current_temperature": 65.0,
        "target_temp_low": 65.0,
        "target_temp_high": 72.0,
        "hvac_action": HVACAction.IDLE,
        "temperature_unit": "°F",
        "min_temp": 50.0,
        "max_temp": 90.0,
        "target_temp_step": 1.0,
        "supported_features": (
            ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
            | ClimateEntityFeature.PRESET_MODE
        ),
    }
    proxy = _make_proxy(
        hass,
        hvac_mode=HVACMode.HEAT_COOL,
        real_attrs=base_attrs,
        remote_temp="68.0",
        physical_sensor_temp="64.58",
    )
    proxy._virtual_target_temperature_low = 68.0
    proxy._virtual_target_temperature_high = 75.0

    # Flicker 64.58 -> 64.40 -> 64.58 -> 64.26 (< 0.75 from 65.0): holds at 65.0
    for jitter_temp in ("64.40", "64.58", "64.26"):
        hass.states.async_set(
            "sensor.physical", jitter_temp, {"unit_of_measurement": "°F"}
        )
        await proxy._async_realign_real_target_from_sensor(trigger_source="real")
        assert _climate_set_calls(hass) == []

    # Crossing the 0.75*step threshold (64.25 -> abs(64.25 - 65.0) == 0.75) updates normally
    hass.states.async_set("sensor.physical", "64.25", {"unit_of_measurement": "°F"})
    await proxy._async_realign_real_target_from_sensor(trigger_source="real")
    calls = _climate_set_calls(hass)
    assert len(calls) == 1
    assert calls[0].args[2]["target_temp_low"] == 64.0

    hass.services.async_call.reset_mock()
    proxy._reset_commanded_targets()
    proxy._recent_real_target_requests.clear()

    # trigger_source="sensor" must act immediately without hysteresis
    _set_real_state(hass, proxy, HVACMode.HEAT_COOL, base_attrs)
    hass.states.async_set("sensor.physical", "64.40", {"unit_of_measurement": "°F"})
    await proxy._async_realign_real_target_from_sensor(trigger_source="sensor")
    calls = _climate_set_calls(hass)
    assert len(calls) == 1
    assert calls[0].args[2]["target_temp_low"] == 64.0

    hass.services.async_call.reset_mock()

    # Overdrive active must act immediately even on trigger_source="real"
    heat_attrs = {
        "current_temperature": 64.0,
        "temperature": 67.0,
        "hvac_action": HVACAction.IDLE,
        "temperature_unit": "°F",
        "min_temp": 50.0,
        "max_temp": 90.0,
        "target_temp_step": 1.0,
        "supported_features": (
            ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
        ),
    }
    overdrive_proxy = _make_proxy(
        hass,
        hvac_mode=HVACMode.HEAT,
        real_attrs=heat_attrs,
        remote_temp="67.5",
        physical_sensor_temp="63.90",
        overdrive_offset=1.0,
    )
    overdrive_proxy._virtual_target_temperature = 69.0

    # calc = 63.90 + (69.0 - 67.5) + 1.0 = 66.40; abs(66.40 - 67.0) = 0.60 < 0.75,
    # but overdrive is active so it steps to 66.0 immediately.
    await overdrive_proxy._async_realign_real_target_from_sensor(trigger_source="real")
    assert overdrive_proxy._active_overdrive_heat is True
    calls = _climate_set_calls(hass)
    assert len(calls) == 1
    assert calls[0].args[2]["temperature"] == 66.0


@pytest.mark.asyncio
async def test_real_rounding_hysteresis_does_not_override_satisfied_rounding_crossover(
    hass,
):
    """Satisfied rounding crossover still steps away from real_current after hysteresis."""
    # Heating: remote sensor satisfied (68.2 > 68.0), current_real_target == real_current == 67.0
    heat_attrs = {
        "current_temperature": 67.0,
        "temperature": 67.0,
        "hvac_action": HVACAction.IDLE,
        "temperature_unit": "°F",
        "min_temp": 50.0,
        "max_temp": 90.0,
        "target_temp_step": 1.0,
        "supported_features": (
            ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
        ),
    }
    heat_proxy = _make_proxy(
        hass,
        hvac_mode=HVACMode.HEAT,
        real_attrs=heat_attrs,
        remote_temp="68.2",
        overdrive_offset=0.0,
    )
    heat_proxy._virtual_target_temperature = 68.0

    # calc = 67.0 + (68.0 - 68.2) = 66.8; hysteresis holds 67.0 (< 0.75),
    # then _prevent_satisfied_rounding_crossover steps away to 66.0.
    await heat_proxy._async_realign_real_target_from_sensor(trigger_source="real")
    calls = _climate_set_calls(hass)
    assert len(calls) == 1
    assert calls[0].args[2]["temperature"] == 66.0

    hass.services.async_call.reset_mock()

    # Cooling symmetry: remote sensor satisfied (73.8 < 74.0), current_real == real_current == 75.0
    cool_attrs = {
        "current_temperature": 75.0,
        "temperature": 75.0,
        "hvac_action": HVACAction.IDLE,
        "temperature_unit": "°F",
        "min_temp": 50.0,
        "max_temp": 90.0,
        "target_temp_step": 1.0,
        "supported_features": (
            ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
        ),
    }
    cool_proxy = _make_proxy(
        hass,
        hvac_mode=HVACMode.COOL,
        real_attrs=cool_attrs,
        remote_temp="73.8",
        overdrive_offset=0.0,
    )
    cool_proxy._virtual_target_temperature = 74.0

    await cool_proxy._async_realign_real_target_from_sensor(trigger_source="real")
    calls = _climate_set_calls(hass)
    assert len(calls) == 1
    assert calls[0].args[2]["temperature"] == 76.0


@pytest.mark.asyncio
async def test_trigger_source_preserved_across_coalescing_and_cooldown_retry(hass):
    """Coalescing and cooldown retry preserve homogeneous trigger_source and upgrade mixed to None."""
    proxy = _make_proxy(
        hass,
        hvac_mode=HVACMode.HEAT,
        real_attrs={
            "current_temperature": 67.0,
            "temperature": 68.0,
            "hvac_action": HVACAction.IDLE,
            "temperature_unit": "°F",
            "min_temp": 50.0,
            "max_temp": 90.0,
            "target_temp_step": 1.0,
            "supported_features": (
                ClimateEntityFeature.TARGET_TEMPERATURE
                | ClimateEntityFeature.PRESET_MODE
            ),
        },
        remote_temp="68.0",
        cooldown_period=60,
    )
    proxy._virtual_target_temperature = 69.0

    # Part 1: _schedule_target_realign coalescing (use non-eager Task to simulate queued events)
    with (
        patch.object(
            proxy, "_async_realign_real_target_from_sensor", new=AsyncMock()
        ) as mock_realign,
        patch.object(
            hass,
            "async_create_task",
            side_effect=lambda coro, *args, **kwargs: asyncio.Task(
                coro, loop=hass.loop
            ),
        ),
    ):
        # Two "real" triggers coalesce to "real"
        proxy._schedule_target_realign(trigger_source="real")
        proxy._schedule_target_realign(trigger_source="real")
        assert proxy._realign_trigger_source == "real"
        await proxy._sensor_realign_task
        mock_realign.assert_awaited_once_with(retry=False, trigger_source="real")

        mock_realign.reset_mock()

        # Two "sensor" triggers coalesce to "sensor"
        proxy._schedule_target_realign(trigger_source="sensor")
        proxy._schedule_target_realign(trigger_source="sensor")
        assert proxy._realign_trigger_source == "sensor"
        await proxy._sensor_realign_task
        mock_realign.assert_awaited_once_with(retry=False, trigger_source="sensor")

        mock_realign.reset_mock()

        # Mixed "real" + "sensor" upgrades to None
        proxy._schedule_target_realign(trigger_source="real")
        proxy._schedule_target_realign(trigger_source="sensor")
        assert proxy._realign_trigger_source is None
        await proxy._sensor_realign_task
        mock_realign.assert_awaited_once_with(retry=False, trigger_source=None)

        mock_realign.reset_mock()

        # Mixed "sensor" + "real" upgrades to None
        proxy._schedule_target_realign(trigger_source="sensor")
        proxy._schedule_target_realign(trigger_source="real")
        assert proxy._realign_trigger_source is None
        await proxy._sensor_realign_task
        mock_realign.assert_awaited_once_with(retry=False, trigger_source=None)

    # Part 2: Cooldown retry trigger_source preservation and upgrade
    proxy._last_real_write_time = time.monotonic()

    with patch(
        "custom_components.thermostat_proxy.climate.async_call_later",
        return_value=MagicMock(),
    ) as mock_call_later:
        # Blocking "real" during cooldown records _pending_cooldown_trigger_source == "real"
        await proxy._async_realign_real_target_from_sensor(trigger_source="real")
        assert mock_call_later.call_count == 1
        assert proxy._pending_cooldown_trigger_source == "real"

        # Another "real" while cooldown is armed keeps "real"
        await proxy._async_realign_real_target_from_sensor(trigger_source="real")
        assert proxy._pending_cooldown_trigger_source == "real"

        with patch.object(proxy, "_schedule_target_realign") as mock_schedule:
            proxy._async_cooldown_retry(dt_util.utcnow())
            mock_schedule.assert_called_once_with(retry=True, trigger_source="real")
            assert proxy._pending_cooldown_trigger_source is None

        # Blocking "real" then receiving "sensor" while cooldown is armed upgrades to None
        mock_call_later.reset_mock()
        await proxy._async_realign_real_target_from_sensor(trigger_source="real")
        assert proxy._pending_cooldown_trigger_source == "real"
        await proxy._async_realign_real_target_from_sensor(trigger_source="sensor")
        assert proxy._pending_cooldown_trigger_source is None

        with patch.object(proxy, "_schedule_target_realign") as mock_schedule:
            proxy._async_cooldown_retry(dt_util.utcnow())
            mock_schedule.assert_called_once_with(retry=True, trigger_source=None)
            assert proxy._pending_cooldown_trigger_source is None


@pytest.mark.asyncio
async def test_preset_switch_mid_cycle_bypasses_active_cycle_guard(hass):
    """Switching presets mid-cycle must realign immediately instead of holding stale targets."""
    sensors = [
        {"name": "Office", "entity_id": "sensor.office"},
        {"name": "Kids Room", "entity_id": "sensor.kids_room"},
    ]

    # Dual heating: Office (65.0) -> Kids Room (67.8) with virtual_low=68.0
    heat_attrs = {
        "current_temperature": 68.0,
        "target_temp_low": 71.0,
        "target_temp_high": 77.0,
        "hvac_action": HVACAction.HEATING,
        "temperature_unit": "°F",
        "min_temp": 50.0,
        "max_temp": 90.0,
        "target_temp_step": 1.0,
        "supported_features": (
            ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
            | ClimateEntityFeature.PRESET_MODE
        ),
    }
    heat_proxy = _make_proxy(
        hass,
        hvac_mode=HVACMode.HEAT_COOL,
        real_attrs=heat_attrs,
        sensors=sensors,
    )
    hass.states.async_set("sensor.office", "65.0", {"unit_of_measurement": "°F"})
    hass.states.async_set("sensor.kids_room", "67.8", {"unit_of_measurement": "°F"})
    heat_proxy._sensor_states["sensor.office"] = hass.states.get("sensor.office")
    heat_proxy._sensor_states["sensor.kids_room"] = hass.states.get("sensor.kids_room")
    heat_proxy._selected_sensor_name = "Office"
    heat_proxy._virtual_target_temperature_low = 68.0
    heat_proxy._virtual_target_temperature_high = 74.0

    await heat_proxy.async_set_preset_mode("Kids Room")

    calls = _climate_set_calls(hass)
    assert len(calls) == 1
    assert calls[0].args[2]["target_temp_low"] == 68.0

    hass.services.async_call.reset_mock()

    # Dual cooling: Office (78.0) -> Kids Room (74.2) with virtual_high=74.0
    cool_attrs = {
        "current_temperature": 74.0,
        "target_temp_low": 64.0,
        "target_temp_high": 70.0,
        "hvac_action": HVACAction.COOLING,
        "temperature_unit": "°F",
        "min_temp": 50.0,
        "max_temp": 90.0,
        "target_temp_step": 1.0,
        "supported_features": (
            ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
            | ClimateEntityFeature.PRESET_MODE
        ),
    }
    cool_proxy = _make_proxy(
        hass,
        hvac_mode=HVACMode.HEAT_COOL,
        real_attrs=cool_attrs,
        sensors=sensors,
    )
    hass.states.async_set("sensor.office", "78.0", {"unit_of_measurement": "°F"})
    hass.states.async_set("sensor.kids_room", "74.2", {"unit_of_measurement": "°F"})
    cool_proxy._sensor_states["sensor.office"] = hass.states.get("sensor.office")
    cool_proxy._sensor_states["sensor.kids_room"] = hass.states.get("sensor.kids_room")
    cool_proxy._selected_sensor_name = "Office"
    cool_proxy._virtual_target_temperature_low = 68.0
    cool_proxy._virtual_target_temperature_high = 74.0

    await cool_proxy.async_set_preset_mode("Kids Room")

    calls = _climate_set_calls(hass)
    assert len(calls) == 1
    assert calls[0].args[2]["target_temp_high"] == 74.0


@pytest.mark.asyncio
async def test_real_rounding_hysteresis_probe_does_not_emit_clamp_warning(hass, caplog):
    """Probing out-of-bounds current_real during rounding hysteresis must not log a clamp warning."""
    proxy = _make_proxy(
        hass,
        hvac_mode=HVACMode.HEAT,
        real_attrs={
            "current_temperature": 70.0,
            "temperature": 76.0,
            "hvac_action": HVACAction.IDLE,
            "temperature_unit": "°F",
            "min_temp": 50.0,
            "max_temp": 90.0,
            "target_temp_step": 1.0,
            "supported_features": (
                ClimateEntityFeature.TARGET_TEMPERATURE
                | ClimateEntityFeature.PRESET_MODE
            ),
        },
        remote_temp="70.0",
        user_max_temp=75.0,
    )
    proxy._virtual_target_temperature = 70.0

    with caplog.at_level(logging.WARNING):
        result = proxy._apply_real_rounding_hysteresis(
            desired_real=75.0,
            calculated_real=75.4,
            current_real=76.0,
            trigger_source="real",
            overdrive_active=False,
            reference_target=70.0,
        )

    assert result == 75.0
    assert not any("Clamping to" in record.message for record in caplog.records)
