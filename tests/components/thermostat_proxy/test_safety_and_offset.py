"""Tests for safety limits, max_sync_offset, and temperature sanitization."""

from unittest.mock import MagicMock

import pytest

from custom_components.thermostat_proxy.climate import CustomThermostatEntity
from homeassistant.components.climate import ClimateEntityFeature, HVACMode
from homeassistant.const import UnitOfTemperature
from homeassistant.core import State


def create_proxy(
    hass,
    thermostat="climate.real",
    sensors=None,
    max_sync_offset=10.0,
    min_temp=None,
    max_temp=None,
    real_min_temp=45.0,
    real_max_temp=80.0,
):
    """Helper to create a configured CustomThermostatEntity for safety tests."""
    if hass is None:
        from unittest.mock import MagicMock

        hass = MagicMock()

    if sensors is None:
        sensors = [{"name": "Sensor 1", "entity_id": "sensor.1"}]

    proxy = CustomThermostatEntity(
        hass=hass,
        name="Test Proxy",
        real_thermostat=thermostat,
        sensors=sensors,
        default_sensor="Sensor 1",
        unique_id="123",
        physical_sensor_name="Physical",
        use_last_active_sensor=False,
        max_sync_offset=max_sync_offset,
        user_min_temp=min_temp,
        user_max_temp=max_temp,
    )

    attrs = {
        "current_temperature": 74.0,
        "temperature": 74.0,
        "target_temp_step": 1.0,
        "min_temp": real_min_temp,
        "max_temp": real_max_temp,
        "current_humidity": 45.0,
        "supported_features": ClimateEntityFeature.TARGET_TEMPERATURE,
    }
    proxy._real_state = State(thermostat, HVACMode.COOL, attrs)
    proxy._temperature_unit = UnitOfTemperature.FAHRENHEIT
    proxy._update_real_temperature_limits()

    if hasattr(hass, "states") and hasattr(hass.states, "async_set"):
        try:
            hass.states.async_set(thermostat, HVACMode.COOL, attrs)
            proxy._real_state = hass.states.get(thermostat)
        except Exception:
            pass

    return proxy


def test_safety_clamp_enforces_max_sync_offset():
    """Test that _apply_safety_clamp strictly constrains setpoint within max_sync_offset."""
    proxy = create_proxy(None, max_sync_offset=10.0)
    proxy._virtual_target_temperature = 72.5

    # 1. Calculated target is 32.0 (below allowed range [62.5, 82.5])
    # Hardware min is 45.0, so without max_sync_offset it would have clamped to 45.0.
    # With max_sync_offset=10, it must clamp to 62.5!
    clamped = proxy._apply_safety_clamp(32.0, reference_target=72.5)
    assert clamped == 62.5

    # 2. Calculated target is 45.0 (still below allowed 62.5)
    clamped = proxy._apply_safety_clamp(45.0, reference_target=72.5)
    assert clamped == 62.5

    # 3. Calculated target is 95.0 (above allowed range [62.5, 82.5])
    # Hardware max is 80.0, so max_sync_offset (82.5) followed by hardware max (80.0) clamps to 80.0
    clamped = proxy._apply_safety_clamp(95.0, reference_target=72.5)
    assert clamped == 80.0

    # 4. Within range (e.g. 70.0)
    clamped = proxy._apply_safety_clamp(70.0, reference_target=72.5)
    assert clamped == 70.0


def test_safety_clamp_dual_setpoint_max_sync_offset():
    """Test that dual setpoints each respect max_sync_offset relative to their targets."""
    proxy = create_proxy(
        None, max_sync_offset=10.0, real_min_temp=40.0, real_max_temp=90.0
    )
    proxy._virtual_target_temperature_low = 68.0
    proxy._virtual_target_temperature_high = 74.0

    # Low setpoint: target is 68.0 -> allowed range is [58.0, 78.0]
    clamped_low = proxy._apply_safety_clamp(45.0, reference_target=68.0)
    assert clamped_low == 58.0

    # High setpoint: target is 74.0 -> allowed range is [64.0, 84.0]
    clamped_high = proxy._apply_safety_clamp(50.0, reference_target=74.0)
    assert clamped_high == 64.0


