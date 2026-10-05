"""Shared fixtures for willo-ha's tests.

Run with: pip install pytest-homeassistant-custom-component, then
`pytest tests/` from the repo root. This uses the real
`pytest-homeassistant-custom-component` harness (a real, minimal
in-process HomeAssistant instance per test — not a mock of HA itself),
matching how the wider HA custom-component ecosystem tests integrations.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Make custom_components/willo loadable by hass.config_entries.flow.async_init in tests."""
    yield


@pytest.fixture(autouse=True)
def _prevent_real_side_effects_from_async_setup_entry():
    """Any test that drives a Willo config flow to CREATE_ENTRY (both
    async_step_user and async_step_claim can) makes the config entries
    manager call async_setup_entry for real, which opens a real outbound
    socket.io connection to api.willo.sh. That is slow, flaky in a sandbox
    and irrelevant to what these tests check, so connect is mocked for
    every test.
    """
    with patch("custom_components.willo.socketio.AsyncClient.connect", new=AsyncMock()):
        yield
