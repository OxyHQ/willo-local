"""Constants for the Willo Local orchestrator.

This is a SEPARATE Python package from custom_components/willo — it runs
as its own process/HAOS add-on, never inside HA Core's own Python process
(see this repo's top-level README and OxyHQ/Willo issue #9). Because of
that, it deliberately does NOT import custom_components.willo (which pulls
in `homeassistant` and `python-socketio` — heavy, HA-Core-specific
dependencies this process has no other reason to need).

DEFAULT_CLAIM_URL and DEFAULT_CLAIM_STATUS_URL are kept identical, on
purpose, to custom_components/willo/const.py's own copies — both describe
the same two backend endpoints, from two different processes' points of
view. If the backend's claim routes ever move, update both files.
"""

from __future__ import annotations

DEFAULT_CLAIM_URL = "https://api.willo.sh/tunnel/claim"
DEFAULT_CLAIM_STATUS_URL = "https://api.willo.sh/tunnel/claim/status"

# Where this orchestrator expects to find HA Core's REST API on the same
# device. Overridable via the WILLO_HA_BASE_URL env var — see main.py —
# since a real HAOS add-on reaches Core over its own documented add-on
# network, not necessarily literally "localhost" (open item #4 from the
# Willo issue's own "still needs real HAOS hardware to verify" list).
DEFAULT_HA_BASE_URL = "http://localhost:8123"