def test_sanitize_uninitialized_real_temperature_below_hardware_min(hass):
    """Test that physical current_temperature below hardware min_temp is treated as uninitialized."""
    proxy = create_proxy(hass, real_min_temp=45.0)

    # Physical thermostat reconnects reporting 32.0°F (below hardware min_temp 45.0°F)
    hass.states.async_set(
        "climate.real",
        HVACMode.COOL,
        {
            "current_temperature": 32.0,
            "temperature": 74.0,
            "min_temp": 45.0,
            "max_temp": 80.0,
            "current_humidity": 0,
        },
    )
    proxy._real_state = hass.states.get("climate.real")
    proxy._update_real_temperature_limits()

    # Must return None and not mark entity as healthy with bogus reading
    assert proxy._get_real_current_temperature() is None


def test_sanitize_uninitialized_real_temperature_32f_zero_humidity(hass):
    """Test that 32°F with 0% humidity in Fahrenheit is treated as uninitialized."""
    proxy = create_proxy(hass, real_min_temp=30.0)  # min_temp lower than 32

    # Physical thermostat reports exactly 32.0°F and 0% humidity
    hass.states.async_set(
        "climate.real",
        HVACMode.COOL,
        {
            "current_temperature": 32.0,
            "temperature": 74.0,
            "min_temp": 30.0,
            "max_temp": 80.0,
            "current_humidity": 0,
        },
    )
    proxy._real_state = hass.states.get("climate.real")
    proxy._update_real_temperature_limits()

    assert proxy._get_real_current_temperature() is None


def test_sanitize_uninitialized_real_temperature_missing_humidity(hass):
    """Test that 32°F with missing humidity in Fahrenheit is treated as uninitialized."""
    proxy = create_proxy(hass, real_min_temp=30.0)

    # Physical thermostat reports exactly 32.0°F and no humidity attribute
    hass.states.async_set(
        "climate.real",
        HVACMode.COOL,
        {
            "current_temperature": 32.0,
            "temperature": 74.0,
            "min_temp": 30.0,
            "max_temp": 80.0,
        },
    )
    proxy._real_state = hass.states.get("climate.real")
    proxy._update_real_temperature_limits()

    assert proxy._get_real_current_temperature() is None


def test_sanitize_uninitialized_real_temperature_with_normal_humidity(hass):
    """Test that 32°F even with normal humidity (e.g. 47%) is treated as uninitialized."""
    proxy = create_proxy(hass, real_min_temp=45.0)

    # Physical thermostat reconnects reporting 32.0°F and 47% humidity
    hass.states.async_set(
        "climate.real",
        HVACMode.COOL,
        {
            "current_temperature": 32.0,
            "temperature": 73.0,
            "min_temp": 45.0,
            "max_temp": 80.0,
            "current_humidity": 47.0,
        },
    )
    proxy._real_state = hass.states.get("climate.real")
    proxy._update_real_temperature_limits()

    assert proxy._get_real_current_temperature() is None


def test_format_math_real_adjustment_shows_clamping():
    """Test that log math formatting clearly notes clamping when desired_val differs."""
    proxy = create_proxy(None)

    # Normal math (no clamping)
    msg = proxy._format_math_real_adjustment(
        real_val=74.0,
        sensor_val=72.0,
        virtual_val=72.0,
        desired_val=74.0,
        unit="°F",
    )
    assert msg == "74.0°F - 0.0°F = 74.0°F"

    # Clamped math (e.g. 32.0 - 0.0 clamped to 62.5)
    msg_clamped = proxy._format_math_real_adjustment(
        real_val=32.0,
        sensor_val=72.5,
        virtual_val=72.5,
        desired_val=62.5,
        unit="°F",
    )
    assert msg_clamped == "32.0°F - 0.0°F = 62.5°F"


