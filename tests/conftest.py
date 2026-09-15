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
    async_step_user and async_step_claim can) causes the config entries
    manager to immediately call async_setup_entry for real. That function
    does two things no test should ever do for real:

    1. _delete_stock_components() — deletes frontend/analytics/cloud from
       the ACTUAL installed homeassistant package running this very test
       suite. This is not hypothetical: an earlier version of this test
       suite did not have this fixture, and running it once deleted those
       three directories from the pytest-homeassistant-custom-component
       venv, breaking every subsequent test run's collection (bootstrap.py
       itself hard-imports `config`, which hard-imports `frontend` — see
       this repo's README, "Cleanup deletion" section, for the full
       finding). _delete_stock_components has its own dedicated, isolated
       tests in test_init.py that verify it safely, against a fake
       tmp_path package tree — it must never run un-mocked here.
    2. sio.connect(...) — a real outbound socketio connection attempt to
       api.willo.sh, which is slow, flaky in a sandboxed test environment,
       and irrelevant to what config_flow/init tests are checking.

    Autouse + module-wide (not just one test) because it is easy to add a
    new test that reaches CREATE_ENTRY and forget this — the cost of
    forgetting is silently corrupting the test venv's own HA install.
    """
    with (
        patch("custom_components.willo._delete_stock_components"),
        patch("custom_components.willo.socketio.AsyncClient.connect", new=AsyncMock()),
    ):
        yield
