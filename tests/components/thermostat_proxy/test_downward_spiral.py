import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
import time

from custom_components.thermostat_proxy.const import DOMAIN, CONF_THERMOSTAT, CONF_SENSORS, CONF_DISABLE_AUTO_SWITCH

@pytest.mark.asyncio
async def test_downward_spiral_prevention(hass: HomeAssistant) -> None:
    """Test that thermostat snapping does not cause a downward spiral."""
    mode = "heat_cool"
    
    hass.states.async_set(
        "climate.real",
        mode,
        {
            "current_temperature": 20.0,
            "target_temp_low": 18.0,
            "target_temp_high": 24.0,
            "target_temp_step": 1.0,
            "supported_features": 3,
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
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    component = hass.data["climate"]
    entity = component.get_entity("climate.thermostat_proxy")
    
    # Simulate a proxy target request (proxy wants high 26, low 20)
    # The proxy sends this to the thermostat and records it.
    entity._record_real_target_request(20.0)
    entity._record_real_target_request(26.0)
    
    # Simulate thermostat snapping high to 25.0 after a delay (WITHIN grace period)
    # The proxy should ignore the change because it's within the 45s grace period.
    entity._last_real_write_time = time.monotonic() - 10.0  # Inside grace period
    entity._last_real_target_temp_low = 18.0
    entity._last_real_target_temp_high = 24.0
    
    # Store virtual targets
    entity._virtual_target_temperature_low = 20.0
    entity._virtual_target_temperature_high = 26.0
    
    # The physical thermostat updates both, but one is snapped (25 instead of 26)
    entity._detect_external_dual_target_change(20.0, 25.0, was_not_controlling=False)
    
    # Because it is within the grace period, external changes are skipped.
    # HOWEVER, the pending request for 20.0 MUST STILL have been consumed!
    assert entity._virtual_target_temperature_low == 20.0
    
    # High change is ignored, so virtual high remains 26.0
    assert entity._virtual_target_temperature_high == 26.0
    
    # Crucially, the pending request for 20.0 MUST have been consumed.
    assert len(entity._recent_real_target_requests) == 1
    assert entity._recent_real_target_requests[0][0] == 26.0