@pytest.mark.asyncio
async def test_reconnect_32f_zero_humidity_skips_realign(hass):
    """Test that 32°F / 0% humidity on reconnect aborts realignment without service call."""
    proxy = create_proxy(hass, real_min_temp=45.0, max_sync_offset=10.0)
    proxy._virtual_target_temperature = 72.5
    proxy._sensor_states["sensor.1"] = State("sensor.1", "72.5")

    # Real thermostat reconnects with 32.0°F and 0% humidity
    proxy._real_state = State(
        "climate.real",
        HVACMode.COOL,
        {
            "current_temperature": 32.0,
            "temperature": 72.0,
            "min_temp": 45.0,
            "max_temp": 80.0,
            "current_humidity": 0,
            "target_temp_step": 1.0,
            "supported_features": ClimateEntityFeature.TARGET_TEMPERATURE,
        },
    )

    await proxy._async_realign_real_target_from_sensor()

    # Must NOT dispatch climate.set_temperature to the physical thermostat
    assert not hass.services.async_call.called


@pytest.mark.asyncio
async def test_realign_enforces_max_sync_offset_clamp(hass):
    """Test that realignment strictly clamps physical setpoint within max_sync_offset."""
    proxy = create_proxy(hass, real_min_temp=45.0, max_sync_offset=10.0)
    proxy._virtual_target_temperature = 72.5
    proxy._sensor_states["sensor.1"] = State("sensor.1", "72.5")

    # Real thermostat reports 50.0°F (valid reading, 50% humidity)
    # Target = 72.5, sensor = 72.5 -> delta = 0.
    # Calculated real target = 50.0 + 0 = 50.0°F.
    # Allowed range [62.5, 82.5]. Clamped to 62.5°F, rounded to step 1.0 -> 63.0°F.
    proxy._real_state = State(
        "climate.real",
        HVACMode.COOL,
        {
            "current_temperature": 50.0,
            "temperature": 72.0,
            "min_temp": 45.0,
            "max_temp": 80.0,
            "current_humidity": 50.0,
            "target_temp_step": 1.0,
            "supported_features": ClimateEntityFeature.TARGET_TEMPERATURE,
        },
    )

    await proxy._async_realign_real_target_from_sensor()

    assert hass.services.async_call.called
    args, _ = hass.services.async_call.call_args
    assert args[0] == "climate"
    assert args[1] == "set_temperature"
    # Hardware min is 45.0, but max_sync_offset ensures it is clamped near 62.5 (62.0 with step 1.0), NEVER 50.0 or 45.0!
    assert args[2]["temperature"] in (62.0, 63.0)
    assert abs(args[2]["temperature"] - 72.5) <= 10.5
    assert args[2]["temperature"] not in (50.0, 45.0)


def _climate_set_calls(hass):
    """Return all recorded climate.set_temperature service calls."""
    return [
        call
        for call in hass.services.async_call.call_args_list
        if call.args[:2] == ("climate", "set_temperature")
    ]


def _configure_real_state(
    hass,
    proxy: CustomThermostatEntity,
    hvac_mode: HVACMode,
    attrs: dict,
    selected_sensor: str,
    remote_temp: str | None = None,
) -> None:
    """Configure proxy entity_id, physical state, and selected sensor."""
    proxy.entity_id = "climate.test_proxy"
    proxy.async_write_ha_state = MagicMock()
    hass.states.async_set("climate.real", hvac_mode, attrs)
    proxy._real_state = hass.states.get("climate.real")
    proxy._update_real_temperature_limits()
    proxy._selected_sensor_name = selected_sensor
    if remote_temp is not None:
        hass.states.async_set("sensor.1", remote_temp, {"unit_of_measurement": "°F"})
        proxy._sensor_states["sensor.1"] = hass.states.get("sensor.1")


