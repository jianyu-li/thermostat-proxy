"""Regression coverage for missing virtual range targets (issue #54)."""

from types import SimpleNamespace

import pytest

from homeassistant.components.climate import HVACMode
from homeassistant.core import State

from .test_dual_setpoint import create_dual_proxy


def update_real_state(proxy, old_state, new_state):
    proxy._async_handle_real_state_event(
        SimpleNamespace(data={"old_state": old_state, "new_state": new_state})
    )


@pytest.mark.parametrize(
    "mode,previous",
    [
        (HVACMode.HEAT_COOL, None),
        (HVACMode.HEAT_COOL, HVACMode.OFF),
        (HVACMode.AUTO, "unknown"),
        (HVACMode.AUTO, "unavailable"),
    ],
)
async def test_range_entry_initializes_and_realigns(hass, mode, previous):
    proxy = create_dual_proxy(hass, hvac_mode=mode)
    proxy._virtual_target_temperature_low = None
    proxy._virtual_target_temperature_high = None
    old_state = State("climate.real", previous) if previous is not None else None

    update_real_state(proxy, old_state, proxy._real_state)
    await hass.async_block_till_done()

    assert proxy._virtual_target_temperature_low == 18.0
    assert proxy._virtual_target_temperature_high == 24.0
    assert proxy.preset_mode == "Remote"
    calls = [
        c
        for c in hass.services.async_call.call_args_list
        if c.args[:2] == ("climate", "set_temperature")
    ]
    assert len(calls) == 1
    assert calls[0].args[2]["target_temp_low"] == 20.0
    assert calls[0].args[2]["target_temp_high"] == 26.0


async def test_range_targets_arrive_after_mode_change(hass):
    mode = HVACMode.AUTO
    proxy = create_dual_proxy(hass, hvac_mode=mode)
    proxy._virtual_target_temperature_low = None
    proxy._virtual_target_temperature_high = None
    ready = proxy._real_state
    attributes = dict(ready.attributes)
    attributes.pop("target_temp_low")
    attributes.pop("target_temp_high")
    waiting = State("climate.real", mode, attributes)

    update_real_state(proxy, State("climate.real", HVACMode.OFF), waiting)
    await hass.async_block_till_done()
    assert proxy._virtual_target_temperature_low is None
    assert proxy._virtual_target_temperature_high is None
    assert not hass.services.async_call.called

    update_real_state(proxy, waiting, ready)
    await hass.async_block_till_done()
    assert proxy._virtual_target_temperature_low == 18.0
    assert proxy._virtual_target_temperature_high == 24.0
    assert proxy.preset_mode == "Remote"
    assert any(
        c.args[:2] == ("climate", "set_temperature")
        for c in hass.services.async_call.call_args_list
    )


@pytest.mark.parametrize(
    "low,high,expected",
    [
        (19.0, None, (19.0, 24.0)),
        (None, 25.0, (18.0, 25.0)),
        (19.0, 25.0, (19.0, 25.0)),
    ],
)
async def test_range_initialization_preserves_existing_targets(
    hass, low, high, expected
):
    proxy = create_dual_proxy(hass)
    proxy._virtual_target_temperature_low = low
    proxy._virtual_target_temperature_high = high

    update_real_state(proxy, State("climate.real", HVACMode.OFF), proxy._real_state)
    await hass.async_block_till_done()
    assert (
        proxy._virtual_target_temperature_low,
        proxy._virtual_target_temperature_high,
    ) == expected


@pytest.mark.parametrize(
    "previous,expected", [(HVACMode.HEAT, (21.0, 24.0)), (HVACMode.COOL, (18.0, 21.0))]
)
async def test_range_initialization_preserves_single_target_transfer(
    hass, previous, expected
):
    proxy = create_dual_proxy(hass)
    proxy._virtual_target_temperature_low = None
    proxy._virtual_target_temperature_high = None
    proxy._virtual_target_temperature = 21.0

    update_real_state(proxy, State("climate.real", previous), proxy._real_state)
    await hass.async_block_till_done()
    assert (
        proxy._virtual_target_temperature_low,
        proxy._virtual_target_temperature_high,
    ) == expected


async def test_realign_recovers_missing_range_targets(hass):
    proxy = create_dual_proxy(hass)
    proxy._virtual_target_temperature_low = None
    proxy._virtual_target_temperature_high = None

    await proxy._async_realign_real_target_from_sensor()
    assert proxy._virtual_target_temperature_low == 18.0
    assert proxy._virtual_target_temperature_high == 24.0
    assert any(
        c.args[:2] == ("climate", "set_temperature")
        for c in hass.services.async_call.call_args_list
    )
