"""Manages the `configuration.yaml` this device's Home Assistant Core
boots with — an explicit integration allow-list, never `default_config:`,
per the Willo Local design (OxyHQ/Willo issue #9), PLUS restricting
Core's own HTTP server to the loopback interface only.

See this repo's README, "Cleanup deletion" section, for the full history
of why loopback binding is the mechanism actually used: physically
deleting `frontend` crashes the next `hass` launch outright, and merely
excluding `frontend` from this same explicit list does NOT stop it from
loading or serving — `homeassistant/bootstrap.py`'s `_get_domains()`
unconditionally force-includes `frontend` (and `analytics`) via
`DEFAULT_INTEGRATIONS` regardless of what this file says. Binding Core's
`http:` to `127.0.0.1` only was verified to be the one thing that actually
makes Core's HTTP surface (whatever is or isn't loaded on it) unreachable
from outside this device, while this orchestrator's own server (see
server.py) binds to the real network interface separately and is
unaffected by this.

This orchestrator treats `configuration.yaml` as fully owned and managed
by it — nobody hand-edits Home Assistant's configuration.yaml on a Willo
Local appliance (they never see HA's own UI at all) — so this always
writes the same fixed, deterministic content rather than trying to parse
and merge arbitrary existing YAML.
"""

from __future__ import annotations

from pathlib import Path

CONFIGURATION_YAML_CONTENT = """\
homeassistant:
  name: Willo Green
  latitude: 0
  longitude: 0
  elevation: 0
  unit_system: metric
  time_zone: UTC

# Explicit integration allow-list — never default_config: — so nothing
# beyond what Willo Local actually needs ever gets pulled in. api: and
# config: back the REST endpoints this orchestrator itself calls
# (onboarding, config entries, the homeassistant.restart service).
# http.server_host restricts Core's own HTTP server to this device's
# loopback interface ONLY: Core is never reachable from the network, even
# though frontend/analytics/cloud remain force-loaded by HA's own
# bootstrap regardless of this list (see this repo's README) — this
# orchestrator, bound separately to the real network interface (see
# server.py), is the only thing a person's phone or laptop can ever reach.
api:
config:
http:
  server_port: 8123
  server_host: 127.0.0.1
"""


def ensure_explicit_configuration(config_dir: Path) -> bool:
    """Writes CONFIGURATION_YAML_CONTENT to <config_dir>/configuration.yaml
    if it isn't already exactly that.

    Returns True if the file was created or changed — the caller MUST
    restart Core for a change to take effect (Core only reads
    configuration.yaml at startup).
    """
    path = config_dir / "configuration.yaml"
    current = path.read_text() if path.is_file() else None
    if current == CONFIGURATION_YAML_CONTENT:
        return False
    path.write_text(CONFIGURATION_YAML_CONTENT)
    return True
