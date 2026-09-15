"""Belt-and-suspenders analytics/cloud deletion, run BY THE ORCHESTRATOR
ITSELF — separate from, and in addition to,
custom_components/willo/__init__.py's own copy of this same logic.

Why two copies: the willo integration's own async_setup_entry only runs
once a `willo` config entry exists — i.e. only after this orchestrator has
already finished pairing the device. On the very first boot of a factory
device, there is no config entry yet, so nothing inside HA Core would ever
run this deletion. The orchestrator runs it directly, early in its own
boot sequence (see main.py step 4), so analytics/cloud are gone before
onboarding even finishes — not just after pairing.

This is intentionally NOT imported from custom_components/willo (that
would pull `homeassistant` and `python-socketio` into this process' own
dependency set for no reason — this process only needs to delete some
directories, it never imports anything from the `homeassistant` package
itself). Keep this logic identical to __init__.py's _delete_stock_components.

`frontend` is DELIBERATELY EXCLUDED from STOCK_COMPONENTS_TO_REMOVE — do
not add it back. It was tried and reverted after real testing:
`homeassistant/bootstrap.py` unconditionally imports
`homeassistant.components.config` at module level, which itself imports
`frontend` at ITS top level — so deleting `frontend`'s files makes the
very next `hass` process launch crash outright with `ImportError: cannot
import name 'frontend' from 'homeassistant.components'`, before Core's own
recovery-mode logic can even run. Excluding `frontend` from
`configuration.yaml` does not avoid this either, and does not even stop
`frontend` from running: `bootstrap._get_domains()` unconditionally merges
`DEFAULT_INTEGRATIONS` (which includes `"frontend"`) into every
non-recovery-mode boot regardless of `configuration.yaml`'s content, and
recovery mode force-includes `frontend` too — confirmed by booting HA with
`frontend:` absent from an explicit `configuration.yaml` and getting a
real `302 → /onboarding.html`, serving HA's actual onboarding wizard HTML,
anyway. See this repo's README, "Cleanup deletion" section, for the full
writeup, the exact commands that proved both of the above, and the
network-level mitigation (binding Core's own `http:` to loopback only)
verified to actually achieve "unreachable from outside this device"
instead — not yet wired into this orchestrator pending a design decision.
"""

from __future__ import annotations

import importlib.util
import logging
import shutil
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

STOCK_COMPONENTS_TO_REMOVE = ("analytics", "cloud")


def delete_stock_components() -> None:
    """Delete analytics/ and cloud/ from the installed homeassistant
    package. Must never raise — see this module's doc comment and
    custom_components/willo/__init__.py's identical function for why
    every failure here is a logged warning, not a crash.

    UNVERIFIED ON REAL HAOS, FLAGGING PLAINLY: this only does anything
    useful if `homeassistant` is importable from wherever THIS process
    runs — true in every sandbox test in this repo (orchestrator and Core
    share one venv there), but on real Home Assistant OS a Supervisor
    add-on normally runs in its OWN container, isolated from Core's
    container filesystem by default (add-ons get access to paths like
    /config, /share, /addon_configs — not another container's Python
    site-packages). If the willo-local add-on's `config.yaml` does not
    explicitly mount Core's install path (or run with elevated access),
    `find_spec` below returns None here, this function logs the warning
    below and does nothing, and the willo integration's OWN copy of this
    same logic (which runs inside Core's process, where the package is
    always importable) becomes the only copy that actually does anything
    — which is fine on the SECOND boot onward (the integration's copy
    covers it), but means this orchestrator-side copy cannot be assumed
    to help on the very first boot, before any config entry exists, on
    real HAOS. Confirming which is true requires real HAOS Supervisor
    hardware — this is one of the open items this task could not verify
    in a plain venv/Docker sandbox (see this repo's README).
    """
    spec = importlib.util.find_spec("homeassistant")
    if spec is None or not spec.submodule_search_locations:
        _LOGGER.warning(
            "Could not resolve the installed homeassistant package via importlib; "
            "skipping analytics/cloud cleanup this boot"
        )
        return

    for install_root in spec.submodule_search_locations:
        components_dir = Path(install_root) / "components"
        for component_name in STOCK_COMPONENTS_TO_REMOVE:
            component_dir = components_dir / component_name
            try:
                if component_dir.is_dir():
                    shutil.rmtree(component_dir)
                    _LOGGER.info("Willo orchestrator: deleted stock '%s' component at %s", component_name, component_dir)
            except OSError:
                _LOGGER.warning(
                    "Willo orchestrator: failed to delete stock '%s' component at %s — leaving it in place",
                    component_name,
                    component_dir,
                    exc_info=True,
                )