@pytest.mark.asyncio
async def test_physical_preset_direct_passthrough_beyond_max_sync_offset(hass):
    """Physical preset passes targets directly even when gap from current_temp > max_sync_offset."""
    # Dual setpoint scenario: current=63.0, low=68.0, high=74.0, max_sync_offset=10.0
    dual_proxy = create_proxy(
        hass, max_sync_offset=10.0, real_min_temp=45.0, real_max_temp=90.0
    )
    _configure_real_state(
        hass,
        dual_proxy,
        HVACMode.HEAT_COOL,
        {
            "current_temperature": 63.0,
            "target_temp_low": 65.0,
            "target_temp_high": 72.0,
            "target_temp_step": 1.0,
            "min_temp": 45.0,
            "max_temp": 90.0,
            "supported_features": (
                ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
                | ClimateEntityFeature.PRESET_MODE
            ),
        },
        selected_sensor="Physical",
    )

    await dual_proxy.async_set_temperature(target_temp_low=68.0, target_temp_high=74.0)

    calls = _climate_set_calls(hass)
    assert len(calls) == 1
    assert calls[0].args[2]["target_temp_low"] == 68.0
    assert calls[0].args[2]["target_temp_high"] == 74.0
    assert dual_proxy.target_temperature_low == 68.0
    assert dual_proxy.target_temperature_high == 74.0

    hass.services.async_call.reset_mock()

    # Single setpoint scenario: current=60.0, target=75.0 (15° gap > 10° max_sync_offset)
    single_proxy = create_proxy(
        hass, max_sync_offset=10.0, real_min_temp=45.0, real_max_temp=90.0
    )
    _configure_real_state(
        hass,
        single_proxy,
        HVACMode.HEAT,
        {
            "current_temperature": 60.0,
            "temperature": 62.0,
            "target_temp_step": 1.0,
            "min_temp": 45.0,
            "max_temp": 90.0,
            "supported_features": (
                ClimateEntityFeature.TARGET_TEMPERATURE
                | ClimateEntityFeature.PRESET_MODE
            ),
        },
        selected_sensor="Physical",
    )

    await single_proxy.async_set_temperature(temperature=75.0)

    calls = _climate_set_calls(hass)
    assert len(calls) == 1
    assert calls[0].args[2]["temperature"] == 75.0
    assert single_proxy.target_temperature == 75.0


@pytest.mark.asyncio
async def test_physical_preset_passthrough_when_current_temperature_missing(hass):
    """Physical preset passes single and dual targets directly even if current_temperature is None."""
    single_proxy = create_proxy(
        hass, max_sync_offset=10.0, real_min_temp=45.0, real_max_temp=90.0
    )
    _configure_real_state(
        hass,
        single_proxy,
        HVACMode.HEAT,
        {
            "current_temperature": None,
            "temperature": 68.0,
            "target_temp_step": 1.0,
            "min_temp": 45.0,
            "max_temp": 90.0,
            "supported_features": (
                ClimateEntityFeature.TARGET_TEMPERATURE
                | ClimateEntityFeature.PRESET_MODE
            ),
        },
        selected_sensor="Physical",
    )

    await single_proxy.async_set_temperature(temperature=74.0)

    calls = _climate_set_calls(hass)
    assert len(calls) == 1
    assert calls[0].args[2]["temperature"] == 74.0
    assert single_proxy.target_temperature == 74.0

    hass.services.async_call.reset_mock()

    dual_proxy = create_proxy(
        hass, max_sync_offset=10.0, real_min_temp=45.0, real_max_temp=90.0
    )
    _configure_real_state(
        hass,
        dual_proxy,
        HVACMode.HEAT_COOL,
        {
            "current_temperature": None,
            "target_temp_low": 66.0,
            "target_temp_high": 72.0,
            "target_temp_step": 1.0,
            "min_temp": 45.0,
            "max_temp": 90.0,
            "supported_features": (
                ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
                | ClimateEntityFeature.PRESET_MODE
            ),
        },
        selected_sensor="Physical",
    )

    await dual_proxy.async_set_temperature(target_temp_low=68.0, target_temp_high=74.0)

    calls = _climate_set_calls(hass)
    assert len(calls) == 1
    assert calls[0].args[2]["target_temp_low"] == 68.0
    assert calls[0].args[2]["target_temp_high"] == 74.0
    assert dual_proxy.target_temperature_low == 68.0
    assert dual_proxy.target_temperature_high == 74.0


