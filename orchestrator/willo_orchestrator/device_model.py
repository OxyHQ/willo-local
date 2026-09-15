"""Detects the real Home Assistant board model (e.g. "Green", "Yellow")
from HAOS Supervisor's own API, for the Willo app's device-auto-detect
screen (`GET http://willo.local/status`'s `deviceModel` field — see
status.py) — the app explicitly does not want a hardcoded "Green" for
every appliance.

VERIFIED FOR REAL, PARTIALLY: `aiohasupervisor` (the real, typed Python
client library for Supervisor's REST API — already an installed
dependency of the stock `hassio` integration, confirmed by inspecting the
actual installed package rather than guessing a field name) exposes
`SupervisorClient(api_host, token).os.info()` → `OSInfo.board: str | None`,
via `GET os/info`. That `board` field (confirmed by reading
aiohasupervisor's real models/os.py in this sandbox) is exactly what this
needs — HAOS's own board slugs are lowercase ("green", "yellow", "rpi4",
"generic-x86-64", ...), title-cased below into what the Willo app wants
to display.

UNVERIFIED, FLAGGED PLAINLY: this was never called against a REAL
Supervisor — there is no Supervisor in a plain `pip install homeassistant`
sandbox, and SUPERVISOR_TOKEN (the env var HAOS injects into every add-on
container, the standard auth mechanism for this API) is never set here.
What IS verified: this module correctly detects that absence and returns
None without raising or hanging, exactly as it needs to for this
sandbox — and the `os.info()` call shape and `board` field name are real,
read directly from the installed client library's source, not
remembered/guessed. Whether `http://supervisor` (the standard internal
hostname every add-on container can reach) and the actual response shape
hold up against a real Supervisor is on the same "needs real HAOS
hardware" list as the other Supervisor-specific unknowns in this repo's
README — added there, not silently assumed to work.
"""

from __future__ import annotations

import logging
import os

_LOGGER = logging.getLogger(__name__)

SUPERVISOR_API_HOST = "http://supervisor"


async def detect_device_model() -> str | None:
    """Returns a display-ready board name ("Green", "Yellow", ...) or
    None if this isn't running under Supervisor at all (a plain venv/
    Docker Core install, every sandbox test in this repo) or the call
    fails for any reason. Never raises.
    """
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        _LOGGER.info("SUPERVISOR_TOKEN not set — not running under Supervisor, deviceModel will be null")
        return None

    try:
        from aiohasupervisor import SupervisorClient  # noqa: PLC0415 - optional dependency, only needed under Supervisor
    except ImportError:
        _LOGGER.warning("aiohasupervisor is not installed — cannot query Supervisor for the board model")
        return None

    try:
        async with SupervisorClient(SUPERVISOR_API_HOST, token) as client:
            os_info = await client.os.info()
    except Exception:  # noqa: BLE001 - deviceModel is a nice-to-have for the app's UI copy, never worth failing boot over
        _LOGGER.warning("Failed to query Supervisor for the board model", exc_info=True)
        return None

    if not os_info.board:
        return None
    return os_info.board.replace("-", " ").replace("_", " ").title()
