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
by it on a genuinely fresh device — nobody hand-edits Home Assistant's
configuration.yaml on a Willo Local appliance (they never see HA's own UI
at all) — so on a fresh device this always writes the same fixed,
deterministic content rather than trying to parse and merge arbitrary
existing YAML.

**That assumption is UNSAFE on a device that already has a real,
hand-authored configuration.yaml** — confirmed the hard way against a
real Home Assistant Green with an 800+ line configuration.yaml, ~15
packages, shell_commands controlling a home router's VPN, and months of
real automations: unconditionally overwriting that file (and restarting
Core to apply loopback binding, which requires the overwrite) would have
been catastrophic. See `has_meaningful_existing_configuration()` below —
`main.py` calls this BEFORE ever calling `ensure_explicit_configuration()`
or restarting Core for it, and skips both entirely (falling back to only
the hostname rename + serving the claim/status UI, neither of which
touches configuration.yaml) whenever it returns True.
`ensure_explicit_configuration()` itself is unchanged and still always
overwrites when called — the safety fix lives entirely in whether it gets
called at all, not in what it does.
"""

from __future__ import annotations

from pathlib import Path

import yaml

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

    Deliberately unconditional — this does not itself decide whether it is
    SAFE to call. That decision is `has_meaningful_existing_configuration()`
    below, which `main.py` checks first.
    """
    path = config_dir / "configuration.yaml"
    current = path.read_text() if path.is_file() else None
    if current == CONFIGURATION_YAML_CONTENT:
        return False
    path.write_text(CONFIGURATION_YAML_CONTENT)
    return True


# The exact content a genuinely fresh Home Assistant Core install writes to
# its own configuration.yaml on first launch, before this orchestrator (or
# anyone else) ever touches it — captured empirically by running a real,
# never-before-launched `hass` against an empty config directory and
# reading back exactly what it wrote (HA Core 2026.2.3; see this repo's
# README for the verification transcript). Used below as one of two exact-
# match fast paths for "this is definitely a fresh device" — the other
# being Willo's own CONFIGURATION_YAML_CONTENT, once already applied.
_FRESH_HA_DEFAULT_CONFIGURATION_YAML = """\

# Loads default set of integrations. Do not remove.
default_config:

# Load frontend themes from the themes folder
frontend:
  themes: !include_dir_merge_named themes

automation: !include automations.yaml
script: !include scripts.yaml
scene: !include scenes.yaml
"""


class _PermissiveConfigLoader(yaml.SafeLoader):
    """A YAML loader that tolerates Home Assistant's own custom tags
    (`!include`, `!secret`, `!include_dir_named`, `!include_dir_merge_named`,
    `!include_dir_list`, `!include_dir_merge_list`, `!env_var`, and any
    others) instead of raising on them, by resolving every such tag to
    `None`. `has_meaningful_existing_configuration()` below only ever needs
    to know which top-level (and top-level-nested) YAML *keys* a real
    configuration.yaml defines — never what an `!include` actually points
    to — so there is no need to reimplement HA's own tag resolution here,
    and a real device's configuration.yaml is guaranteed to use several of
    these tags (that is exactly what makes it "real").
    """


def _construct_unknown_tag_as_none(loader: yaml.SafeLoader, tag_suffix: str, node: yaml.Node) -> None:
    return None


_PermissiveConfigLoader.add_multi_constructor("!", _construct_unknown_tag_as_none)


def _parse_configuration_yaml_keys(content: str) -> dict[str, object] | None:
    """Parses `content` far enough to inspect its keys, tolerating HA's own
    custom tags. Returns None if it can't even be parsed as a YAML mapping
    at all — treated as "real" (unknown) by the caller, never as "fresh",
    since a fresh device's configuration.yaml is always valid, simple YAML.
    """
    try:
        parsed = yaml.load(content, Loader=_PermissiveConfigLoader)
    except yaml.YAMLError:
        return None
    return parsed if isinstance(parsed, dict) else None


# Top-level keys that either a genuinely fresh HA install's own default
# configuration.yaml OR Willo's own CONFIGURATION_YAML_CONTENT ever uses.
# This is a deliberately small, closed allow-list, not an attempt to
# enumerate every "harmless" HA integration — seeing ANY top-level key
# outside this set (`packages:`, `climate:`, `shell_command:`, `sensor:`,
# a real `mqtt:` block, etc.) means a real person has added real
# configuration, and this module does not try to guess which additions
# are "probably fine".
_KNOWN_SAFE_TOP_LEVEL_KEYS = frozenset(
    {"default_config", "frontend", "automation", "script", "scene", "homeassistant", "api", "config", "http"}
)

# The only `homeassistant:` sub-keys either template ever writes. This
# matters on its own, separately from the top-level check above, because
# HA's `packages:` mechanism — how a real install like the one this was
# verified against pulls in ~15 packages' worth of real automations,
# climate/ventilation control, etc. — lives NESTED under `homeassistant:`,
# not as a top-level key. A `homeassistant:` block with anything beyond
# this set is real configuration even if every top-level key otherwise
# looks "safe".
_KNOWN_SAFE_HOMEASSISTANT_BLOCK_KEYS = frozenset(
    {"name", "latitude", "longitude", "elevation", "unit_system", "time_zone"}
)

# A generous ceiling, well above both known-fresh templates (the real HA
# default above is 11 lines; Willo's own CONFIGURATION_YAML_CONTENT is
# about 25 including comments) — a purely defensive catch-all for a file
# that somehow uses only "safe" keys yet has grown far beyond what either
# template ever would, rather than the primary signal.
_FRESH_LINE_COUNT_CEILING = 40


def has_meaningful_existing_configuration(config_dir: Path) -> bool:
    """True if <config_dir>/configuration.yaml already holds real,
    hand-authored configuration that this orchestrator must never
    overwrite, or restart Core to apply loopback binding for.

    False (safe to manage as a fresh device) for exactly three cases:
    no file yet, HA's own untouched default template, or Willo's own
    already-applied CONFIGURATION_YAML_CONTENT. Everything else is judged
    by a closed allow-list of top-level (and `homeassistant:`-nested) YAML
    keys plus a generous line-count ceiling — see the module-level
    constants above for what "safe" means and why. Deliberately
    conservative: anything this function cannot positively confirm is
    fresh (including content it can't even parse) is treated as real, per
    this repo's README and the real Home Assistant Green this was
    verified against.
    """
    path = config_dir / "configuration.yaml"
    if not path.is_file():
        return False

    content = path.read_text()
    if content in (CONFIGURATION_YAML_CONTENT, _FRESH_HA_DEFAULT_CONFIGURATION_YAML):
        return False

    parsed = _parse_configuration_yaml_keys(content)
    if parsed is None:
        return True

    top_level_keys = set(parsed.keys())
    if not top_level_keys.issubset(_KNOWN_SAFE_TOP_LEVEL_KEYS):
        return True

    homeassistant_block = parsed.get("homeassistant")
    if isinstance(homeassistant_block, dict) and not set(homeassistant_block.keys()).issubset(
        _KNOWN_SAFE_HOMEASSISTANT_BLOCK_KEYS
    ):
        return True

    return len(content.splitlines()) > _FRESH_LINE_COUNT_CEILING
