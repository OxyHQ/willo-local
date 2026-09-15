"""Tests for ha_config.py's ensure_explicit_configuration — the explicit
integration allow-list + loopback-only http binding this orchestrator
writes into configuration.yaml (see ha_config.py's module doc comment for
why this, and not frontend deletion or configuration-only exclusion, is
the mechanism that actually makes Core's HTTP surface unreachable from
outside the device).
"""

from __future__ import annotations

from pathlib import Path

from willo_orchestrator.ha_config import CONFIGURATION_YAML_CONTENT, ensure_explicit_configuration


def test_writes_the_file_and_reports_changed_when_missing(tmp_path: Path) -> None:
    changed = ensure_explicit_configuration(tmp_path)

    assert changed is True
    assert (tmp_path / "configuration.yaml").read_text() == CONFIGURATION_YAML_CONTENT


def test_reports_unchanged_on_a_second_call(tmp_path: Path) -> None:
    ensure_explicit_configuration(tmp_path)

    changed = ensure_explicit_configuration(tmp_path)

    assert changed is False


def test_overwrites_and_reports_changed_when_content_differs(tmp_path: Path) -> None:
    (tmp_path / "configuration.yaml").write_text("default_config:\n")

    changed = ensure_explicit_configuration(tmp_path)

    assert changed is True
    assert (tmp_path / "configuration.yaml").read_text() == CONFIGURATION_YAML_CONTENT


def test_content_binds_http_to_loopback_only() -> None:
    assert "server_host: 127.0.0.1" in CONFIGURATION_YAML_CONTENT


def test_content_never_uses_default_config() -> None:
    # A mention inside an explanatory comment is fine (and expected) — an
    # actual `default_config:` YAML key is not.
    non_comment_lines = [line for line in CONFIGURATION_YAML_CONTENT.splitlines() if not line.strip().startswith("#")]
    assert not any(line.strip() == "default_config:" for line in non_comment_lines)


def test_content_excludes_frontend_analytics_cloud_keys() -> None:
    # Not that this stops them loading (it doesn't — see ha_config.py's
    # doc comment) — just documenting that this file never explicitly
    # opts into them either.
    for domain in ("frontend", "analytics", "cloud"):
        assert f"{domain}:" not in CONFIGURATION_YAML_CONTENT
