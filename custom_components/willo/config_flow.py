"""Config flow for Willo.

Two entry points create the same kind of entry, for two different
audiences:

- `async_step_user` — a human, manually installing this integration via
  HACS on their own pre-existing Home Assistant instance, typing an
  8-character pairing code they read off the Willo app. No instance URL,
  no OAuth client id, no "Advanced" section: that's the whole point of the
  pairing-code design (see __init__.py).
- `async_step_claim` — Willo Local's on-device orchestrator (see
  OxyHQ/Willo issue #9 and this repo's `orchestrator/` package), once it
  already holds a `{home_id, secret}` pair straight from Willo's backend
  (POST /tunnel/claim + GET /tunnel/claim/status — no pairing code to
  type, nothing to redeem here). This step does no HTTP call and shows no
  form; it exists purely so a *source* other than `user` can create a
  Willo entry the same way `async_step_user` does on success.

  IMPORTANT, verified empirically against a real local HA Core instance
  (see this repo's README "Headless config-entry creation" section): HA's
  config-entries REST flow API (`POST /api/config/config_entries/flow`)
  hardcodes `context["source"] = SOURCE_USER` for every externally
  initiated flow (see `homeassistant/components/config/config_entries.py`,
  `ConfigManagerFlowIndexView.get_context`) — there is no request body
  field that reaches a non-`user` source through that endpoint. That
  means an EXTERNAL process (the orchestrator, running outside HA Core's
  own Python process) cannot trigger `async_step_claim` over HTTP. This
  step is still correct to keep — `hass.config_entries.flow.async_init(
  DOMAIN, context={"source": "claim"}, data=...)` is the real, standard
  way to reach it, but only from code running *inside* the same HA Core
  process (another integration, a script, or a future first-party
  Supervisor add-on architecture that runs in-process). The orchestrator,
  being an external process, instead writes the config entry directly
  into `.storage/core.config_entries` and restarts Core — see
  `orchestrator/ha_entry.py`'s module doc comment for the exact schema
  confirmed against this HA version, and for why that's the mechanism
  actually used end-to-end today.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_HOME_ID, CONF_SECRET, DEFAULT_PAIR_URL, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema({vol.Required("code"): str})
STEP_CLAIM_SCHEMA = vol.Schema({vol.Required(CONF_HOME_ID): str, vol.Required(CONF_SECRET): str})


class WilloConfigFlow(ConfigFlow, domain=DOMAIN):
    """Exchange a pairing code (from the Willo app) for a tunnel secret —
    or, for Willo Local's orchestrator, accept an already-known
    {home_id, secret} pair directly. See this module's doc comment.
    """

    VERSION = 1

    async def _async_finish_entry(self, home_id: str, secret: str) -> ConfigFlowResult:
        """Shared by async_step_user and async_step_claim: one Willo Home
        per Home Assistant instance, so a second code/claim on an
        already-paired instance replaces nothing here — that has to go
        through Willo's own "create another home" flow instead.
        """
        await self.async_set_unique_id(home_id)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title="Willo",
            data={CONF_HOME_ID: home_id, CONF_SECRET: secret},
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            code = user_input["code"].strip().upper()
            session = async_get_clientsession(self.hass)
            try:
                async with session.post(DEFAULT_PAIR_URL, json={"code": code}) as response:
                    if response.status == 200:
                        data = await response.json()
                        return await self._async_finish_entry(data["homeId"], data["secret"])
                    if response.status == 404:
                        errors["base"] = "invalid_code"
                    else:
                        errors["base"] = "cannot_connect"
            except (aiohttp.ClientError, TimeoutError):
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001 - any other failure must still show the form again, not crash the flow
                _LOGGER.exception("Unexpected error completing Willo pairing")
                errors["base"] = "unknown"

        return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors)

    async def async_step_claim(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Create an entry directly from an already-known {home_id, secret}
        — no HTTP call, no form ever shown. See this module's doc comment:
        reachable only from code running inside this same HA Core process
        via `hass.config_entries.flow.async_init(DOMAIN,
        context={"source": "claim"}, data={CONF_HOME_ID: ..., CONF_SECRET: ...})`
        — the orchestrator (an external process) cannot reach this over
        HTTP and uses a direct `.storage/core.config_entries` write
        instead (see orchestrator/ha_entry.py).
        """
        if user_input is None:
            return self.async_abort(reason="claim_requires_data")

        try:
            data = STEP_CLAIM_SCHEMA(user_input)
        except vol.Invalid:
            return self.async_abort(reason="claim_invalid_data")

        return await self._async_finish_entry(data[CONF_HOME_ID], data[CONF_SECRET])