@pytest.mark.asyncio
async def test_physical_preset_realignment_does_not_clamp_by_max_sync_offset(hass):
    """Switching back to Physical preset restores full virtual targets without max_sync_offset clamp."""
    dual_proxy = create_proxy(
        hass, max_sync_offset=10.0, real_min_temp=45.0, real_max_temp=90.0
    )
    _configure_real_state(
        hass,
        dual_proxy,
        HVACMode.HEAT_COOL,
        {
            "current_temperature": 63.0,
            "target_temp_low": 65.0,
            "target_temp_high": 72.0,
            "target_temp_step": 1.0,
            "min_temp": 45.0,
            "max_temp": 90.0,
            "supported_features": (
                ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
                | ClimateEntityFeature.PRESET_MODE
            ),
        },
        selected_sensor="Sensor 1",
        remote_temp="65.0",
    )
    dual_proxy._virtual_target_temperature_low = 67.0
    dual_proxy._virtual_target_temperature_high = 74.0

    await dual_proxy.async_set_preset_mode("Physical")

    calls = _climate_set_calls(hass)
    assert len(calls) == 1
    assert calls[0].args[2]["target_temp_low"] == 67.0
    assert calls[0].args[2]["target_temp_high"] == 74.0

    hass.services.async_call.reset_mock()

    single_proxy = create_proxy(
        hass, max_sync_offset=10.0, real_min_temp=45.0, real_max_temp=90.0
    )
    _configure_real_state(
        hass,
        single_proxy,
        HVACMode.HEAT,
        {
            "current_temperature": 60.0,
            "temperature": 62.0,
            "target_temp_step": 1.0,
            "min_temp": 45.0,
            "max_temp": 90.0,
            "supported_features": (
                ClimateEntityFeature.TARGET_TEMPERATURE
                | ClimateEntityFeature.PRESET_MODE
            ),
        },
        selected_sensor="Sensor 1",
        remote_temp="62.0",
    )
    single_proxy._virtual_target_temperature = 75.0

    await single_proxy.async_set_preset_mode("Physical")

    calls = _climate_set_calls(hass)
    assert len(calls) == 1
    assert calls[0].args[2]["temperature"] == 75.0


