"""Tests for custom_components/willo/__init__.py's _delete_stock_components —
the self-healing frontend/analytics/cloud deletion from OxyHQ/Willo issue #9.

These tests point `importlib.util.find_spec` at a FAKE, disposable package
tree (pytest's tmp_path) rather than the real installed `homeassistant`
package the test suite itself runs on. That distinction matters: an
earlier version of this test suite let `_delete_stock_components` run
against the real installed package (via a full config-flow-driven
async_setup_entry) and it deleted frontend/analytics/cloud from the very
homeassistant install running pytest, breaking every later test in the
same invocation — see test_config_flow.py's
test_claim_step_same_home_twice_aborts_already_configured for where that
is now patched out. The tests below are the deliberately safe, isolated
equivalent, and are what actually verifies the deletion logic itself.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from custom_components.willo import _delete_stock_components


def _make_fake_homeassistant_package(tmp_path, components: list[str]):
    """Build a throwaway directory tree that looks like an installed
    homeassistant package's components/ folder, containing only the given
    component directories (each with a placeholder file, like a real
    component would have __init__.py etc.).
    """
    components_dir = tmp_path / "homeassistant" / "components"
    for name in components:
        component_dir = components_dir / name
        component_dir.mkdir(parents=True)
        (component_dir / "__init__.py").write_text("# fake component\n")
    return tmp_path / "homeassistant"


def test_deletes_frontend_analytics_and_cloud_when_present(tmp_path) -> None:
    install_root = _make_fake_homeassistant_package(
        tmp_path, ["frontend", "analytics", "cloud", "light", "sensor"]
    )
    fake_spec = SimpleNamespace(submodule_search_locations=[str(install_root)])

    with patch("custom_components.willo.importlib.util.find_spec", return_value=fake_spec):
        _delete_stock_components()

    assert not (install_root / "components" / "frontend").exists()
    assert not (install_root / "components" / "analytics").exists()
    assert not (install_root / "components" / "cloud").exists()
    # untouched: this function must only ever remove exactly these three
    assert (install_root / "components" / "light").exists()
    assert (install_root / "components" / "sensor").exists()


def test_missing_directories_are_a_silent_noop(tmp_path) -> None:
    """Already deleted (e.g. a second boot) — must not raise."""
    install_root = _make_fake_homeassistant_package(tmp_path, ["light"])
    fake_spec = SimpleNamespace(submodule_search_locations=[str(install_root)])

    with patch("custom_components.willo.importlib.util.find_spec", return_value=fake_spec):
        _delete_stock_components()  # frontend/analytics/cloud never existed here — must not raise

    assert (install_root / "components" / "light").exists()


def test_unresolvable_homeassistant_package_logs_warning_and_does_not_raise(caplog) -> None:
    with patch("custom_components.willo.importlib.util.find_spec", return_value=None):
        with caplog.at_level(logging.WARNING):
            _delete_stock_components()  # must not raise even if the package can't be resolved at all

    assert "Could not resolve the installed homeassistant package" in caplog.text


def test_permission_error_on_one_component_is_logged_and_others_still_deleted(tmp_path, caplog) -> None:
    """A OSError deleting one component (e.g. a permission error) must be
    logged as a warning and skipped — it must never stop the other two
    from being deleted, and must never propagate out of the function.
    """
    install_root = _make_fake_homeassistant_package(tmp_path, ["frontend", "analytics", "cloud"])
    fake_spec = SimpleNamespace(submodule_search_locations=[str(install_root)])

    real_rmtree = __import__("shutil").rmtree

    def _flaky_rmtree(path, *args, **kwargs):
        if str(path).endswith("analytics"):
            raise OSError("Permission denied (simulated)")
        return real_rmtree(path, *args, **kwargs)

    with (
        patch("custom_components.willo.importlib.util.find_spec", return_value=fake_spec),
        patch("custom_components.willo.shutil.rmtree", side_effect=_flaky_rmtree),
        caplog.at_level(logging.WARNING),
    ):
        _delete_stock_components()  # must not raise despite the simulated OSError on analytics

    assert not (install_root / "components" / "frontend").exists()
    assert (install_root / "components" / "analytics").exists()  # left in place, deletion failed
    assert not (install_root / "components" / "cloud").exists()
    assert "failed to delete stock 'analytics' component" in caplog.text.lower()


@pytest.mark.parametrize("component_name", ["frontend", "analytics", "cloud"])
def test_only_deletes_the_three_named_components_never_a_lookalike(tmp_path, component_name) -> None:
    """frontend_something/ or my_cloud/ must survive — only an exact
    directory name match is ever removed.
    """
    install_root = _make_fake_homeassistant_package(tmp_path, [f"{component_name}_extra", "light"])
    fake_spec = SimpleNamespace(submodule_search_locations=[str(install_root)])

    with patch("custom_components.willo.importlib.util.find_spec", return_value=fake_spec):
        _delete_stock_components()

    assert (install_root / "components" / f"{component_name}_extra").exists()
