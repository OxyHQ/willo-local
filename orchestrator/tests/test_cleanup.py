"""Tests for cleanup.py — the orchestrator's own standalone copy of the
frontend/analytics/cloud deletion logic (see cleanup.py's module doc
comment for why there are two copies of this logic in this repo).

Same isolation approach as custom_components/willo's own tests for this
logic: a fake tmp_path package tree, never the real installed
homeassistant package running this test suite.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import patch

from willo_orchestrator.cleanup import delete_stock_components


def _make_fake_homeassistant_package(tmp_path, components: list[str]):
    components_dir = tmp_path / "homeassistant" / "components"
    for name in components:
        component_dir = components_dir / name
        component_dir.mkdir(parents=True)
        (component_dir / "__init__.py").write_text("# fake component\n")
    return tmp_path / "homeassistant"


def test_deletes_frontend_analytics_and_cloud_when_present(tmp_path) -> None:
    install_root = _make_fake_homeassistant_package(tmp_path, ["frontend", "analytics", "cloud", "light"])
    fake_spec = SimpleNamespace(submodule_search_locations=[str(install_root)])

    with patch("willo_orchestrator.cleanup.importlib.util.find_spec", return_value=fake_spec):
        delete_stock_components()

    assert not (install_root / "components" / "frontend").exists()
    assert not (install_root / "components" / "analytics").exists()
    assert not (install_root / "components" / "cloud").exists()
    assert (install_root / "components" / "light").exists()


def test_missing_directories_are_a_silent_noop(tmp_path) -> None:
    install_root = _make_fake_homeassistant_package(tmp_path, ["light"])
    fake_spec = SimpleNamespace(submodule_search_locations=[str(install_root)])

    with patch("willo_orchestrator.cleanup.importlib.util.find_spec", return_value=fake_spec):
        delete_stock_components()  # must not raise

    assert (install_root / "components" / "light").exists()


def test_unresolvable_package_logs_warning_and_does_not_raise(caplog) -> None:
    with patch("willo_orchestrator.cleanup.importlib.util.find_spec", return_value=None):
        with caplog.at_level(logging.WARNING):
            delete_stock_components()

    assert "Could not resolve the installed homeassistant package" in caplog.text
