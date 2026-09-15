"""Tests for custom_components/willo/__init__.py's
_replace_frontend_with_stub — the defense-in-depth frontend stub swap
layered on top of orchestrator/willo_orchestrator/ha_config.py's loopback
binding (see __init__.py and frontend_stub.py for the full rationale and
fragility caveat).

Same isolation approach as test_init.py: a fake tmp_path package tree,
never the real installed homeassistant package running this test suite.
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from unittest.mock import patch

from custom_components.willo import _replace_frontend_with_stub
from custom_components.willo.frontend_stub import STUB_INIT_PY, STUB_MANIFEST_JSON


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

    with patch("custom_components.willo.importlib.util.find_spec", return_value=fake_spec):
        _replace_frontend_with_stub()

    frontend_dir = install_root / "components" / "frontend"
    assert (frontend_dir / "__init__.py").read_text() == STUB_INIT_PY
    assert (frontend_dir / "manifest.json").read_text() == STUB_MANIFEST_JSON


def test_removes_any_other_real_frontend_files_first(tmp_path) -> None:
    install_root = _make_fake_homeassistant_package(tmp_path, ["frontend"])
    frontend_dir = install_root / "components" / "frontend"
    (frontend_dir / "storage.py").write_text("# real frontend internals\n")
    fake_spec = SimpleNamespace(submodule_search_locations=[str(install_root)])

    with patch("custom_components.willo.importlib.util.find_spec", return_value=fake_spec):
        _replace_frontend_with_stub()

    assert not (frontend_dir / "storage.py").exists()


def test_works_even_if_frontend_directory_is_already_missing(tmp_path) -> None:
    install_root = _make_fake_homeassistant_package(tmp_path, ["light"])
    fake_spec = SimpleNamespace(submodule_search_locations=[str(install_root)])

    with patch("custom_components.willo.importlib.util.find_spec", return_value=fake_spec):
        _replace_frontend_with_stub()  # must not raise

    frontend_dir = install_root / "components" / "frontend"
    assert (frontend_dir / "__init__.py").read_text() == STUB_INIT_PY


def test_unresolvable_package_logs_warning_and_does_not_raise(caplog) -> None:
    with patch("custom_components.willo.importlib.util.find_spec", return_value=None):
        with caplog.at_level(logging.WARNING):
            _replace_frontend_with_stub()

    assert "Could not resolve the installed homeassistant package" in caplog.text


def test_stub_manifest_is_valid_json_with_the_frontend_domain() -> None:
    manifest = json.loads(STUB_MANIFEST_JSON)
    assert manifest["domain"] == "frontend"
    assert "requirements" not in manifest
