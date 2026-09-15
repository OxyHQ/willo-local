"""The inert stub that replaces the real `frontend` component's files —
see `_replace_frontend_with_stub` in `__init__.py` for how and when this
gets written, and this repo's README, "Cleanup deletion" section, for the
full investigation this came out of.

WHY A STUB INSTEAD OF DELETING `frontend`: physically deleting it crashes
the next `hass` launch outright (`homeassistant/bootstrap.py` hard-imports
`homeassistant.components.config` at module level, which hard-imports
`frontend` at ITS top level). A stub keeps the SAME importable module path
and the SAME symbols other stock code needs, so every one of those imports
still succeeds — it just does nothing real: no HTTP views, no static
assets, no wizard, no dashboard.

FRAGILITY, FLAGGED PLAINLY: `homeassistant.components.frontend`'s
internals (`DATA_PANELS`, `MANIFEST_JSON`, `async_register_built_in_panel`,
`async_remove_panel`, `async_system_store`) are NOT a documented, stable
public API — `frontend` is an `integration_type: system` component, and
nothing about its internal symbol names or function signatures is
guaranteed not to change between HA releases the way `http: server_host`
(a real, documented, user-facing config key) is. STUB_INIT_PY below was
built by exhaustively grepping every `from homeassistant.components import
frontend` / `from homeassistant.components.frontend import X` across the
ENTIRE installed `homeassistant==2026.2.3` package — see the README for
the exact commands — and is only as correct as that snapshot. A future HA
version could add a new stock component that imports a new symbol from
`frontend`; the most likely failure mode is that ONE component's setup
logging a soft "Setup failed for X" error (the same category of
degradation already accepted for the analytics/cloud deletion below) —
not a repeat of the frontend-deletion crash, since bootstrap.py's own
hard-imported chain only needs `frontend` to exist and expose what
`config/__init__.py` touches, which this stub still does. Still, re-run
this file's derivation grep before bumping the target HA version — see
the README's "Loopback binding + inert stub" section for the commands.

This is why loopback binding (see orchestrator/willo_orchestrator/
ha_config.py) is the mechanism this repo treats as load-bearing — it
relies on a real, documented HA config option, not a reverse-engineered
internal contract, so it must never be removed even with this stub in
place. This stub is defense-in-depth layered on top of it, not a
replacement for it — verified to remain safe to lose (see
_replace_frontend_with_stub's try/except): if writing or swapping in the
stub fails for any reason, this function logs a warning and leaves the
real `frontend` in place, exactly as if this stub didn't exist at all.
"""

from __future__ import annotations

STUB_MANIFEST_JSON = """\
{
  "domain": "frontend",
  "name": "Home Assistant Frontend",
  "codeowners": ["@home-assistant/frontend"],
  "dependencies": [
    "api",
    "auth",
    "config",
    "device_automation",
    "diagnostics",
    "file_upload",
    "http",
    "lovelace",
    "onboarding",
    "repairs",
    "search",
    "system_log",
    "websocket_api"
  ],
  "documentation": "https://www.home-assistant.io/integrations/frontend",
  "integration_type": "system",
  "quality_scale": "internal"
}
"""

STUB_INIT_PY = '''\
"""STUB replacement for homeassistant.components.frontend, written by
Willo Local (OxyHQ/Willo issue #9) — see custom_components/willo/
frontend_stub.py for the full explanation. Registers nothing: no HTTP
views, no static assets, no websocket commands, no onboarding.html, no
dashboard.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.typing import ConfigType
from homeassistant.util.hass_dict import HassKey

DOMAIN = "frontend"

DATA_PANELS: HassKey[dict[str, Any]] = HassKey("frontend_panels")

MANIFEST_JSON: dict[str, Any] = {
    "background_color": "#FFFFFF",
    "description": "Willo",
    "dir": "ltr",
    "display": "standalone",
    "icons": [],
    "name": "Willo",
    "short_name": "Willo",
    "start_url": "/",
    "theme_color": "#03A9F4",
}


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    hass.data.setdefault(DATA_PANELS, {})

    async def _reload_themes_noop(call: ServiceCall) -> None:
        return None

    hass.services.async_register(DOMAIN, "reload_themes", _reload_themes_noop)

    return True


def async_register_built_in_panel(
    hass: HomeAssistant,
    component_name: str,
    sidebar_title: str | None = None,
    sidebar_icon: str | None = None,
    sidebar_default_visible: bool = True,
    frontend_url_path: str | None = None,
    config: dict[str, Any] | None = None,
    require_admin: bool = False,
    *,
    update: bool = False,
    config_panel_domain: str | None = None,
) -> None:
    panels = hass.data.setdefault(DATA_PANELS, {})
    panels[frontend_url_path or component_name] = None


def async_remove_panel(hass: HomeAssistant, frontend_url_path: str, *, warn_if_unknown: bool = True) -> None:
    hass.data.setdefault(DATA_PANELS, {}).pop(frontend_url_path, None)


class _InertSystemStore:
    data: dict[str, Any] = {}

    async def async_set_item(self, key: str, value: Any) -> None:
        self.data[key] = value


async def async_system_store(hass: HomeAssistant) -> "_InertSystemStore":
    return _InertSystemStore()
'''
