# Willo for Home Assistant

Connects this Home Assistant instance to [Willo](https://willo.sh) — no
port forwarding, no HTTPS certificate, no static IP. This integration opens
one **outbound** connection to Willo's backend and keeps it open; the Willo
app never talks to Home Assistant directly.

## Install

1. Add this repository to [HACS](https://hacs.xyz/) as a custom repository
   (category: Integration), or copy `custom_components/willo` into your
   Home Assistant's own `custom_components/` folder.
2. Restart Home Assistant.
3. Settings → Devices & Services → Add Integration → **Willo**.
4. In the Willo app, create a home and generate a pairing code.
5. Enter that code here. Done — no URL, no OAuth, nothing else to configure.

## What it does

- Sends Willo a snapshot of your `light`, `fan`, `sensor`, and `camera`
  entities on connect, and pushes an update the moment any of them change.
- Executes commands Willo sends back (turn on/off, set brightness, set fan
  speed) via Home Assistant's own service-call API — nothing here talks to
  a device directly; Home Assistant still does.
- Reconnects automatically if the connection drops (a router reboot, a
  brief outage) — no user action needed.

## Development

Pure Python, no relation to the Willo web app's own toolchain (that lives in
[`OxyHQ/Willo`](https://github.com/OxyHQ/Willo)). See
`custom_components/willo/__init__.py`'s module doc comment for the wire
protocol this speaks to Willo's backend
(`packages/backend/src/realtime/tunnelNamespace.ts` in that repo).

Run the integration's own tests (`pytest-homeassistant-custom-component`,
which spins up a real, minimal in-process HomeAssistant instance per test
— not a mock of HA itself):

```
pip install pytest-homeassistant-custom-component
pip install "python-socketio[asyncio_client]>=5.11,<6" "PyTurboJPEG==1.8.0"  # this integration's own manifest requirements
pytest tests/
```

## Willo Local (`orchestrator/` + `willo-claim-ui/`)

[OxyHQ/Willo issue #9](https://github.com/OxyHQ/Willo/issues/9) adds a
second way to get onto a Willo home: instead of a person going through
Home Assistant's own onboarding wizard and typing a pairing code, a
factory-provisioned Home Assistant Green boots straight into a
Willo-branded status screen (`willo-claim-ui/`, a small Vite app) driven by
a persistent on-device process (`orchestrator/`) that:

1. serves the built claim UI + a local `GET /status`
2. polls Core's REST API until it's up
3. drives HA's real onboarding REST API (creates a throwaway
   `willo-svc-<hex>` admin, finishes the core_config/analytics/integration
   steps)
4. deletes `analytics`/`cloud` from the installed `homeassistant` package
   (belt-and-suspenders — `frontend` is deliberately NOT deleted; see
   "Cleanup deletion" below for why)
5. calls the real Willo backend's `POST /tunnel/claim` /
   `GET /tunnel/claim/status`, falling back to a clearly-logged local mock
   if that backend isn't reachable
6. writes the `willo` config entry directly into
   `.storage/core.config_entries` and restarts Core
7. `GET /status` reflects every one of these stages live:
   `onboarding → syncing → awaiting-pairing → paired`

Run it locally:

```
cd willo-claim-ui && bun install && bun run build   # produces dist/, which the orchestrator serves
cd ../orchestrator && pip install -e . && pip install -e ".[test]"
pytest tests/
WILLO_HA_BASE_URL=http://localhost:8123 \
WILLO_HA_CONFIG_DIR=/path/to/a/fresh/unonboarded/ha/config \
WILLO_STATIC_DIR=../willo-claim-ui/dist \
WILLO_PORT=8080 \
python -m willo_orchestrator.main
```

### What was actually verified, and how

Everything below was tested against a **real, local Home Assistant Core
2026.2.3**, installed with `pip install homeassistant==2026.2.3` into a
disposable Python 3.13 venv (no Docker available in the sandbox this was
built in) — never against real Home Assistant Green / HAOS hardware, and
never against the user's own home network. That distinction matters for
the two open items at the very end of this section.

**Cleanup deletion — `frontend` is intentionally never deleted, and
`configuration.yaml` alone cannot hide it either. Read this before
touching either copy of `_delete_stock_components`.**

This went through three real, tested iterations, in this order:

1. *Delete `frontend`/`analytics`/`cloud`, every boot* (the plan as
   originally written). Every other stock component that imports
   `frontend`/`analytics`/`cloud` at module level was found by grepping
   the installed package: `config`, `history`, `logbook`, `lovelace`,
   `hassio`, `mobile_app`, `my`, `panel_custom`, `calendar`, `energy`,
   `media_source`, `todo` (all import `frontend`); `mobile_app`,
   `netatmo`, `owntracks`, `plaato`, `rachio`, `toon`, `withings`,
   `loqed`, `overseerr` import `cloud` (but only `http`'s reference is a
   deferred/lazy import, `# noqa: PLC0415`, not a hard dependency — the
   rest are third-party integrations never loaded unless configured);
   `esphome`/`wled` import `analytics` (component-specific, not
   force-loaded). Far more importantly: **`homeassistant/bootstrap.py`
   itself unconditionally imports `config` at the top of the file**
   (`from .components import (... config as config_pre_import ...)`, a
   performance pre-import that runs regardless of `configuration.yaml`),
   and `homeassistant/components/config/__init__.py` does `from
   homeassistant.components import frontend` at ITS top level. Deleting
   `frontend` therefore does not just risk a "some panel doesn't
   register" failure inside a running Core — **it makes the `hass`
   process itself fail to start**, with `ImportError: cannot import name
   'frontend' from 'homeassistant.components'`, before bootstrap's own
   error handling or recovery-mode logic can even run. Proven twice: by
   deleting `frontend` and relaunching `hass` directly, and through the
   real orchestrator + integration pipeline (a full onboarding → cleanup
   → claim → pair → restart run deleted `frontend`, wrote a real config
   entry, called the real `homeassistant.restart` service, and the next
   `hass` launch on that same config directory crashed with the identical
   traceback). **Rejected — reverted.**
2. *Stop deleting `frontend`; instead exclude it from an explicit
   `configuration.yaml` component list* (no `default_config:`, no
   `frontend:` key). This does NOT achieve the goal either, and does not
   even reduce exposure: `bootstrap.py`'s `_get_domains()` unconditionally
   does `domains.update(DEFAULT_INTEGRATIONS)` for every non-recovery-mode
   boot, and `DEFAULT_INTEGRATIONS` includes `"frontend"` — so it is
   force-loaded and force-set-up *regardless* of what
   `configuration.yaml` says. Recovery mode doesn't help either:
   `DEFAULT_INTEGRATIONS_RECOVERY_MODE = {"frontend"}` force-includes it
   there too, and `recovery_mode` isn't even a `configuration.yaml` key —
   it's CLI-only (`--recovery-mode`) or triggered by bootstrap failure.
   Proven live: booted HA with an explicit `configuration.yaml`
   (`homeassistant:`, `api:`, `config:`, `http:` — no `frontend:`
   anywhere, no `default_config:`) and `frontend`'s files fully intact on
   disk, then `curl -i http://localhost:8123/` → `HTTP/1.1 302 Found`,
   `location: /onboarding.html`; `curl http://localhost:8123/onboarding.html`
   returned real HA-branded HTML (`<title>Home Assistant</title>`,
   `<ha-onboarding>`); an authenticated `GET /api/config` confirmed
   `"frontend" in components` is `true`. **Does not work — do not rely on
   `configuration.yaml` alone to hide `frontend`.**
3. *Stop deleting `analytics`/`cloud` from being the whole story too —
   restrict Core's own `http:` to loopback only.* Since `frontend` cannot
   be deleted (crashes reboot) or hidden via config (still force-loaded),
   the only verified way to make it actually unreachable from outside the
   device is network-level: `http: { server_host: 127.0.0.1 }` in
   `configuration.yaml`. Proven live: with that key set, `ss -ltnp` showed
   Core bound to `127.0.0.1:8123` only (not `0.0.0.0:8123`/`*:8123`), so
   no other host on the network can reach it at all — while
   `curl http://127.0.0.1:8123/` from the same device still worked
   (`302`), meaning the orchestrator (which runs on the same device) is
   unaffected. **This is the verified path to "no HA UI ever reachable
   from outside this device" — it is NOT yet wired into this repo. Adding
   `server_host: 127.0.0.1` to whatever `configuration.yaml` the
   orchestrator writes/manages is a real, concrete next step, but a
   deliberate one to confirm before building — it changes the shape of
   Core's own config, and how real HAOS's Supervisor/Ingress already
   manages `http:` bindings could not be verified in this sandbox (see
   the open items below).**

`analytics` is separately force-attempted on every boot regardless of
`configuration.yaml`, same mechanism as `frontend` (`DEFAULT_INTEGRATIONS`
includes it too, commented `# Needed for onboarding` in HA's own source,
and `/api/onboarding/core_config`'s real handler does `await
async_setup_component(hass, "analytics", {})` as a fallback). Unlike
`frontend`, `analytics` is NOT in `CRITICAL_INTEGRATIONS`, so a missing
`analytics` directory only produces one `ERROR (MainThread)
[homeassistant.setup] Setup failed for 'analytics'` log line and does not
crash Core or trigger recovery mode — confirmed by booting repeatedly with
`analytics`+`cloud` deleted and `frontend` intact, which came up
completely healthy every time (see "Re-verification" below for the exact
repeated-boot run). `cloud` is not in `DEFAULT_INTEGRATIONS` at all and is
only pulled in if explicitly configured, or (on real Supervisor) as a
dependency of `hassio` — checked, `hassio`'s manifest only depends on
`http`/`repairs`, not `cloud`.

**Net, current state**: `custom_components/willo/__init__.py` and
`orchestrator/willo_orchestrator/cleanup.py` both delete `analytics` and
`cloud` only — `frontend` is excluded from
`_STOCK_COMPONENTS_TO_REMOVE`/`STOCK_COMPONENTS_TO_REMOVE` in both files,
permanently, with the finding above in a comment directly above that
constant so it doesn't get silently reintroduced. Every failure is still
caught and logged, never raised. The network-binding mitigation for
`frontend` itself is verified but not yet implemented — flagging this as
the concrete next decision rather than guessing at it.

### Re-verification after dropping frontend deletion

All of the below is a second, independent pass, done after the finding
above and reported precisely rather than assumed:

- **Full pipeline with the corrected cleanup step**: a fresh, never-
  onboarded HA Core instance was driven through the real orchestrator —
  onboarding → `analytics`/`cloud` deletion (`frontend` never touched) →
  mock claim (forced via `WILLO_CLAIM_URL` pointing at an unreachable
  address, the same legitimate env-var override used for the real backend
  URL, since completing a *real* claim needs a live Willo-app owner) →
  headless entry write → `homeassistant.restart` service call. `GET
  /status` was polled live throughout and showed
  `onboarding → syncing → awaiting-pairing → paired`, same as before the
  fix. The orchestrator's own log shows exactly two deletions
  (`deleted stock 'analytics' component...`, `deleted stock 'cloud'
  component...`) and no attempt at `frontend` anywhere.
- **Repeated-boot stability — the exact test that originally caught the
  crash, repeated 5 times**: after the pipeline above paired the device
  (so a real `willo` config entry now exists, exercising both this
  integration's own cleanup copy AND the orchestrator's), `hass` was
  relaunched on that same config directory **5 times in a row**. Every
  single launch reached a healthy, API-responding state
  (`curl http://localhost:8123/api/` → `401`, the expected
  "unauthenticated but alive" response) in ~3 seconds, with **no crash, no
  recovery-mode fallback, and no `ImportError`** in any of the 5 logs —
  the only `ERROR`-level lines across all 5 were benign artifacts of the
  test harness killing `hass` mid-setup between cycles (a cancelled
  socketio connect attempt, `asyncio.exceptions.CancelledError: Home
  Assistant is stopping`), not bootstrap failures. `frontend`'s files
  were still present and intact after all 5 cycles.
- **`frontend` is genuinely still reachable — this is expected, and is
  exactly why the goal is not yet fully met.** On the same instance,
  `GET /` returned `HTTP/1.1 200 OK` with 5917 bytes of real HA dashboard
  HTML (it was a `302 → /onboarding.html` before pairing, in the earlier
  "does configuration.yaml exclusion work" test — both are `frontend`
  actively serving real content, just at different points in onboarding).
  **This confirms the trade this fix makes**: reboots are now safe
  (no crash), at the cost of `frontend` being fully reachable again unless
  the network-binding mitigation above is also implemented — that part of
  the original goal ("no HA UI ever reachable") is NOT met by this change
  alone, and is flagged as the next concrete step rather than
  papered over.

**Headless config-entry creation — mechanism (b) chosen, verified working
end-to-end; mechanism (a) verified NOT to work.**

- Mechanism (a), HA's config-entries REST flow API: rejected.
  `homeassistant/components/config/config_entries.py`'s
  `ConfigManagerFlowIndexView.get_context()` hardcodes
  `context["source"] = config_entries.SOURCE_USER` for every flow
  initiated through `POST /api/config/config_entries/flow` — confirmed
  both by reading that source and by driving the real endpoint
  (`curl -X POST .../api/config/config_entries/flow -d '{"handler":
  "willo"}'` with a real admin bearer token) against a live `willo`
  integration, which always landed on `step_id: "user"`.
- Mechanism (b), a direct `.storage/core.config_entries` write + Core
  restart: chosen, and verified two different ways — a hand-written entry
  with the schema in `orchestrator/willo_orchestrator/ha_entry.py`'s
  doc comment, AND the real orchestrator's own `write_willo_entry()` in a
  full end-to-end run — both were picked up correctly by Core on restart
  and had `async_setup_entry` genuinely invoked (proven by the entry
  landing in `state: "setup_retry"`, `reason: "Could not reach Willo's
  tunnel at https://api.willo.sh"` — that exact string only comes from
  `custom_components/willo/__init__.py`'s own `ConfigEntryNotReady` path).
- `custom_components/willo/config_flow.py` still gained the
  `async_step_claim` step the issue asked for (accepts `{home_id,
  secret}`, no HTTP call, no form) — it's real and tested
  (`tests/test_config_flow.py`), but per the above it is reachable only
  from code running *inside* HA Core's own process
  (`hass.config_entries.flow.async_init(DOMAIN, context={"source":
  "claim"}, data=...)`), not by the orchestrator, which is a separate
  process by design.

**Onboarding REST automation — verified end-to-end on HA 2026.2.3.** Real
endpoints and payloads, read from `homeassistant/components/onboarding/views.py`
and confirmed live:
`GET /api/onboarding` → `[{"step": "user"|"core_config"|"analytics"|"integration", "done": bool}, ...]`;
`POST /api/onboarding/users` `{name, username, password, client_id, language}` → `{auth_code}`;
`POST /auth/token` (`grant_type=authorization_code`, `code`, `client_id`) → `{access_token, refresh_token, expires_in, ...}`;
`POST /api/onboarding/core_config`, `POST /api/onboarding/analytics` (bearer auth, empty body) → `{}`;
`POST /api/onboarding/integration` `{client_id, redirect_uri}` (bearer auth) → `{auth_code}`.

**The real Willo backend claim routes went live mid-development.** At the
start of this work, `https://api.willo.sh/tunnel/claim` answered `404
Cannot POST /tunnel/claim` (reachable host, undeployed route — the
backend for this same issue was being built in parallel). By the end,
the same call answered `201 {"claimCode", "claimToken", "expiresAt"}` and
`GET /tunnel/claim/status` answered `{"status": "pending"}` — both
matching the documented contract exactly, confirmed by
`orchestrator/willo_orchestrator/main.py`'s own real run against it (see
its log: a real `POST` succeeded, no mock fallback triggered). Completing
a real `claimed` transition needs an authenticated Willo-app owner
calling `POST /homes/:id/claim-device`, out of scope here — the mock in
`willo_client.py` (`WILLO_CLAIM_URL`/`WILLO_CLAIM_STATUS_URL` env vars
point at it when the real backend is unreachable) exists to exercise that
transition and the rest of the boot sequence without it.

**Still genuinely unverified — needs real HAOS hardware, not a plain venv
or Docker Core install:**

- The HAOS Supervisor hostname-rename API (`willo.local`) — Supervisor's
  own REST surface does not exist in a plain `pip install homeassistant`
  environment at all.
- Add-on ↔ Core networking and filesystem access under actual
  Supervisor management. In particular,
  `orchestrator/willo_orchestrator/cleanup.py`'s belt-and-suspenders
  deletion assumes `homeassistant` is importable from wherever the
  orchestrator runs — true in every sandbox test here (orchestrator and
  Core share one venv), but a real HAOS add-on normally runs in its own
  container, isolated from Core's container filesystem by default. Nothing
  in this task could confirm whether the real `willo-local` add-on will
  have access to Core's installed package path at all — flagging this
  plainly rather than assuming it "just works" on real hardware.

No code in this repository or its tests ever attempted to reach real Home
Assistant Green / HAOS hardware or the user's home network — every test
above ran against a disposable local HA Core install created for this
task, and `custom_components/willo`'s own tunnel target
(`DEFAULT_TUNNEL_URL`) was never pointed anywhere but the real, public
`api.willo.sh` (reachable from this sandbox, unrelated to any home
network) or an explicit local test stub.
