"""Renames this device's hostname to "willo" via HAOS Supervisor's real
API, so real HAOS mDNS/avahi advertises it as `willo.local` (the `.local`
suffix is added by the host's own mDNS responder from a bare hostname —
Supervisor's API takes the bare name, not the suffixed one, per
`HostOptions` below).

VERIFIED FOR REAL, PARTIALLY — same standard as device_model.py: found by
reading aiohasupervisor's actual installed source, not remembered/guessed.
`HostClient` (`aiohasupervisor/host.py`) exposes:
    GET  host/info     -> HostInfo (includes the CURRENT `hostname`)
    POST host/options  <- HostOptions(hostname=...)  (`host.py`'s
                           `set_options`)
Both real, typed, and confirmed by inspecting the installed package
directly (the same `aiohasupervisor` dependency `device_model.py` already
uses for `os/info`).

UNVERIFIED, FLAGGED PLAINLY: never called against a REAL Supervisor. This
task attempted a real HAOS QEMU VM boot (see this repo's README, "Real
HAOS VM attempt" section, for the full writeup) — real KVM virtualization
works in that sandbox, the official HAOS image boots correctly under UEFI,
and Home Assistant Core briefly became reachable under real Supervisor
management once — but a reproducible DNS-over-TLS-related stall under
QEMU's default usermode networking (diagnosed via QEMU's own monitor, not
guessed) prevented completing onboarding and testing this specific call
against that real Supervisor before time ran out on that attempt. This
function's behavior when Supervisor is absent (the SUPERVISOR_TOKEN-unset
case, true for every venv sandbox test in this repo) IS verified: it
degrades to a no-op, never raises. What is NOT verified is that
`host/options` actually renames the hostname exactly as
`HostOptions`/`HostClient.set_options` imply against a live Supervisor —
that needs either a working bridged-network HAOS VM boot or real hardware.
"""

from __future__ import annotations

import logging
import os

_LOGGER = logging.getLogger(__name__)

SUPERVISOR_API_HOST = "http://supervisor"
WILLO_HOSTNAME = "willo"


async def set_device_hostname() -> bool:
    """Renames the host to WILLO_HOSTNAME via Supervisor. Returns True if
    the call was made (does not confirm mDNS actually advertises the new
    name — that's an OS-level effect this process has no way to observe).
    False if this isn't running under Supervisor at all, or the call
    failed for any reason. Never raises — a failed hostname rename is not
    worth blocking pairing over.
    """
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        _LOGGER.info("SUPERVISOR_TOKEN not set — not running under Supervisor, skipping hostname rename")
        return False

    try:
        from aiohasupervisor import SupervisorClient  # noqa: PLC0415 - optional dependency, only needed under Supervisor
        from aiohasupervisor.models import HostOptions  # noqa: PLC0415
    except ImportError:
        _LOGGER.warning("aiohasupervisor is not installed — cannot rename the host via Supervisor")
        return False

    try:
        async with SupervisorClient(SUPERVISOR_API_HOST, token) as client:
            current = await client.host.info()
            if current.hostname == WILLO_HOSTNAME:
                _LOGGER.info("Host is already named '%s' — nothing to do", WILLO_HOSTNAME)
                return True
            await client.host.set_options(HostOptions(hostname=WILLO_HOSTNAME))
    except Exception:  # noqa: BLE001 - a failed rename must never block pairing; willo.local not resolving is a real but non-fatal degradation
        _LOGGER.warning("Failed to rename the host to '%s' via Supervisor", WILLO_HOSTNAME, exc_info=True)
        return False

    _LOGGER.info("Renamed host to '%s' via Supervisor (host/options)", WILLO_HOSTNAME)
    return True
