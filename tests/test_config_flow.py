"""Real, in-process tests for custom_components/willo/config_flow.py —
covering both entry points into a Willo config entry:

- async_step_user: the human pairing-code flow (existing behaviour).
- async_step_claim: Willo Local's headless entry point, added for
  OxyHQ/Willo issue #9. This is the step the orchestrator WOULD use if it
  ran inside HA Core's own process — it doesn't (see orchestrator/ha_entry.py
  for what the orchestrator actually does instead, and config_flow.py's
  module doc comment for why), but this step must still work correctly
  for any in-process caller (a future add-on architecture, an automation,
  a script).
"""

from __future__ import annotations

from homeassistant import config_entries, data_entry_flow
from homeassistant.core import HomeAssistant

from custom_components.willo.const import CONF_HOME_ID, CONF_SECRET, DEFAULT_PAIR_URL, DOMAIN


async def test_user_step_valid_code_creates_entry(hass: HomeAssistant, aioclient_mock) -> None:
    """A valid pairing code exchanges for {homeId, secret} and creates the entry."""
    aioclient_mock.post(DEFAULT_PAIR_URL, json={"homeId": "home_abc123", "secret": "s3cr3t"})

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": "abc12345"}
    )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["title"] == "Willo"
    assert result["data"] == {CONF_HOME_ID: "home_abc123", CONF_SECRET: "s3cr3t"}
    # the code is upper-cased before being sent, per async_step_user
    assert aioclient_mock.mock_calls[0][2] == {"code": "ABC12345"}


async def test_user_step_invalid_code_shows_error(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.post(DEFAULT_PAIR_URL, status=404)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": "wrongcode"}
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_code"}


async def test_user_step_cannot_connect_shows_error(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.post(DEFAULT_PAIR_URL, exc=Exception("boom"))

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": "abc12345"}
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}


async def test_claim_step_creates_entry_with_no_http_call(hass: HomeAssistant, aioclient_mock) -> None:
    """The headless claim step (Willo Local) creates the entry directly —
    no form, no HTTP call to DEFAULT_PAIR_URL at all.
    """
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "claim"},
        data={CONF_HOME_ID: "home_xyz789", CONF_SECRET: "claimed-secret"},
    )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["title"] == "Willo"
    assert result["data"] == {CONF_HOME_ID: "home_xyz789", CONF_SECRET: "claimed-secret"}
    assert len(aioclient_mock.mock_calls) == 0


async def test_claim_step_without_data_aborts(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "claim"})

    assert result["type"] == data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "claim_requires_data"


async def test_claim_step_with_incomplete_data_aborts(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "claim"}, data={CONF_HOME_ID: "home_only"}
    )

    assert result["type"] == data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "claim_invalid_data"


async def test_claim_step_same_home_twice_aborts_already_configured(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """Re-claiming the SAME home_id onto an instance that already holds it
    must not silently replace the stored secret — this mirrors
    async_step_user's pre-existing duplicate-pairing guard exactly (see
    _async_finish_entry), verified here for the new claim step.

    (conftest.py's autouse fixture keeps the CREATE_ENTRY below from
    triggering a real socketio connection or a real analytics/cloud
    deletion against this test venv's own homeassistant install.)
    """
    first = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "claim"}, data={CONF_HOME_ID: "home_one", CONF_SECRET: "s1"}
    )
    assert first["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    second = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "claim"}, data={CONF_HOME_ID: "home_one", CONF_SECRET: "s2-different"}
    )
    assert second["type"] == data_entry_flow.FlowResultType.ABORT
    assert second["reason"] == "already_configured"
