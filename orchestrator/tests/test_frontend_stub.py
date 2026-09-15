"""Tests for cleanup.py's replace_frontend_with_stub — the defense-in-depth
frontend stub swap layered on top of loopback binding (see cleanup.py and
frontend_stub.py for the full rationale and fragility caveat).

Same isolation approach as the rest of this repo's cleanup tests: a fake
tmp_path package tree, never the real installed homeassistant package
running this test suite.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import patch

from willo_orchestrator.cleanup import replace_frontend_with_stub
from willo_orchestrator.frontend_stub import STUB_INIT_PY, STUB_MANIFEST_JSON


def _make_fake_homeassistant_package(tmp_path, components: list[str]):
    components_dir = tmp_path / "homeassistant" / "components"
    for name in components:
        component_dir = components_dir / name
        component_dir.mkdir(parents=True)
        (component_dir / "__init__.py").write_text("# fake component\n")
        (component_dir / "manifest.json").write_text("{}\n")
    return tmp_path / "homeassistant"


def test_replaces_frontend_files_with_the_stub(tmp_path) -> None:
    install_root = _make_fake_homeassistant_package(tmp_path, ["frontend"])
    fake_spec = SimpleNamespace(submodule_search_locations=[str(install_root)])

    with patch("willo_orchestrator.cleanup.importlib.util.find_spec", return_value=fake_spec):
        replace_frontend_with_stub()

    frontend_dir = install_root / "components" / "frontend"
    assert (frontend_dir / "__init__.py").read_text() == STUB_INIT_PY
    assert (frontend_dir / "manifest.json").read_text() == STUB_MANIFEST_JSON


def test_removes_any_other_real_frontend_files_first(tmp_path) -> None:
    """A real frontend/ has more than two files (icons.json, storage.py,
    translations/, ...) — those must not survive the swap, or stale real
    code could still be importable alongside the stub.
    """
    install_root = _make_fake_homeassistant_package(tmp_path, ["frontend"])
    frontend_dir = install_root / "components" / "frontend"
    (frontend_dir / "storage.py").write_text("# real frontend internals\n")
    (frontend_dir / "icons.json").write_text("{}\n")
    fake_spec = SimpleNamespace(submodule_search_locations=[str(install_root)])

    with patch("willo_orchestrator.cleanup.importlib.util.find_spec", return_value=fake_spec):
        replace_frontend_with_stub()

    assert not (frontend_dir / "storage.py").exists()
    assert not (frontend_dir / "icons.json").exists()
    assert (frontend_dir / "__init__.py").read_text() == STUB_INIT_PY


def test_works_even_if_frontend_directory_is_already_missing(tmp_path) -> None:
    install_root = _make_fake_homeassistant_package(tmp_path, ["light"])
    fake_spec = SimpleNamespace(submodule_search_locations=[str(install_root)])

    with patch("willo_orchestrator.cleanup.importlib.util.find_spec", return_value=fake_spec):
        replace_frontend_with_stub()  # must not raise

    frontend_dir = install_root / "components" / "frontend"
    assert (frontend_dir / "__init__.py").read_text() == STUB_INIT_PY


def test_unresolvable_package_logs_warning_and_does_not_raise(caplog) -> None:
    with patch("willo_orchestrator.cleanup.importlib.util.find_spec", return_value=None):
        with caplog.at_level(logging.WARNING):
            replace_frontend_with_stub()

    assert "Could not resolve the installed homeassistant package" in caplog.text


def test_stub_source_only_declares_the_symbols_confirmed_needed() -> None:
    for expected_symbol in (
        "DATA_PANELS",
        "MANIFEST_JSON",
        "async_setup",
        "async_register_built_in_panel",
        "async_remove_panel",
        "async_system_store",
    ):
        assert expected_symbol in STUB_INIT_PY


def test_stub_manifest_keeps_the_same_domain_and_dependencies_as_the_real_component() -> None:
    import json

    manifest = json.loads(STUB_MANIFEST_JSON)
    assert manifest["domain"] == "frontend"
    # Same dependency list as the real frontend component confirmed live
    # against HA 2026.2.3 — deviating here risks changing what else gets
    # pulled in when frontend is force-loaded, an unrelated variable this
    # stub should not also be changing.
    assert set(manifest["dependencies"]) == {
        "api", "auth", "config", "device_automation", "diagnostics",
        "file_upload", "http", "lovelace", "onboarding", "repairs",
        "search", "system_log", "websocket_api",
    }
    assert "requirements" not in manifest  # the real home-assistant-frontend asset package is never needed
