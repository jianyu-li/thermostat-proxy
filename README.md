
# Thermostat Proxy (Home Assistant)

![Thermostat Proxy icon](custom_components/thermostat_proxy/icon.png)

A Home Assistant custom integration that lets you expose a virtual `climate` entity which mirrors a real thermostat but lets you pick any temperature sensor to act as the “current temperature”. When you change the virtual target temperature, the integration calculates the difference between the selected sensor and the requested set point, then offsets the real thermostat so it behaves as if it were reading the chosen sensor.

## Installation via HACS

[![Add to Home Assistant](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?repository=thermostat-proxy&category=integration&owner=jianyu-li)

![Thermostat Proxy screenshot](images/main.png)
![Comparison diagram](images/comparison.png)

## Features

- Wraps an existing `climate` entity; copies all of its attributes for dashboards/automations.
- Supports any number of temperature sensors. Each named sensor becomes a `preset_mode`, so changing the preset swaps the active sensor.
- Falls back to the real thermostat’s `current_temperature` whenever the selected sensor is unknown or unavailable.
- `climate.set_temperature` service adjusts the linked thermostat by the delta between the selected sensor reading and your requested temperature.
- Exposes helper attributes: active sensor, sensor entity id, real current temperature, and the last real target temperature.
- Remembers the previously selected sensor/target temperature across restarts and surfaces an `unavailable_entities` attribute so you can monitor unhealthy dependencies.
- Always adds a built-in preset for the wrapped thermostat’s own temperature reading (named `Physical Entity` by default, but you can rename it during setup) so you can revert or set it as the default sensor.
- If someone changes the physical thermostat directly, the proxy automatically switches to the physical preset and logs the change in Home Assistant's logbook.
- "Overdrive" logic: If the remote sensor hasn't reached the target but the physical thermostat thinks it's done (e.g. goes "Idle"), the proxy will temporarily offset the real target by an additional degree to force the HVAC to keep running until the remote sensor is satisfied.
- **Fan Mode Support**: Fully proxies the real thermostat's fan modes. You can control the fan (Auto/On/Low/etc.) seamlessly through the proxy entity.
- **User Log Attribution**: Logbook entries for target temperature or preset changes will show which user performed the action.
- **Safety Limits**: Configure custom `min_temp` and `max_temp` bounds. Calculated targets are clamped to these limits to prevent extreme requests due to sensor anomalies or to respect operational restrictions enforced by certain thermostats that aren't exposed through their Home Assistant attributes.
- Default sensor selector includes a "Last active sensor" option (during setup or in options) so the proxy resumes with the most recently selected sensor instead of the configured default.

## Configuration

| Option | Required | Default | Description |
|---|---|---|---|
| `name` | Yes | `Thermostat Proxy` | The name of the virtual climate entity. |
| `thermostat` | Yes | | The entity ID of the physical thermostat to wrap. |
| `target_sensor` | No | | The entity ID of the default temperature sensor to use. If not specified, the proxy will default to the `Physical Entity` preset. |
| `physical_sensor_name` | No | `Physical Entity` | The name of the preset representing the physical thermostat itself. |
| `cooldown_period` | No | `0` (Disabled) | **Minimum Adjustment Interval**: Minimum time (in seconds) between automatic updates to the physical thermostat. Useful for preventing rapid cycling with noisy sensors. Retries automatically when cooldown expires. |
| `min_temp` | No | `0` (Disabled) | **Minimum Safe Temperature Limit**: Calculated targets sent to the physical thermostat will not go below this value. Set to 0 to disable. |
| `max_temp` | No | `0` (Disabled) | **Maximum Safe Temperature Limit**: Calculated targets sent to the physical thermostat will not exceed this value. Set to 0 to disable. |

## How It Works

- `current_temperature` reflects the selected sensor. If its state is `unknown`/`unavailable`, the entity reports the real thermostat’s own temperature.
- `preset_modes` is populated with the configured sensor names. Calling `climate.set_preset_mode` switches the sensor.
- When you call `climate.set_temperature` on the custom entity, it calculates `delta = requested_temp - displayed_current_temp` and then sets the real thermostat to `real_current_temp + delta`. A two-degree increase relative to the virtual sensor becomes a two-degree increase on the physical thermostat, for example.
- **Overdrive**: If the virtual target is not met (e.g., set to 70, sensor reads 69), but the physical thermostat (satisfied at its own location) goes Idle, the integration detects this "Stall". It then applies a +1° (or -1° for cooling) "Overdrive" offset to the physical thermostat's target to force it to run. This offset sticks until the virtual target is met or the system is no longer stalled.
- **Safety Clamping**: Calculated targets are first clamped to user-configured `min_temp` and `max_temp` safety limits (if set), then further constrained to the physical thermostat's `min_temp`, `max_temp`, and `target_temp_step`. This dual-layer protection prevents extreme values from sensor anomalies. Configuring explicit safety limits is useful for certain thermostats that enforce additional operational restrictions not exposed through their Home Assistant attributes.
- If the physical thermostat’s target changes outside of this integration, the proxy moves to the physical preset and aligns its virtual target with the real target.
- All attributes from the physical thermostat are forwarded as extra attributes, alongside:
  - `active_sensor`
  - `active_sensor_entity_id`
  - `real_current_temperature`
  - `real_target_temperature`
  - `sensor_options`
  - `unavailable_entities`

## Automations / Service Examples

Switch the active sensor (preset):

```yaml
action: climate.set_preset_mode
target:
  entity_id: climate.living_room_proxy
data:
  preset_mode: Kitchen
```

Set a sensor-based target temperature:

```yaml
action: climate.set_temperature
target:
  entity_id: climate.living_room_proxy
data:
  temperature: 73
```

The integration will take the currently selected sensor’s temperature, compare it to the requested value, and offset the real thermostat accordingly.

Automatically move the proxy to the kitchen sensor whenever the fireplace is running so the extra heat doesn’t throw off the default thermostat, then fall back to the physical preset (renamed if you customized it) once the fire is off:

```yaml
alias: Thermostat Mode Adjust
description: Automatically adjust thermostat proxy preset mode.
triggers:
  - trigger: state
    entity_id:
      - switch.fireplace
    to:
      - "on"
    id: Fireplace On
    from:
      - "off"
  - trigger: state
    entity_id:
      - switch.fireplace
    to:
      - "off"
    id: Fireplace Off
    from:
      - "on"
conditions: []
actions:
  - choose:
      - conditions:
          - condition: trigger
            id:
              - Fireplace On
        sequence:
          - action: climate.set_preset_mode
            data:
              preset_mode: Kitchen
            target:
              entity_id: climate.custom_thermostat
      - conditions:
          - condition: trigger
            id:
              - Fireplace Off
        sequence:
          - action: climate.set_preset_mode
            data:
              preset_mode: Physical Entity
            target:
              entity_id: climate.custom_thermostat
mode: single
```

## Limitations / Notes

- The component assumes a single target temperature (heat, cool, or auto with a shared set point). Dual set points (`target_temp_low` / `target_temp_high`) are not supported.
- Because Home Assistant does not expose the real thermostat’s precision/step directly, changes to `current_temperature` or the linked thermostat may momentarily desync the displayed target temperature if another integration changes the physical thermostat. The entity exposes the real target temperature as an attribute so you can reconcile differences.
- Manual changes made directly on the physical thermostat will switch the proxy to the physical preset and align the virtual target with the real set point while recording a logbook entry.
- If you pick a specific default sensor instead of "Last active sensor", the proxy will fall back to that default after a restart even if you had switched to a different preset earlier.
- This integration does not use humidity data for its core logic (e.g., temperature control), but it does expose the underlying thermostat's humidity reading as a real_current_humidity attribute for visibility.

## Contributing

Contributions are welcome! Feel free to create a new branch and submit pull a request!
