"""Frontend stub swap, run BY THE ORCHESTRATOR on a fresh Willo Local
device only (main.py step 4 runs after the explicit configuration.yaml has
been written, which only happens on a genuinely fresh device).

There used to be an analytics/cloud deletion here too. It was removed
because it was never needed and is dangerous. With the explicit
configuration.yaml allow-list (ha_config.py) `cloud` is never loaded, since
HA only sets it up when the configuration or a dependency asks for it. The
onboarding analytics step leaves analytics preferences empty, so analytics
sends nothing. Deleting either component's files on a normal install breaks
`default_config`, which hard-depends on `cloud`.

`frontend` is never deleted outright — only replaced by a stub. Deleting it
was tried and reverted after real testing:
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
writeup, the exact commands that proved both of the above.

The mechanism actually wired in for reachability is network-level:
`orchestrator/willo_orchestrator/ha_config.py` binds Core's own `http:` to
loopback only, verified to make Core genuinely unreachable from any
non-loopback interface. `replace_frontend_with_stub` below is
defense-in-depth LAYERED ON TOP of that — see frontend_stub.py for the
full rationale and an explicit fragility caveat (it depends on an
undocumented internal HA contract, unlike the loopback binding, which
depends on a real documented config key) — never a substitute for it.
"""

from __future__ import annotations

import importlib.util
import logging
import shutil
from pathlib import Path

from .frontend_stub import STUB_INIT_PY, STUB_MANIFEST_JSON

_LOGGER = logging.getLogger(__name__)

def replace_frontend_with_stub() -> None:
    """Replace the installed `frontend` component's files with an inert
    stub — see frontend_stub.py for the full rationale and fragility
    caveat. Defense-in-depth on TOP of loopback binding, never a
    substitute for it (see this module's doc comment). Has its own
    try/except: a failure here must never crash this process.
    """
    spec = importlib.util.find_spec("homeassistant")
    if spec is None or not spec.submodule_search_locations:
        _LOGGER.warning(
            "Could not resolve the installed homeassistant package via importlib; "
            "skipping the frontend stub swap this boot"
        )
        return

    for install_root in spec.submodule_search_locations:
        frontend_dir = Path(install_root) / "components" / "frontend"
        try:
            if frontend_dir.is_dir():
                shutil.rmtree(frontend_dir)
            frontend_dir.mkdir(parents=True, exist_ok=True)
            (frontend_dir / "__init__.py").write_text(STUB_INIT_PY)
            (frontend_dir / "manifest.json").write_text(STUB_MANIFEST_JSON)
            _LOGGER.info("Willo orchestrator: replaced the 'frontend' component with an inert stub at %s", frontend_dir)
        except OSError:
            _LOGGER.warning(
                "Willo orchestrator: failed to replace the 'frontend' component with a stub at %s — "
                "leaving the real component in place (loopback binding is still the load-bearing "
                "protection either way)",
                frontend_dir,
                exc_info=True,
            )
