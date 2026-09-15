"""Tests for ha_entry.py's direct .storage/core.config_entries write — the
mechanism (b) chosen and empirically verified in OxyHQ/Willo issue #9 (see
ha_entry.py's module doc comment, and this repo's README).

These tests exercise the read-modify-write logic against a throwaway
fixture file shaped exactly like the real file HA writes (captured from a
real local HA Core 2026.2.3 instance) — they do NOT start a real hass
process (that's covered by this repo's manual/README-documented end-to-end
run, not by the automated suite).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from willo_orchestrator.ha_entry import ConfigEntriesStorageError, has_willo_entry, write_willo_entry

EXISTING_STORAGE = {
    "version": 1,
    "minor_version": 5,
    "key": "core.config_entries",
    "data": {
        "entries": [
            {
                "created_at": "2026-09-15T09:00:43.980514+00:00",
                "data": {},
                "disabled_by": None,
                "discovery_keys": {},
                "domain": "backup",
                "entry_id": "01M2J4R4JC9P6EFE1M9YD0F9PM",
                "minor_version": 1,
                "modified_at": "2026-09-15T09:00:43.980515+00:00",
                "options": {},
                "pref_disable_new_entities": False,
                "pref_disable_polling": False,
                "source": "system",
                "subentries": [],
                "title": "Backup",
                "unique_id": None,
                "version": 1,
            }
        ]
    },
}


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    storage_dir = tmp_path / ".storage"
    storage_dir.mkdir()
    (storage_dir / "core.config_entries").write_text(json.dumps(EXISTING_STORAGE))
    return tmp_path


def test_write_willo_entry_appends_without_touching_other_entries(config_dir: Path) -> None:
    entry_id = write_willo_entry(config_dir, home_id="home_abc", secret="s3cr3t")

    with (config_dir / ".storage" / "core.config_entries").open() as file:
        storage = json.load(file)

    assert storage["version"] == 1
    assert storage["minor_version"] == 5
    assert storage["key"] == "core.config_entries"
    assert len(storage["data"]["entries"]) == 2

    backup_entry = next(e for e in storage["data"]["entries"] if e["domain"] == "backup")
    assert backup_entry == EXISTING_STORAGE["data"]["entries"][0]  # untouched

    willo_entry = next(e for e in storage["data"]["entries"] if e["domain"] == "willo")
    assert willo_entry["entry_id"] == entry_id
    assert willo_entry["data"] == {"home_id": "home_abc", "secret": "s3cr3t"}
    assert willo_entry["unique_id"] == "home_abc"
    assert willo_entry["title"] == "Willo"
    assert willo_entry["source"] == "claim"
    assert willo_entry["version"] == 1
    assert willo_entry["minor_version"] == 1
    assert willo_entry["subentries"] == []
    assert willo_entry["options"] == {}
    assert willo_entry["disabled_by"] is None


def test_write_willo_entry_generates_a_real_ulid(config_dir: Path) -> None:
    entry_id = write_willo_entry(config_dir, home_id="home_abc", secret="s3cr3t")
    # ULID: 26 chars, Crockford base32 (no I, L, O, U)
    assert len(entry_id) == 26
    assert entry_id == entry_id.upper()
    assert not any(character in entry_id for character in "ILOU")


def test_write_willo_entry_without_onboarding_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigEntriesStorageError):
        write_willo_entry(tmp_path, home_id="home_abc", secret="s3cr3t")


def test_has_willo_entry_false_before_write(config_dir: Path) -> None:
    assert has_willo_entry(config_dir) is False


def test_has_willo_entry_true_after_write(config_dir: Path) -> None:
    write_willo_entry(config_dir, home_id="home_abc", secret="s3cr3t")
    assert has_willo_entry(config_dir) is True


def test_has_willo_entry_false_when_storage_file_missing(tmp_path: Path) -> None:
    assert has_willo_entry(tmp_path) is False
