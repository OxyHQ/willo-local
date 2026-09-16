"""The Willo Local orchestrator's entrypoint — implements the boot
sequence from OxyHQ/Willo issue #9:

    1. serve the built willo-claim-ui app + GET /status               (server.py)
    1a. detect the board model (deviceModel) and rename the host to     (device_model.py,
        "willo" via Supervisor, both independent of onboarding — a       hostname.py)
        no-op under Supervisor-less installs (every sandbox test here)
    2. poll localhost:8123 until Core's REST API answers               (ha_client.py)
    2a. complete onboarding's "user" step (the only unauthenticated one) (ha_client.py)
    2b. write configuration.yaml's explicit allow-list + loopback       (ha_config.py)
        http binding; restart Core if that file changed, then resume
    3. drive the rest of HA onboarding via REST                        (ha_client.py)
    4. delete analytics/cloud, replace frontend with an inert stub      (cleanup.py)
       (belt-and-suspenders — loopback binding in step 2b is the
       load-bearing reachability mechanism; the stub swap is
       defense-in-depth layered on top, not a substitute for it)
    5. POST /tunnel/claim, poll GET /tunnel/claim/status                (willo_client.py)
    6. write the willo config entry directly, restart Core              (ha_entry.py)
    7. status.stage tracks every real transition above, live            (status.py)

Every environment-specific value is a WILLO_* env var — nothing about a
real device's HA config directory or address is hardcoded here (see
AGENTS.md's "Environment configuration" — this repo follows it too, even
though it predates that file).

Step 4 deliberately does NOT delete `frontend` — see cleanup.py's module
doc comment and this repo's README ("Cleanup deletion") for why that was
tried, reverted, and is not safe to reintroduce: it crashes the next
`hass` launch outright, and excluding `frontend` from `configuration.yaml`
does not even stop it from running or serving its real UI — which is
exactly why step 2b's loopback binding exists: it's the mechanism that
was actually verified to make Core's HTTP surface unreachable from
outside this device (see ha_config.py and the README).

Step 2b runs BEFORE the rest of onboarding, right after the "user" step,
because it needs an authenticated token to call the restart service and a
factory-fresh device has no admin account until that one step completes —
and it runs there rather than after the whole of onboarding so Core is
never, even briefly, reachable from the network with onboarding still
in progress.

Safety fix, checked before ANY of the above runs: steps 2a-6 all assume a
factory-fresh, never-onboarded device. `has_meaningful_existing_configuration()`
(ha_config.py) detects a configuration.yaml that already holds real,
hand-authored configuration — a device that is not fresh at all, verified
against a real Home Assistant Green with an 800+ line configuration.yaml,
~15 packages, and months of real automations — and if so, skips the
entire onboarding-automation branch (creating an admin user, rewriting
configuration.yaml, restarting Core for loopback binding, cleanup
deletion, the claim flow, all of it). Only step 1a (hostname rename,
device model detection) and step 1 (serving this status/claim UI) still
run, since neither touches configuration.yaml or assumes onboarding is
incomplete. See status.py's "existing-install" stage.
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
from .device_model import detect_device_model
from .ha_client import HAClient, HAClientError
from .hostname import set_device_hostname
from .ha_config import ensure_explicit_configuration, has_meaningful_existing_configuration
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


async def _complete_user_step(ha: HAClient, *, base_url: str) -> dict[str, str]:
    """Onboarding's "user" step — the only one that needs no pre-existing
    auth, since a factory-fresh device has no admin account yet. Returns
    the token dict from exchanging its auth_code (has "access_token" and
    "refresh_token").

    Not idempotent by design: there is no HA REST endpoint to fetch a
    fresh auth_code for an already-onboarded user, so this orchestrator
    cannot resume past this exact point without its own persisted token.
    Out of scope to solve generically here; the sandbox tests in this
    repo always run onboarding start-to-finish in one pass. Raises if
    this step is already marked done.
    """
    onboarding_status = await ha.get_onboarding_status()
    done_steps = {step["step"] for step in onboarding_status if step["done"]}
    if "user" in done_steps:
        raise HAClientError(
            "Onboarding's 'user' step is already done but no access token was persisted — "
            "cannot resume onboarding from this exact point"
        )

    client_id = f"{base_url}/"
    username = f"willo-svc-{secrets.token_hex(4)}"
    password = secrets.token_urlsafe(24)
    auth_code = await ha.create_admin_user(
        name=_ADMIN_NAME, username=username, password=password, client_id=client_id
    )
    _LOGGER.info("Created throwaway HA admin user %s", username)

    return await ha.exchange_auth_code(auth_code=auth_code, client_id=client_id)


async def _complete_remaining_onboarding_steps(ha: HAClient, *, base_url: str, access_token: str) -> None:
    """core_config, analytics, integration — run only for the ones not
    already marked done, so a crash/restart between these three can
    resume rather than fail forever on "step already done".
    """
    onboarding_status = await ha.get_onboarding_status()
    done_steps = {step["step"] for step in onboarding_status if step["done"]}

    client_id = f"{base_url}/"
    redirect_uri = f"{base_url}/"

    if "core_config" not in done_steps:
        await ha.finish_core_config_step(access_token=access_token)
    if "analytics" not in done_steps:
        await ha.finish_analytics_step(access_token=access_token)
    if "integration" not in done_steps:
        await ha.finish_integration_step(access_token=access_token, client_id=client_id, redirect_uri=redirect_uri)

    _LOGGER.info("Onboarding complete")


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

    # Both independent of the onboarding/pairing state machine below.
    # deviceModel: the Willo app's auto-detect screen wants this as soon as
    # it's available, not gated behind onboarding completing. Hostname:
    # renaming to willo.local doesn't depend on Core being onboarded either
    # — it's a Supervisor-only, OS-level change — and doing it early means
    # the device advertises its real name for as much of the boot sequence
    # as possible.
    status.device_model = await detect_device_model()
    await set_device_hostname()

    try:
        async with aiohttp.ClientSession() as session:
            ha = HAClient(session, base_url=ha_base_url)

            status.stage = "onboarding"
            await ha.wait_until_api_ready()

            if has_willo_entry(ha_config_dir):
                _LOGGER.info("A willo config entry already exists in %s — nothing left to do", ha_config_dir)
                status.stage = "paired"
            elif has_meaningful_existing_configuration(ha_config_dir):
                # Safety fix: this device's configuration.yaml is not a
                # fresh-install default or Willo's own managed template —
                # it holds real, hand-authored configuration (verified
                # against a real Home Assistant Green with an 800+ line
                # configuration.yaml, ~15 packages, and months of real
                # automations; see ha_config.py's module doc comment and
                # this repo's README). The entire onboarding-automation
                # branch below assumes a factory-fresh device (it creates a
                # throwaway admin user, rewrites configuration.yaml, and
                # restarts Core to apply loopback binding) — none of that
                # is safe here, and onboarding's "user" step would just
                # fail outright anyway on a device that finished onboarding
                # months ago. Only what already ran unconditionally above
                # (hostname rename, serving this status/claim UI) applies;
                # configuration.yaml is left byte-for-byte untouched.
                _LOGGER.info(
                    "%s already holds real, hand-authored configuration (not a fresh-install "
                    "default or Willo's own managed template) — skipping onboarding automation, "
                    "the configuration.yaml rewrite, and the loopback-binding restart entirely. "
                    "Only the hostname rename and this status/claim UI are running.",
                    ha_config_dir / "configuration.yaml",
                )
                status.stage = "existing-install"
            else:
                tokens = await _complete_user_step(ha, base_url=ha_base_url)
                access_token = tokens["access_token"]
                refresh_token = tokens["refresh_token"]

                if ensure_explicit_configuration(ha_config_dir):
                    _LOGGER.info(
                        "configuration.yaml did not match the explicit allow-list + loopback-only "
                        "http binding — wrote it and restarting Core to apply it"
                    )
                    await ha.restart_core(access_token=access_token)
                    await ha.wait_until_api_down()
                    await ha.wait_until_api_ready()
                    # A fresh token: restarting Core is exactly the kind of
                    # real elapsed time (plus a brand new process) that
                    # makes re-minting one safer than assuming the old
                    # access_token is still good.
                    access_token = await ha.refresh_access_token(refresh_token=refresh_token, client_id=f"{ha_base_url}/")
                else:
                    _LOGGER.info("configuration.yaml already matches the explicit allow-list — no restart needed")

                await _complete_remaining_onboarding_steps(ha, base_url=ha_base_url, access_token=access_token)

                status.stage = "syncing"
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, cleanup.delete_stock_components)
                # Defense-in-depth on top of ha_config.py's loopback binding
                # (the load-bearing mechanism) — see cleanup.py and
                # frontend_stub.py for why this is a separate, independently
                # fail-safe step.
                await loop.run_in_executor(None, cleanup.replace_frontend_with_stub)

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
