# Thermostat Proxy (Home Assistant Custom Component)

## Project Overview

**Thermostat Proxy** is a Home Assistant custom integration that creates a virtual `climate` entity. This entity mirrors a real, physical thermostat but allows the user to select any temperature sensor in Home Assistant to act as the reference "current temperature".

The core logic involves calculating the difference (delta) between the selected remote sensor and the desired target temperature, then adjusting the physical thermostat's setpoint by that offset. This effectively allows a remote sensor to control the HVAC system.

## Key Features

*   **Virtual Control:** Wraps an existing `climate` entity and proxies all attributes (fan modes, HVAC modes, etc.).
*   **Sensor Switching:** Maps configured temperature sensors to `preset_modes`. Switching the preset changes the active control sensor.
*   **Offset Logic:** Automatically adjusts the physical thermostat to achieve the target temperature at the remote sensor's location.
*   **Overdrive Mode:** Detects if the physical thermostat is "satisfied" (Idle) while the remote sensor is not, and applies an extra offset to force the system to run.
*   **Safety Limits:** Allows user-configurable `min_temp` and `max_temp` to prevent extreme target setpoints being sent to the physical hardware.
*   **Fan Mode Support:** Seamlessly proxies and controls the physical thermostat's fan modes.
*   **Last Active Sensor:** Option to resume with the most recently selected sensor instead of a fixed default.
*   **Fallback:** Automatically reverts to the physical thermostat's internal sensor if the remote sensor becomes unavailable.
*   **Logbook Attribution:** Tracks which user changed the target temperature or preset.
*   **Configuration:** Fully supports UI-based configuration via Config Flow (add/remove sensors, rename presets, etc.).

## Architecture & Module Organization

The project follows the standard Home Assistant custom component structure:

*   **`custom_components/thermostat_proxy/`**: The core package.
    *   `climate.py`: Hosts the entity logic and `CustomThermostatEntity` class (state updates, offset calculation, service calls).
    *   `config_flow.py`: Handles the UI setup (Config Flow) and Options Flow.
    *   `const.py`: Centralizes constants, attribute names, and defaults.
    *   `manifest.json`: Metadata defining the domain, dependencies (`logbook`), and version.
    *   `translations/`: Localization files (e.g., `en.json`) for UI strings.

**External References:**
- `icons/`: Drop new assets here for HACS bundling.
- `tmp_better_thermostat/`: Read-only upstream reference used for comparisons. Keep its history separate.

## Build, Test, and Development Commands

1. `python3 -m venv .venv && source .venv/bin/activate` — Create an isolated environment.
2. `pip install -r tmp_better_thermostat/requirements.dev.txt` — Install Home Assistant and linting tools.
3. `ruff check custom_components/thermostat_proxy` — Static analysis aligned with HA guidance.
4. `black custom_components/thermostat_proxy` — Enforce 88-character formatting.
5. `codespell custom_components/thermostat_proxy README.md` — Catch typos.
6. `hass --script check_config -c /path/to/ha-config` — Validate component configuration.

### Prerequisites

*   Python 3.10+ (consistent with Home Assistant requirements).
*   Home Assistant instance (for running the integration).

### Testing Guidelines

*   **Manual Testing:** Load the integration into a dev instance and exercise presets, temperature changes, and fallback behavior (e.g., unavailable sensors).
*   **Automated Tests:** The project uses `pytest`. Future tests should follow HA's `tests/components/<domain>` naming and cover edge cases like missing sensors and precision clamping.

### CI/CD

GitHub Actions are configured in `.github/workflows/`:
*   `hassfest.yaml`: Validates against Home Assistant standards.
*   `validate.yaml`: Runs linting and validation.
*   `release-assets.yaml`: Manages release artifacts.

## Coding Style & Naming Conventions

*   **Style:** Follow Home Assistant’s async-first Python style (4-space indentation, type hints, dataclasses for payloads).
*   **I/O:** Guard all I/O behind `async_*` helpers.
*   **Constants:** Use upper snake case in `const.py` (e.g., `ATTR_ACTIVE_SENSOR`).
*   **UI:** User-facing presets use Title Case; internal IDs use `snake_case`.
*   **Logging:** Concise and structured (e.g., `_LOGGER.debug("Delta %s", delta)`).

## Manifest & Hassfest Rules

- Keep `manifest.json` keys sorted: `domain`, `name`, then other keys in strict alphabetical order.
- Add imported HA components to `dependencies` or `after_dependencies` in `manifest.json`.

## Usage & Deployment

### Deployment to Home Assistant
- Sync files to your Home Assistant instance (e.g., `/Volumes/config/custom_components/thermostat_proxy`).
- Use `rsync` to avoid `__pycache__` artifacts:
  `rsync -a --delete --exclude '__pycache__/' --exclude '*.pyc' custom_components/thermostat_proxy/ /Volumes/config/custom_components/thermostat_proxy/`
- Note: Elevation may be required for certain target directories.

### Configuration
1.  **Installation:** Install via HACS or copy `custom_components/thermostat_proxy` to your `custom_components` directory.
2.  **Setup:**
    *   Add via **Settings > Devices & Services > Add Integration**.
    *   Select the physical thermostat to control and add temperature sensors.
3.  **Operation:**
    *   The proxy `climate` entity will appear.
    *   Change `preset_mode` to switch between sensors.
    *   Set target temperature on the proxy entity.

## Commit & Pull Request Guidelines

- **Commits:** Short, Title Case, imperative (e.g., `Set 1° Fallback Step`).
- **PRs:** Focused on one topic, including motivation and testing evidence (screenshots/commands). Call out migration steps for existing users.

## Security & Privacy Notes

- **Secrets:** Never hard-code credentials; use `secrets.yaml` placeholders.
- **Privacy:** Ensure debug logging does not leak occupancy-revealing sensor data.
- **Rules:** Do not include user-identifying information (e.g., real names) in code or docs.

## Agent Rules

- **No Internal Monologue:** Comments must be strictly technical. No conversational text or internal reasoning in code.
- **Privacy:** Maintain strict user privacy in all generated content.
