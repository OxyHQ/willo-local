"""The Willo Local orchestrator's entrypoint — implements the boot
sequence from OxyHQ/Willo issue #9:

    1. serve the built willo-claim-ui app + GET /status               (server.py)
    2. poll localhost:8123 until Core's REST API answers               (ha_client.py)
    3. drive HA onboarding via REST                                    (ha_client.py)
    4. delete frontend/analytics/cloud (belt-and-suspenders)           (cleanup.py)
    5. POST /tunnel/claim, poll GET /tunnel/claim/status                (willo_client.py)
    6. write the willo config entry directly, restart Core              (ha_entry.py)
    7. status.stage tracks every real transition above, live            (status.py)

Every environment-specific value is a WILLO_* env var — nothing about a
real device's HA config directory or address is hardcoded here (see
AGENTS.md's "Environment configuration" — this repo follows it too, even
though it predates that file).
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
from pathlib import Path

import aiohttp

from . import cleanup
from .const import DEFAULT_CLAIM_STATUS_URL, DEFAULT_CLAIM_URL, DEFAULT_HA_BASE_URL
from .ha_client import HAClient, HAClientError
from .ha_entry import has_willo_entry, write_willo_entry
from .server import run_server
from .status import new_status
from .willo_client import WilloClaimClient

_LOGGER = logging.getLogger(__name__)

# "Willo Service Account" style naming per the earlier design conversation
# (never a human-meaningful admin name) — random hex, not a guessable
# fixed string, since this account has full admin rights on Core.
_ADMIN_NAME = "Willo Service Account"


def _env_path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default))


async def _drive_onboarding(ha: HAClient, *, base_url: str) -> str:
    """Runs all four onboarding steps, in order, only for the ones not
    already marked done — idempotent, since a crash/restart mid-onboarding
    must be able to resume rather than fail forever on "step already done".

    Returns a refresh_token: the boot sequence needs a valid access token
    much later too (to call the homeassistant.restart service after the
    claim completes), and onboarding's own access token is only valid for
    30 minutes — easily outlasted by a real person taking their time to
    open the Willo app and tap "claim". The refresh token is what lets the
    orchestrator mint a fresh one right before it's actually needed.
    """
    onboarding_status = await ha.get_onboarding_status()
    done_steps = {step["step"] for step in onboarding_status if step["done"]}

    client_id = f"{base_url}/"
    redirect_uri = f"{base_url}/"

    if "user" in done_steps:
        # Already done (a resumed/crashed earlier run) — there is no HA
        # REST endpoint to fetch a fresh auth_code for an already-onboarded
        # user, so this orchestrator cannot resume past this exact point
        # without its own persisted token. Out of scope to solve generically
        # here; the sandbox tests in this repo always run onboarding
        # start-to-finish in one pass.
        raise HAClientError(
            "Onboarding's 'user' step is already done but no access token was persisted — "
            "cannot resume onboarding from this exact point"
        )

    username = f"willo-svc-{secrets.token_hex(4)}"
    password = secrets.token_urlsafe(24)
    auth_code = await ha.create_admin_user(
        name=_ADMIN_NAME, username=username, password=password, client_id=client_id
    )
    _LOGGER.info("Created throwaway HA admin user %s", username)

    tokens = await ha.exchange_auth_code(auth_code=auth_code, client_id=client_id)
    access_token = tokens["access_token"]

    if "core_config" not in done_steps:
        await ha.finish_core_config_step(access_token=access_token)
    if "analytics" not in done_steps:
        await ha.finish_analytics_step(access_token=access_token)
    if "integration" not in done_steps:
        await ha.finish_integration_step(access_token=access_token, client_id=client_id, redirect_uri=redirect_uri)

    _LOGGER.info("Onboarding complete")
    refresh_token: str = tokens["refresh_token"]
    return refresh_token


async def async_main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    ha_base_url = os.environ.get("WILLO_HA_BASE_URL", DEFAULT_HA_BASE_URL)
    ha_config_dir = _env_path("WILLO_HA_CONFIG_DIR", "/config")
    # Overridable for the same reason custom_components/willo/const.py's
    # DEFAULT_PAIR_URL/DEFAULT_TUNNEL_URL are: an advanced/self-hosted-
    # backend option, and what lets this repo's own sandbox tests point at
    # a throwaway local stub instead of the real production backend.
    claim_url = os.environ.get("WILLO_CLAIM_URL", DEFAULT_CLAIM_URL)
    claim_status_url = os.environ.get("WILLO_CLAIM_STATUS_URL", DEFAULT_CLAIM_STATUS_URL)
    static_dir = _env_path("WILLO_STATIC_DIR", str(Path(__file__).parent.parent.parent / "willo-claim-ui" / "dist"))
    host = os.environ.get("WILLO_HOST", "0.0.0.0")
    port = int(os.environ.get("WILLO_PORT", "8080"))

    status = new_status()
    runner = await run_server(status, static_dir, host=host, port=port)

    try:
        async with aiohttp.ClientSession() as session:
            ha = HAClient(session, base_url=ha_base_url)

            status.stage = "onboarding"
            await ha.wait_until_api_ready()

            if has_willo_entry(ha_config_dir):
                _LOGGER.info("A willo config entry already exists in %s — nothing left to do", ha_config_dir)
                status.stage = "paired"
            else:
                refresh_token = await _drive_onboarding(ha, base_url=ha_base_url)

                status.stage = "syncing"
                await asyncio.get_running_loop().run_in_executor(None, cleanup.delete_stock_components)

                claim_client = WilloClaimClient(session, claim_url=claim_url, claim_status_url=claim_status_url)
                claim = await claim_client.request_claim()

                status.stage = "awaiting-pairing"
                status.claim_code = claim.claim_code
                _LOGGER.info("Awaiting pairing — claim code %s (expires %s)", claim.claim_code, claim.expires_at)

                claim_status = await claim_client.wait_for_claim(claim.claim_token)
                if claim_status.status != "claimed" or not claim_status.home_id or not claim_status.secret:
                    raise HAClientError(f"Claim did not complete successfully: {claim_status}")

                write_willo_entry(ha_config_dir, home_id=claim_status.home_id, secret=claim_status.secret)

                # A fresh access token: onboarding's own token is only
                # valid for 30 minutes, easily outlasted by the real time
                # spent waiting above for a person to tap "claim" in the
                # Willo app.
                fresh_access_token = await ha.refresh_access_token(
                    refresh_token=refresh_token, client_id=f"{ha_base_url}/"
                )
                await ha.restart_core(access_token=fresh_access_token)

                status.stage = "paired"
                status.claim_code = None
                _LOGGER.info("Paired. Restart requested — see this repo's README for how a plain-venv "
                             "sandbox needs an external process to actually relaunch `hass` after this "
                             "call, versus real HAOS where Supervisor does it.")

    except Exception as error:  # noqa: BLE001 - the claim UI must show an error state, not go blank, on ANY failure in this boot sequence
        # Deliberately NOT re-raised: the HTTP server (started above) must
        # stay up so the claim UI keeps polling /status and can show this
        # error to a person standing in front of the device, instead of
        # the whole process dying and willo.local going unreachable.
        _LOGGER.exception("Willo orchestrator boot sequence failed")
        status.error = str(error)

    # Keep the process (and its HTTP server) alive forever — see server.py's
    # doc comment: this is the device's ONLY permanent public HTTP surface.
    await asyncio.Event().wait()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
