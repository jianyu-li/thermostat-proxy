"""Fixtures for the Thermostat Proxy tests."""

from unittest.mock import AsyncMock, patch

import pytest

from homeassistant.core import HomeAssistant


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations in Home Assistant tests."""
    yield


@pytest.fixture(autouse=True)
def mock_dependencies():
    """Mock required dependencies so they don't try to load."""
    with patch("homeassistant.setup.async_setup_component", return_value=True):
        yield


@pytest.fixture
def hass(hass: HomeAssistant):
    """Provide a real hass instance with mocked services for unit tests."""
    mock_async_call = AsyncMock()
    with patch("homeassistant.core.ServiceRegistry.async_call", new=mock_async_call):
        yield hass
