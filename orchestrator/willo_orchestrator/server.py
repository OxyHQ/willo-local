"""The orchestrator's own persistent HTTP surface — serves the built
willo-claim-ui Vite app as static files, plus GET /status, the local JSON
endpoint that app polls roughly once a second (see willo-claim-ui/src/App.tsx).

Per the Willo Local design (OxyHQ/Willo issue #9): Core's own `frontend`
is NOT deleted (see cleanup.py's module doc comment — deleting it crashes
the next `hass` launch outright, and excluding it from configuration.yaml
does not even stop it from running or serving HA's real onboarding
wizard). Instead, `ha_config.py`'s `ensure_explicit_configuration` binds
Core's own `http:` component to loopback only (`server_host: 127.0.0.1`),
verified to make Core's HTTP surface unreachable from any interface but
loopback — while THIS server binds to `WILLO_HOST` (0.0.0.0 by default, a
real network interface), independently and unaffected by that setting, so
this orchestrator is the ONLY thing externally reachable at the device's
public-facing address (`willo.local` on real hardware; the sandbox
machine's real LAN IP in this repo's own end-to-end tests — see the
README's "Cleanup deletion" section for the exact commands that proved
both halves of that claim).
"""

from __future__ import annotations

import logging
from pathlib import Path

from aiohttp import web

from .status import OrchestratorStatus

_LOGGER = logging.getLogger(__name__)


def build_app(status: OrchestratorStatus, static_dir: Path) -> web.Application:
    app = web.Application()

    async def handle_status(request: web.Request) -> web.Response:
        return web.json_response(status.as_json())

    # Registered before the static route below: aiohttp matches routes in
    # registration order where prefixes overlap, and add_static's "/"
    # prefix would otherwise shadow a /status handler registered after it.
    app.router.add_get("/status", handle_status)

    if static_dir.is_dir():
        index_path = static_dir / "index.html"
        resolved_static_dir = static_dir.resolve()

        # A single handler for every path, deliberately NOT using
        # add_static: aiohttp's add_static("/", ...) is a prefix resource
        # that claims every path under "/", including "/" itself (a
        # directory-root request, which 403s with show_index=False) and
        # every unknown deep link (its own 404) — neither case ever falls
        # through to a route registered after it. Confirmed live setting
        # up this exact code for a demo: a browser hitting "/" got a bare
        # 403, not the claim UI. Handling every path in one function sidesteps
        # that router-ordering quirk entirely: serve a real file if the
        # requested path resolves to one inside static_dir, otherwise serve
        # index.html (covers "/" and any future deep link the same way).
        async def handle_path(request: web.Request) -> web.Response:
            tail = request.match_info.get("tail", "")
            candidate = (static_dir / tail).resolve()
            try:
                candidate.relative_to(resolved_static_dir)
            except ValueError:
                return web.Response(status=403, text="Forbidden")
            if candidate.is_file():
                return web.FileResponse(candidate)
            if index_path.is_file():
                return web.FileResponse(index_path)
            return web.Response(status=404, text="willo-claim-ui build not found")

        app.router.add_get("/", handle_path)
        app.router.add_get("/{tail:.*}", handle_path)
    else:
        _LOGGER.warning(
            "willo-claim-ui build directory %s does not exist — only /status will respond. "
            "Run `bun run build` in willo-claim-ui/ first.",
            static_dir,
        )

    return app


async def run_server(status: OrchestratorStatus, static_dir: Path, *, host: str, port: int) -> web.AppRunner:
    """Starts the server and returns the runner (caller owns its lifetime
    — see main.py, which keeps this running for the orchestrator's entire
    process lifetime, per the issue's "owns the user-facing HTTP surface
    permanently" design point).
    """
    app = build_app(status, static_dir)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    _LOGGER.info("Willo orchestrator serving on http://%s:%s (static_dir=%s)", host, port, static_dir)
    return runner
