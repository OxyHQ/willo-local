"""The orchestrator's own status state — polled by the Vite claim UI at
GET /status roughly once a second (see server.py and willo-claim-ui/), and
also by the Willo app itself for its "Connect Home Assistant" auto-detect
screen, which tries `http://willo.local/status` before ever asking someone
to scan/type a code.

One process-wide, in-memory instance (see main.py) — there is exactly one
device being onboarded at a time, so a single mutable object, updated in
place as the boot sequence progresses through real stages, is simpler and
more honest than an event bus or a state machine library would be here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

Stage = Literal["onboarding", "syncing", "awaiting-pairing", "paired"]


@dataclass
class OrchestratorStatus:
    stage: Stage = "onboarding"
    claim_code: str | None = None
    qr_data_url: str | None = None
    # "Green", "Yellow", etc. — set once, early in the boot sequence, from
    # HAOS Supervisor's own board info (see device_model.py). Null under
    # Supervisor-less installs (every sandbox test in this repo) or if
    # Supervisor doesn't report one — the Willo app already handles its
    # absence, per the app team, rather than this orchestrator guessing a
    # board name it doesn't actually know.
    device_model: str | None = None
    # Surfaced so the claim UI can show *something* useful instead of a
    # frozen status line if a step fails outright, rather than the
    # orchestrator crashing silently with nothing visible on willo.local.
    error: str | None = None

    def as_json(self) -> dict[str, str | None]:
        data = asdict(self)
        return {
            "stage": data["stage"],
            "claimCode": data["claim_code"],
            "qrDataUrl": data["qr_data_url"],
            "deviceModel": data["device_model"],
            "error": data["error"],
        }


def new_status() -> OrchestratorStatus:
    return OrchestratorStatus()