@pytest.mark.asyncio
async def test_remote_sensor_large_room_gap_with_small_sensor_offset_succeeds(hass):
    """Large target-vs-sensor gap with small sensor-vs-real offset is not blocked or clamped."""
    # Dual set_temperature and realignment: sensor=62.0, real_current=63.0 (1° offset),
    # target_high=74.0 (12° room gap > 10° max_sync_offset) -> real_high=75.0.
    dual_proxy = create_proxy(
        hass, max_sync_offset=10.0, real_min_temp=45.0, real_max_temp=90.0
    )
    _configure_real_state(
        hass,
        dual_proxy,
        HVACMode.HEAT_COOL,
        {
            "current_temperature": 63.0,
            "target_temp_low": 65.0,
            "target_temp_high": 72.0,
            "target_temp_step": 1.0,
            "min_temp": 45.0,
            "max_temp": 90.0,
            "supported_features": (
                ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
                | ClimateEntityFeature.PRESET_MODE
            ),
        },
        selected_sensor="Sensor 1",
        remote_temp="62.0",
    )

    await dual_proxy.async_set_temperature(target_temp_low=68.0, target_temp_high=74.0)

    calls = _climate_set_calls(hass)
    assert len(calls) == 1
    assert calls[0].args[2]["target_temp_low"] == 69.0
    assert calls[0].args[2]["target_temp_high"] == 75.0

    hass.services.async_call.reset_mock()
    dual_proxy._reset_commanded_targets()
    dual_proxy._recent_real_target_requests.clear()
    _configure_real_state(
        hass,
        dual_proxy,
        HVACMode.HEAT_COOL,
        {
            "current_temperature": 63.0,
            "target_temp_low": 65.0,
            "target_temp_high": 72.0,
            "target_temp_step": 1.0,
            "min_temp": 45.0,
            "max_temp": 90.0,
            "supported_features": (
                ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
                | ClimateEntityFeature.PRESET_MODE
            ),
        },
        selected_sensor="Sensor 1",
        remote_temp="62.0",
    )
    dual_proxy._virtual_target_temperature_low = 68.0
    dual_proxy._virtual_target_temperature_high = 74.0

    await dual_proxy._async_realign_real_target_from_sensor()

    calls = _climate_set_calls(hass)
    assert len(calls) == 1
    assert calls[0].args[2]["target_temp_low"] == 69.0
    assert calls[0].args[2]["target_temp_high"] == 75.0

    hass.services.async_call.reset_mock()

    # Single set_temperature and realignment: sensor=62.0, real_current=63.0, target=74.0 -> 75.0
    single_proxy = create_proxy(
        hass, max_sync_offset=10.0, real_min_temp=45.0, real_max_temp=90.0
    )
    _configure_real_state(
        hass,
        single_proxy,
        HVACMode.HEAT,
        {
            "current_temperature": 63.0,
            "temperature": 65.0,
            "target_temp_step": 1.0,
            "min_temp": 45.0,
            "max_temp": 90.0,
            "supported_features": (
                ClimateEntityFeature.TARGET_TEMPERATURE
                | ClimateEntityFeature.PRESET_MODE
            ),
        },
        selected_sensor="Sensor 1",
        remote_temp="62.0",
    )

    await single_proxy.async_set_temperature(temperature=74.0)

    calls = _climate_set_calls(hass)
    assert len(calls) == 1
    assert calls[0].args[2]["temperature"] == 75.0

    hass.services.async_call.reset_mock()
    single_proxy._reset_commanded_targets()
    single_proxy._recent_real_target_requests.clear()
    _configure_real_state(
        hass,
        single_proxy,
        HVACMode.HEAT,
        {
            "current_temperature": 63.0,
            "temperature": 65.0,
            "target_temp_step": 1.0,
            "min_temp": 45.0,
            "max_temp": 90.0,
            "supported_features": (
                ClimateEntityFeature.TARGET_TEMPERATURE
                | ClimateEntityFeature.PRESET_MODE
            ),
        },
        selected_sensor="Sensor 1",
        remote_temp="62.0",
    )
    single_proxy._virtual_target_temperature = 74.0

    await single_proxy._async_realign_real_target_from_sensor()

    calls = _climate_set_calls(hass)
    assert len(calls) == 1
    assert calls[0].args[2]["temperature"] == 75.0


