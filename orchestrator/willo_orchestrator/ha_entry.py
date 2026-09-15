"""Headless Willo config-entry creation — mechanism (b) from OxyHQ/Willo
issue #9's open item #2, CHOSEN AND VERIFIED over mechanism (a).

Both candidates were tested empirically against a real local HA Core
2026.2.3 instance (see this repo's README, "Headless config-entry
creation" section, for the full writeup):

(a) HA's config-entries REST flow API (`POST /api/config/config_entries/
    flow`). REJECTED: `homeassistant/components/config/config_entries.py`'s
    `ConfigManagerFlowIndexView.get_context()` hardcodes
    `context["source"] = config_entries.SOURCE_USER` for every externally
    initiated flow — confirmed by reading that source AND by driving the
    real endpoint against a live `willo` custom integration, which always
    landed on `step_id: "user"` no matter what. There is no request body
    field that reaches a different source through that endpoint, so an
    external process cannot use it to reach a non-`user` step.

(b) Writing the entry directly into `.storage/core.config_entries` and
    restarting Core. CHOSEN. Verified end-to-end: a hand-written entry
    with this exact shape was picked up by Core on restart, recognized as
    a real `willo` entry, and had `async_setup_entry` genuinely invoked on
    it (proven by the entry landing in `state: "setup_retry"` with
    `reason: "Could not reach Willo's tunnel at https://api.willo.sh"` —
    that exact string only comes from custom_components/willo/__init__.py's
    own ConfigEntryNotReady path, so this is not a guess).

The exact JSON schema below was read directly from a real
`.storage/core.config_entries` file after creating a `willo` entry the
normal way (via the config flow) on HA Core 2026.2.3, minor_version 5 of
that storage key. `version`/`minor_version`/`key` at the top of the file
are HA's own storage-format versioning — this module reads and preserves
whatever is already there rather than hardcoding guessed values, since
migrating that format is HA's own concern, not this orchestrator's.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from ulid_transform import ulid_now

_LOGGER = logging.getLogger(__name__)

CONFIG_ENTRIES_STORAGE_RELATIVE_PATH = Path(".storage") / "core.config_entries"

# The source recorded on an entry created this way. Not one of HA's own
# config_entries.SOURCE_* constants (this bypasses the flow manager
# entirely, so none of those apply) — "claim" is purely descriptive
# metadata, confirmed safe by the same live test above: HA does not
# validate `source` against a fixed enum when loading entries from
# storage, it just stores and displays whatever string is there.
ENTRY_SOURCE = "claim"
ENTRY_DOMAIN = "willo"
ENTRY_TITLE = "Willo"


class ConfigEntriesStorageError(Exception):
    """Raised when .storage/core.config_entries can't be safely read or written."""


def _now_iso() -> str:
    # Matches the exact format HA itself writes, e.g.
    # "2026-09-15T09:05:39.963273+00:00" — confirmed by inspecting a real
    # entry HA created itself via the config flow.
    return datetime.now(timezone.utc).isoformat()


def write_willo_entry(config_dir: Path, *, home_id: str, secret: str) -> str:
    """Append a new `willo` config entry directly into
    <config_dir>/.storage/core.config_entries. Returns the new entry_id.

    Read-modify-write, not a blind overwrite: this must never touch any
    OTHER integration's entries, which is why the whole file is loaded,
    one entry is appended, and the whole structure (including whatever
    `version`/`minor_version`/`key` HA itself already wrote) is written
    back unchanged apart from that append.
    """
    storage_path = config_dir / CONFIG_ENTRIES_STORAGE_RELATIVE_PATH
    if not storage_path.is_file():
        raise ConfigEntriesStorageError(
            f"{storage_path} does not exist yet — onboarding must finish (which creates this "
            "file) before a config entry can be written into it"
        )

    with storage_path.open() as file:
        storage = json.load(file)

    now = _now_iso()
    entry_id = ulid_now()
    new_entry = {
        "created_at": now,
        "data": {"home_id": home_id, "secret": secret},
        "disabled_by": None,
        "discovery_keys": {},
        "domain": ENTRY_DOMAIN,
        "entry_id": entry_id,
        "minor_version": 1,
        "modified_at": now,
        "options": {},
        "pref_disable_new_entities": False,
        "pref_disable_polling": False,
        "source": ENTRY_SOURCE,
        "subentries": [],
        "title": ENTRY_TITLE,
        "unique_id": home_id,
        "version": 1,
    }
    storage["data"]["entries"].append(new_entry)

    # Write to a temp file then rename, so a crash mid-write can never
    # leave core.config_entries half-written — HA's own storage helper
    # does the same thing, and this file holds every OTHER integration's
    # config too, not just Willo's.
    tmp_path = storage_path.with_suffix(".tmp")
    with tmp_path.open("w") as file:
        json.dump(storage, file, indent=2)
    tmp_path.replace(storage_path)

    _LOGGER.info("Wrote willo config entry %s for home_id=%s directly into %s", entry_id, home_id, storage_path)
    return entry_id


def has_willo_entry(config_dir: Path) -> bool:
    """True if a `willo` domain entry already exists — used to avoid
    writing a second one (Willo is one-home-per-instance; see
    custom_components/willo/config_flow.py's _async_finish_entry for the
    same rule enforced on the config-flow side of entry creation).
    """
    storage_path = config_dir / CONFIG_ENTRIES_STORAGE_RELATIVE_PATH
    if not storage_path.is_file():
        return False
    with storage_path.open() as file:
        storage = json.load(file)
    return any(entry["domain"] == ENTRY_DOMAIN for entry in storage["data"]["entries"])
