"""Tests for ha_config.py's ensure_explicit_configuration — the explicit
integration allow-list + loopback-only http binding this orchestrator
writes into configuration.yaml (see ha_config.py's module doc comment for
why this, and not frontend deletion or configuration-only exclusion, is
the mechanism that actually makes Core's HTTP surface unreachable from
outside the device).
"""

from __future__ import annotations

from pathlib import Path

from willo_orchestrator.ha_config import (
    CONFIGURATION_YAML_CONTENT,
    ensure_explicit_configuration,
    has_meaningful_existing_configuration,
)

# A genuinely fresh Home Assistant Core install's own untouched default —
# captured empirically by running a real, never-before-launched `hass`
# against an empty config directory (HA Core 2026.2.3) and reading back
# exactly what it wrote. Kept here (rather than importing the private
# constant from ha_config.py) so this test documents, independently, what
# "fresh" really looks like.
_REAL_FRESH_HA_DEFAULT = """\

# Loads default set of integrations. Do not remove.
default_config:

# Load frontend themes from the themes folder
frontend:
  themes: !include_dir_merge_named themes

automation: !include automations.yaml
script: !include scripts.yaml
scene: !include scenes.yaml
"""

# A realistic stand-in for the real Home Assistant Green this safety fix
# was verified against: a large, hand-authored configuration.yaml with
# packages (HA's mechanism for pulling in real automations/climate control
# from separate files), a shell_command controlling a home router's VPN,
# inline platform config, and a custom dashboard panel — none of which a
# fresh device's configuration.yaml, or Willo's own managed template,
# would ever contain.
_REALISTIC_EXISTING_INSTALL_CONFIGURATION = """\
homeassistant:
  name: Home
  latitude: 45.5017
  longitude: -73.5673
  elevation: 45
  unit_system: metric
  time_zone: America/Toronto
  packages: !include_dir_named packages

frontend:
  themes: !include_dir_merge_named themes
  extra_module_url:
    - /local/marco-panel/marco-panel.js

http:
  use_x_forwarded_for: true
  trusted_proxies:
    - 127.0.0.1

api:
config:

automation: !include automations.yaml
script: !include scripts.yaml
scene: !include scenes.yaml

shell_command:
  vpn_router_reconnect: "ssh router 'wg-quick down wg0 && wg-quick up wg0'"
  vpn_router_status: "ssh router 'wg show'"

climate:
  - platform: generic_thermostat
    name: Living Room
    heater: switch.living_room_heater
    target_sensor: sensor.living_room_temperature

sensor:
  - platform: template
    sensors:
      ventilation_duty_cycle:
        friendly_name: "Ventilation duty cycle"
        value_template: "{{ states('sensor.ventilation_runtime') }}"

lovelace:
  mode: yaml
  resources:
    - url: /local/marco-panel/marco-panel.js
      type: module
"""


def test_has_meaningful_existing_configuration_false_when_missing(tmp_path: Path) -> None:
    assert has_meaningful_existing_configuration(tmp_path) is False


def test_has_meaningful_existing_configuration_false_for_willos_own_template(tmp_path: Path) -> None:
    (tmp_path / "configuration.yaml").write_text(CONFIGURATION_YAML_CONTENT)

    assert has_meaningful_existing_configuration(tmp_path) is False


def test_has_meaningful_existing_configuration_false_for_real_ha_default(tmp_path: Path) -> None:
    (tmp_path / "configuration.yaml").write_text(_REAL_FRESH_HA_DEFAULT)

    assert has_meaningful_existing_configuration(tmp_path) is False


def test_has_meaningful_existing_configuration_true_for_a_realistic_existing_install(tmp_path: Path) -> None:
    (tmp_path / "configuration.yaml").write_text(_REALISTIC_EXISTING_INSTALL_CONFIGURATION)

    assert has_meaningful_existing_configuration(tmp_path) is True


def test_has_meaningful_existing_configuration_true_for_packages_alone(tmp_path: Path) -> None:
    # packages: lives NESTED under homeassistant:, not as a top-level key —
    # a short file that is otherwise entirely "safe" but references a
    # packages directory (which could itself hold hundreds of lines of
    # real automations) must still be treated as real.
    (tmp_path / "configuration.yaml").write_text(
        "homeassistant:\n"
        "  name: Home\n"
        "  packages: !include_dir_named packages\n"
        "\n"
        "automation: !include automations.yaml\n"
        "script: !include scripts.yaml\n"
        "scene: !include scenes.yaml\n"
    )

    assert has_meaningful_existing_configuration(tmp_path) is True


def test_has_meaningful_existing_configuration_true_for_an_unrecognized_top_level_key(tmp_path: Path) -> None:
    (tmp_path / "configuration.yaml").write_text(CONFIGURATION_YAML_CONTENT + "\nmqtt:\n  broker: 192.168.1.5\n")

    assert has_meaningful_existing_configuration(tmp_path) is True


def test_has_meaningful_existing_configuration_true_for_unparseable_content(tmp_path: Path) -> None:
    # Deliberately conservative: content this can't even parse is treated
    # as real/unknown, never as "fresh".
    (tmp_path / "configuration.yaml").write_text("this: is: not: valid: yaml: [")

    assert has_meaningful_existing_configuration(tmp_path) is True


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
