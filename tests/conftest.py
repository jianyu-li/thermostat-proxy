"""Fixtures for the Thermostat Proxy tests."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations in Home Assistant tests."""
    yield


@pytest.fixture(autouse=True)
def mock_dependencies():
    """Mock required dependencies so they don't try to load."""
    from unittest.mock import patch

    with patch("homeassistant.setup.async_setup_component", return_value=True):
        yield