@pytest.mark.asyncio
async def test_faulty_remote_sensor_drift_clamps_without_raising(hass):
    """Faulty remote sensor drifting beyond max_sync_offset clamps cleanly without ValueError."""
    # Single mode cold drift: sensor=40.0, real_current=68.0, target=70.0 -> clamped to 80.0
    single_proxy = create_proxy(
        hass, max_sync_offset=10.0, real_min_temp=45.0, real_max_temp=90.0
    )
    _configure_real_state(
        hass,
        single_proxy,
        HVACMode.HEAT,
        {
            "current_temperature": 68.0,
            "temperature": 68.0,
            "target_temp_step": 1.0,
            "min_temp": 45.0,
            "max_temp": 90.0,
            "supported_features": (
                ClimateEntityFeature.TARGET_TEMPERATURE
                | ClimateEntityFeature.PRESET_MODE
            ),
        },
        selected_sensor="Sensor 1",
        remote_temp="40.0",
    )

    await single_proxy.async_set_temperature(temperature=70.0)

    calls = _climate_set_calls(hass)
    assert len(calls) == 1
    assert calls[0].args[2]["temperature"] == 80.0
    assert single_proxy.target_temperature == 70.0

    hass.services.async_call.reset_mock()
    single_proxy._reset_commanded_targets()
    single_proxy._recent_real_target_requests.clear()

    # Single mode hot drift: sensor=95.0, real_current=68.0, target=70.0 -> clamped to 60.0
    _configure_real_state(
        hass,
        single_proxy,
        HVACMode.COOL,
        {
            "current_temperature": 68.0,
            "temperature": 68.0,
            "target_temp_step": 1.0,
            "min_temp": 45.0,
            "max_temp": 90.0,
            "supported_features": (
                ClimateEntityFeature.TARGET_TEMPERATURE
                | ClimateEntityFeature.PRESET_MODE
            ),
        },
        selected_sensor="Sensor 1",
        remote_temp="95.0",
    )

    await single_proxy.async_set_temperature(temperature=70.0)

    calls = _climate_set_calls(hass)
    assert len(calls) == 1
    assert calls[0].args[2]["temperature"] == 60.0
    assert single_proxy.target_temperature == 70.0

    hass.services.async_call.reset_mock()

    # Dual mode cold drift: sensor=40.0, real_current=68.0, low=68.0, high=74.0 -> 78.0, 84.0
    dual_proxy = create_proxy(
        hass, max_sync_offset=10.0, real_min_temp=45.0, real_max_temp=90.0
    )
    _configure_real_state(
        hass,
        dual_proxy,
        HVACMode.HEAT_COOL,
        {
            "current_temperature": 68.0,
            "target_temp_low": 65.0,
            "target_temp_high": 75.0,
            "target_temp_step": 1.0,
            "min_temp": 45.0,
            "max_temp": 90.0,
            "supported_features": (
                ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
                | ClimateEntityFeature.PRESET_MODE
            ),
        },
        selected_sensor="Sensor 1",
        remote_temp="40.0",
    )

    await dual_proxy.async_set_temperature(target_temp_low=68.0, target_temp_high=74.0)

    calls = _climate_set_calls(hass)
    assert len(calls) == 1
    assert calls[0].args[2]["target_temp_low"] == 78.0
    assert calls[0].args[2]["target_temp_high"] == 84.0
    assert dual_proxy.target_temperature_low == 68.0
    assert dual_proxy.target_temperature_high == 74.0


@pytest.mark.asyncio
async def test_unavailable_remote_sensor_fallback_passthrough_without_real_current(
    hass,
):
    """Unavailable remote sensor fallback passes single and dual targets directly even if real_current is None."""
    single_proxy = create_proxy(
        hass, max_sync_offset=10.0, real_min_temp=45.0, real_max_temp=90.0
    )
    _configure_real_state(
        hass,
        single_proxy,
        HVACMode.HEAT,
        {
            "current_temperature": None,
            "temperature": 68.0,
            "target_temp_step": 1.0,
            "min_temp": 45.0,
            "max_temp": 90.0,
            "supported_features": (
                ClimateEntityFeature.TARGET_TEMPERATURE
                | ClimateEntityFeature.PRESET_MODE
            ),
        },
        selected_sensor="Sensor 1",
        remote_temp="unavailable",
    )

    assert not single_proxy._is_remote_sensor_controlling()

    await single_proxy.async_set_temperature(temperature=74.0)

    calls = _climate_set_calls(hass)
    assert len(calls) == 1
    assert calls[0].args[2]["temperature"] == 74.0
    assert single_proxy.target_temperature == 74.0

    hass.services.async_call.reset_mock()

    dual_proxy = create_proxy(
        hass, max_sync_offset=10.0, real_min_temp=45.0, real_max_temp=90.0
    )
    _configure_real_state(
        hass,
        dual_proxy,
        HVACMode.HEAT_COOL,
        {
            "current_temperature": None,
            "target_temp_low": 66.0,
            "target_temp_high": 72.0,
            "target_temp_step": 1.0,
            "min_temp": 45.0,
            "max_temp": 90.0,
            "supported_features": (
                ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
                | ClimateEntityFeature.PRESET_MODE
            ),
        },
        selected_sensor="Sensor 1",
        remote_temp="unavailable",
    )

    assert not dual_proxy._is_remote_sensor_controlling()

    await dual_proxy.async_set_temperature(target_temp_low=68.0, target_temp_high=74.0)

    calls = _climate_set_calls(hass)
    assert len(calls) == 1
    assert calls[0].args[2]["target_temp_low"] == 68.0
    assert calls[0].args[2]["target_temp_high"] == 74.0
    assert dual_proxy.target_temperature_low == 68.0
    assert dual_proxy.target_temperature_high == 74.0
