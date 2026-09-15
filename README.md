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

1. serves the built claim UI + a local `GET /status`, bound to a real
   network interface (`WILLO_HOST`, `0.0.0.0` by default) — independent of
   anything below, see "Cleanup deletion" for why that independence
   matters
2. polls Core's REST API until it's up
3. completes onboarding's "user" step (the only one that needs no
   pre-existing auth) to get an admin token
4. writes `configuration.yaml`'s explicit integration allow-list +
   loopback-only `http:` binding if it doesn't already match, and — only
   if it changed — restarts Core and resumes once it's back up
5. drives the rest of HA's onboarding REST API (core_config/analytics/
   integration steps)
6. deletes `analytics`/`cloud` from the installed `homeassistant` package
   (belt-and-suspenders — `frontend` is deliberately NOT deleted; see
   "Cleanup deletion" below for why)
7. calls the real Willo backend's `POST /tunnel/claim` /
   `GET /tunnel/claim/status`, falling back to a clearly-logged local mock
   if that backend isn't reachable
8. writes the `willo` config entry directly into
   `.storage/core.config_entries` and restarts Core
9. `GET /status` reflects every one of these stages live:
   `onboarding → syncing → awaiting-pairing → paired` — and separately,
   as soon as it's known (not gated behind onboarding), a `deviceModel`
   field ("Green", "Yellow", `null` off-Supervisor) the Willo app's own
   auto-detect screen reads directly, without this orchestrator's own
   claim UI ever displaying it — see `device_model.py` and the open
   items below for what's verified and what still needs real HAOS
   hardware

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
   unaffected. **This is the mechanism actually implemented — see
   "Loopback binding" below for the full wiring and the real
   non-loopback reachability proof.**

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
caught and logged, never raised. Reachability is handled separately, at
the network level — see below.

### Loopback binding — the implemented, verified mechanism for "no HA UI ever reachable from outside this device"

`orchestrator/willo_orchestrator/ha_config.py`'s `ensure_explicit_configuration`
writes a fixed `configuration.yaml` (explicit `api:`/`config:`/`http:`
allow-list, never `default_config:`, `http: { server_port: 8123,
server_host: 127.0.0.1 }`) and reports whether it changed anything.
`main.py`'s boot sequence calls it right after onboarding's "user" step
(the only step that needs no pre-existing auth — a factory-fresh device
has no admin account before it), and only restarts Core if the file
actually changed, resuming the rest of onboarding once Core is back up.
`orchestrator/willo_orchestrator/server.py`'s own HTTP server is entirely
separate — bound to `WILLO_HOST` (`0.0.0.0` by default), never touched by
anything in `ha_config.py`.

**Verified for real, both halves of the claim, from a genuinely
non-loopback address — not just `127.0.0.1`, which would be trivial and
prove nothing:**

```
$ ss -ltnp | grep -E "8123|8098"
LISTEN 0 128     0.0.0.0:8098 0.0.0.0:*  users:(("python3",pid=...))   # orchestrator
LISTEN 0 128   127.0.0.1:8123 0.0.0.0:*  users:(("hass",pid=...))      # Core

$ curl -m5 http://192.168.8.50:8123/          # Core, via the sandbox machine's real LAN IP
curl: (7) Failed to connect to 192.168.8.50 port 8123 after 0 ms: Could not connect to server

$ curl -m5 -o /dev/null -w '%{http_code}\n' http://192.168.8.50:8098/status   # orchestrator, same IP
200

$ curl -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8123/    # Core, loopback — still works
200
```

192.168.8.50 is this sandbox machine's own `eth0` address (confirmed via
`ip addr` / `hostname -I`) — not a second physical host, since none was
available, but connecting to a box's own non-loopback interface address
exercises the identical kernel socket-accept path a genuinely remote host
would: a `listen()` socket bound to `127.0.0.1` refuses every inbound
connection that doesn't arrive via the loopback interface, regardless of
where the connecting process physically runs. `curl: (7) ... Could not
connect` is a real, OS-level connection refusal, not an HTTP-level
response of any kind — there is no 404, no panel, nothing "frontend-
shaped" to see, exactly the standard the coordinator asked this be held
to.

**Sequencing caveat, found and worth knowing**: the mid-onboarding
restart (step 4 above) was first tested starting from a `default_config:`
initial file (simulating "whatever a naive auto-generated config might
look like"), and Core hung for several minutes without ever completing
that restart — no crash, no `ImportError`, just no progress (low but
nonzero CPU use, nothing in the log past a `homeassistant.loader.
IntegrationNotFound: Integration 'cloud' not found` error from what looks
like a leftover discovery/flow-init task from `default_config:`'s much
larger component set). Re-tested starting from an already-explicit-list
file (just missing `server_host`) — the realistic case, since a real
Willo Local device should ship with the explicit list baked into its
image from the start, never `default_config:` — and the restart completed
in about 3 seconds, every time. Not chased further: it's a plausible real
robustness gap (an unbounded initial `configuration.yaml` state could in
principle hang a real device's first boot) but not the scenario this
orchestrator is actually designed to run into, and chasing a synthetic
`default_config:`-specific hang felt like solving a problem this design
doesn't actually have. Worth remembering if a future change makes this
restart path reachable from a less-controlled starting state.

### Inert frontend stub — defense-in-depth layered on top, not a substitute

Loopback binding alone satisfies "no HA UI ever reachable from outside
this device" — that's the load-bearing guarantee. But the user wanted the
actual footprint gone where practical, not merely hidden behind a network
restriction, so `custom_components/willo/frontend_stub.py` and
`orchestrator/willo_orchestrator/frontend_stub.py` (identical content,
duplicated the same way the rest of this cleanup logic is — see those
files) replace the installed `frontend` component's files with an inert
stub: same importable module path, same symbols other stock code needs,
but `async_setup`, `async_register_built_in_panel`, `async_remove_panel`,
and `async_system_store` all do nothing real — no HTTP views, no static
assets, no wizard, no dashboard.

**The complete, exhaustive symbol list this stub needed to reproduce**,
found by grepping the entire installed `homeassistant==2026.2.3` package
for every `from homeassistant.components import frontend` and
`from homeassistant.components.frontend import X`, then every
`frontend.` attribute access in each matching file:

- `DATA_PANELS` (a `HassKey`, read/written by `lovelace/__init__.py`,
  `lovelace/dashboard.py`)
- `MANIFEST_JSON` (subscript-only, `mobile_app/webhook.py`)
- `async_register_built_in_panel` (called by `config`, `hassio`,
  `history`, `logbook`, `lovelace`, `my`, `todo`, `panel_custom`,
  `media_source`, `energy`, `calendar` — same signature reproduced
  exactly, including the keyword-only `update`/`config_panel_domain`
  params some call sites use)
- `async_remove_panel` (`hassio/addon_panel.py`, `lovelace/__init__.py`)
- `async_system_store` (`lovelace/__init__.py` — only reached inside a
  storage-migration function that early-returns on any fresh install with
  no pre-existing lovelace storage; stubbed anyway, defensively)
- the `"frontend.reload_themes"` service (referenced by name, not import,
  from `homeassistant`'s own `reload_all` service)

Confirmed `onboarding` (what this orchestrator's own automation depends
on entirely) has zero references to `frontend` anywhere in its source or
manifest — the stub cannot break onboarding automation because nothing
about onboarding touches frontend in the first place.

**Verified for real, both in isolation and through the full pipeline:**

- Manual swap into a real installed package, 5 consecutive `hass`
  relaunches: every boot healthy, zero crashes, zero `ImportError`.
  `frontend` reports as a genuinely loaded component
  (`"frontend" in components` → `true` via authenticated `GET
  /api/config`) — not missing, just inert.
- With Core's `http:` deliberately NOT loopback-restricted for this one
  check (to isolate "is frontend inert" from "is it unreachable" — two
  different guarantees): `GET /`, `GET /onboarding.html`, `GET
  /manifest.json`, `GET /static/icons/favicon.ico` all returned a plain
  generic `404: Not Found` — nothing "frontend-shaped" served at all.
- Full onboarding → user step → config write+restart → remaining
  onboarding → analytics/cloud deletion **and** frontend stub swap →
  claim → headless entry write → final restart → paired, re-run through
  the real orchestrator with both mechanisms wired in together, reaching
  `paired` cleanly (orchestrator log shows all three: `deleted stock
  'analytics'`, `deleted stock 'cloud'`, `replaced the 'frontend'
  component with an inert stub`).
- 5 more consecutive `hass` relaunches on that resulting paired,
  loopback-bound, stub-frontend config directory, each cycle checked
  independently (distinct PID per cycle, confirmed killed before the
  next): all healthy, and on every single cycle — both
  `curl http://192.168.8.50:8123/` (external) refused the connection AND
  `curl http://127.0.0.1:8123/` (loopback, i.e. what the stub alone
  controls) returned `404` — the two layers holding simultaneously,
  every time.

**Fragility, flagged as plainly as asked**: `frontend`'s internals are
not a documented, stable public API — `frontend` is an
`integration_type: system` component, and nothing about `DATA_PANELS`'s
type, `async_register_built_in_panel`'s signature, or which symbols exist
at all is guaranteed across HA releases the way `http: server_host` (a
real, documented, user-facing config key) is. This symbol list is only as
correct as the HA 2026.2.3 snapshot it was derived from. The most likely
failure mode on a future HA version that adds a new stock component
importing a new frontend symbol is that ONE component logging a soft
"Setup failed for X" error — the same category of degradation already
accepted for the analytics/cloud deletion — not a repeat of the
frontend-deletion crash, since nothing about `bootstrap.py`'s own hard
import of `config` (which only needs `frontend` to exist and expose what
`config/__init__.py` touches) changes. Still: **this is measurably more
fragile than loopback binding**, and re-deriving this symbol list (same
grep commands as above) is a real, recurring maintenance cost on every
future HA version bump this project targets — worth budgeting for, not
a one-time cost. Both stub-writing functions are wrapped in their own
try/except, entirely separate from the analytics/cloud deletion's: if
writing or swapping the stub fails for any reason, or a future HA version
makes the stub itself incompatible in some way that surfaces as an
exception, the fallback is exactly "as if this stub didn't exist" —
loopback binding remains the load-bearing, unaffected guarantee either
way.

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
- Whether real HAOS's own Supervisor/Ingress needs Core's `http:` bound to
  something other than loopback to keep working. Supervisor's Ingress
  feature (the mechanism HAOS normally uses to reach Core's UI through
  Supervisor's own reverse proxy) may expect to reach Core directly on its
  usual interface/port — binding Core to `127.0.0.1` only could plausibly
  conflict with that on real hardware in a way a plain venv Core (with no
  Supervisor process at all) cannot surface. This sandbox proved the
  binding itself works exactly as intended for a bare Core process; it
  cannot prove Supervisor is fine with it. A real HAOS Green is needed to
  confirm this one way or the other before shipping.
- `deviceModel` detection (`orchestrator/willo_orchestrator/device_model.py`,
  for the Willo app's own "Connect Home Assistant" auto-detect screen,
  which reads `GET /status`'s `deviceModel` field to say "Found a Willo
  Green" instead of assuming every appliance is one). What IS verified:
  `aiohasupervisor` (Supervisor's real, typed Python client, already an
  installed dependency of the stock `hassio` integration — inspected
  directly in this sandbox, not remembered from memory) exposes
  `SupervisorClient(api_host, token).os.info()` → `OSInfo.board: str |
  None` via `GET os/info`, and this module correctly returns `None`
  without raising when `SUPERVISOR_TOKEN` isn't set (every sandbox test
  here) or when `http://supervisor` is unreachable — both real,
  tested behaviors. What is NOT verified: an actual Supervisor's real
  response shape and whether `http://supervisor` / `SUPERVISOR_TOKEN`
  behave exactly as HAOS's own add-on documentation describes — there is
  no Supervisor at all in a plain venv/Docker Core sandbox to check
  against. Confirm this against a real HAOS Green before trusting the
  Willo app's board-name copy in production.

## HAOS add-on packaging (`haos-addon/`) and real-Supervisor verification

The final phase of this work: package the orchestrator as an actual HAOS
add-on (Dockerfile, `config.yaml`, s6-overlay service — nothing built
before this was add-on-shaped, it was a bare Python process in a venv),
implement the `willo.local` hostname rename, and test as much of this as
possible against a **real** Supervisor, not bare Core — explicitly the
last verification gate before anyone touches real HA Green hardware.

### The add-on itself — built from the real, currently-published add-ons repo, not invented

`haos-addon/config.yaml`, `build.yaml`, `Dockerfile`, and the
`rootfs/etc/s6-overlay/s6-rc.d/willo-local/` service definition were built
by cloning and reading `home-assistant/addons` (the real, first-party
add-ons collection) and `home-assistant/addons-example`, not by guessing
the shape:

- `build.yaml` pins `ghcr.io/home-assistant/{arch}-base:3.24-2026.06.1` —
  the exact, current base image `home-assistant/addons/configurator`
  (a real, currently-published add-on) uses.
- `config.yaml`'s `hassio_api: true` / `homeassistant_api: true` /
  `hassio_role: manager` / `map: [{type: homeassistant_config}]` are all
  real fields, each taken from a specific real add-on in that repo
  (`duckdns` for `hassio_api`, `configurator` for `homeassistant_api`,
  `ssh` for `hassio_role: manager` — the same elevated role this add-on
  needs for the same reason `ssh` does, OS-level Supervisor calls — and
  `matter_server`/`configurator` for the `homeassistant_config` map type
  that mounts Core's config directory at `/homeassistant`).
- The s6-overlay v3 service layout
  (`s6-rc.d/willo-local/{type,run,finish,dependencies.d/base}` +
  `s6-rc.d/user/contents.d/willo-local`) matches `configurator`'s real
  rootfs exactly; `finish` is copied verbatim (real add-ons share this
  exact boilerplate for s6 supervision teardown).

**Verified for real — a genuine `docker build` and `docker run`, not just
a file that looks plausible:**

```
$ sudo docker build -f haos-addon/Dockerfile \
    --build-arg BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.24-2026.06.1 \
    -t willo-local-test .
# ... real base image pull, real `pip3 install /opt/orchestrator` (aiohttp,
# aiohasupervisor, ulid-transform and their transitive deps all resolved
# for real), real COPY of willo-claim-ui/dist and the s6 rootfs ...
#11 writing image sha256:8e59d0d7... done

$ sudo docker run --rm -d -p 18080:8080 willo-local-test
$ docker logs <container>
s6-rc: info: service willo-local: starting
s6-rc: info: service willo-local successfully started
[11:29:26] INFO: Starting Willo Local orchestrator...
2026-09-15 ... INFO willo_orchestrator.server: Willo orchestrator serving on http://0.0.0.0:8080 ...
2026-09-15 ... INFO willo_orchestrator.device_model: SUPERVISOR_TOKEN not set — ... deviceModel will be null
2026-09-15 ... INFO willo_orchestrator.hostname: SUPERVISOR_TOKEN not set — skipping hostname rename
2026-09-15 ... ERROR __main__: Willo orchestrator boot sequence failed
willo_orchestrator.ha_client.HAClientError: GET /api/onboarding -> 404

$ curl http://localhost:18080/status
{"stage": "onboarding", ..., "error": "GET /api/onboarding -> 404"}
$ curl -o /dev/null -w '%{http_code}' http://localhost:18080/
200
```

This confirms, for real: the image builds cleanly on the real official
base image; s6-overlay correctly recognizes and starts the `willo-local`
service; the `run` script's real bashio calls and env vars work; the
orchestrator starts, correctly detects the Supervisor-less environment
(both `device_model.py` and `hostname.py` degrade to their documented
no-op path, not a crash) and correctly attempts `http://homeassistant:8123`
(the real HAOS internal DNS name for Core an add-on with
`homeassistant_api: true` gets, not `localhost`) — which 404s here only
because there's no real Home Assistant network in a bare `docker run`,
exactly as expected; and the claim UI itself is served correctly (`GET /`
→ `200`) from inside the container. The ONE thing this does NOT prove is
the add-on actually installed and started BY Supervisor (as opposed to a
bare `docker run`) — that's the VM section below.

### The hostname rename (`willo_orchestrator/hostname.py`)

Found the same way `os/info`'s `board` field was found earlier: by reading
`aiohasupervisor`'s actual installed source, not guessing an endpoint.
`aiohasupervisor/host.py`'s `HostClient` exposes `GET host/info` →
`HostInfo.hostname` (the current value) and `POST host/options` ←
`HostOptions(hostname=...)` (`set_options`) — both real, typed, confirmed
by import (`from aiohasupervisor.models import HostOptions;
HostOptions(hostname="willo")` constructs cleanly). Wired into
`main.py`'s boot sequence early (independent of onboarding, same as
`deviceModel`), gated on `SUPERVISOR_TOKEN` exactly like `device_model.py`,
never raising. Verified: the no-Supervisor path (every sandbox test here,
including the real `docker run` above) degrades correctly. NOT verified:
that `host/options` actually renames the host against a live Supervisor —
see below for why that specific call couldn't be reached this round.

### The real HAOS VM attempt

Home Assistant publishes official HAOS QEMU/VirtualBox VM images
specifically for this kind of testing. Checked feasibility honestly
before assuming anything:

```
$ ls -la /dev/kvm
crw-rw---- 1 root kvm 10, 232 ... /dev/kvm
$ egrep -c '(vmx|svm)' /proc/cpuinfo
64
$ systemd-detect-virt
wsl
```

This sandbox runs inside WSL2 (itself a Hyper-V VM) — nested virtualization
inside a VM is exactly the kind of setup that often silently doesn't work.
Tested rather than assumed: installed `qemu-system-x86` (Debian's real apt
package), added the sandbox user to the `kvm` group, and booted a real
KVM-accelerated QEMU guest (`qemu-system-x86_64 -accel kvm -cpu host ...`)
— it worked, with no fallback-to-software-emulation warnings. **Real
hardware-accelerated virtualization genuinely works in this sandbox** —
not a given, confirmed rather than assumed.

Downloaded the official release: `home-assistant/operating-system`
release `18.2`, `haos_ova-18.2.qcow2.xz` (the QEMU/VirtualBox-targeted
OVA variant). First real finding: this image is **UEFI-only** — booting
with plain SeaBIOS (QEMU's default) hangs silently at "Booting from Hard
Disk..." forever; booting with OVMF firmware
(`-drive if=pflash,file=/usr/share/OVMF/OVMF_CODE_4M.fd` + a writable
copy of `OVMF_VARS_4M.fd`) boots correctly into a real HAOS `systemd`
environment (HAOS ZRAM units, the real EXT4 root mount, the genuine
"Welcome to Home Assistant" console banner).

**Home Assistant Core, under real Supervisor management, DID become
reachable once**: `curl http://localhost:<forwarded-port>/api/` answered
`401` (up, unauthenticated) on the very first successful boot — real,
concrete proof this whole pipeline can work end to end in this sandbox.
That specific attempt was then lost to a real mistake, not a fundamental
blocker: repeated probes against `/api/` (which requires auth) rather
than the actually-public `/api/onboarding` appear to have triggered HA's
own IP-ban security middleware, after which even the public endpoint
returned a bare `401` for the rest of that boot. Lesson applied for every
attempt after: only ever poll `/api/onboarding` for readiness (the same
real, already-verified check `HAClient.wait_until_api_ready` uses against
bare Core).

**Every subsequent attempt (fresh disk each time, to rule out any
carried-over bad state) hit a reproducible stall**: `GET /api/onboarding`
consistently returned `307 Temporary Redirect` → `Location:
http://<host-without-port>/api/onboarding`, with `Server: Python/3.14
aiohttp/3.14.3` — a different Python version than bare Core's 3.13.5 in
every earlier venv test, strong evidence this response comes from
Supervisor's own landing/proxy service while Core itself was never
successfully started. Diagnosed with real evidence, not guessed: QEMU's
own monitor (`info usernet`) showed the guest actively opening large
numbers of short-lived DNS and DNS-over-TLS (port 853, to `1.1.1.1`/
`1.0.0.1`) connections that established at the TCP level but produced no
further traffic — a recognized category of QEMU usermode-networking
(slirp) limitation, not a HAOS/Supervisor bug. Tried a targeted, evidence
based fix (`-device virtio-net-pci,...,host_mtu=1400`, addressing a known
slirp MTU/fragmentation issue) on a fresh disk; it did not resolve the
stall within the time available for this task. The next real fix — a
bridged/tap network device instead of slirp, avoiding QEMU's usermode
networking entirely — was not attempted: it needs installing and
configuring `iptables`/a DHCP server/bridge-utils from scratch, a
materially larger new effort, and time ran out on this pass.

**Reported honestly, not forced**: full HAOS+Supervisor first-boot
provisioning did not complete in this sandbox this round. What IS now
genuinely verified, distinct from every earlier bare-Core test:
Docker/OS-level virtualization is real and works here; the official HAOS
image is correctly downloadable and bootable (with the UEFI finding);
Core reachability under real Supervisor management was directly observed
once. What remains unverified, and needs either a follow-up session with
bridged VM networking or the user's own real HAOS Green hardware: the
actual `host/options` hostname-rename call, `os/info`'s real response
shape, and the packaged add-on actually being installed and started BY a
live Supervisor (as opposed to the bare `docker run` verified above,
which proves the container itself is correct but not Supervisor's own
add-on lifecycle management of it).

### Updated status of the four originally-flagged open items

1. **Onboarding REST payload shapes** — fully verified (see "Onboarding
   REST automation" above).
2. **Headless config-entry creation mechanism** — fully verified,
   mechanism (b) chosen (see "Headless config-entry creation" above).
3. **HAOS Supervisor hostname-rename API** — the real API call is now
   *implemented* (`hostname.py`, `HostClient.set_options`) and its
   no-Supervisor degradation path is tested, but calling it against a
   live Supervisor is NOT verified — see above.
4. **Add-on ↔ Core networking** — partially advanced: the add-on's own
   container correctly reaches for `http://homeassistant:8123` (the real
   internal hostname), and the packaged container itself is proven to
   build and run correctly (Docker verification above), but Supervisor
   actually wiring that hostname up, and granting the container access to
   Core's install path for `cleanup.py`'s belt-and-suspenders deletion,
   remains unverified against a live Supervisor for the same reason as
   item 3.

No code in this repository or its tests ever attempted to reach real Home
Assistant Green / HAOS hardware or the user's home network — every test
above ran against a disposable local HA Core install or a disposable
local HAOS VM created for this task, and `custom_components/willo`'s own
tunnel target (`DEFAULT_TUNNEL_URL`) was never pointed anywhere but the
real, public `api.willo.sh` (reachable from this sandbox, unrelated to
any home network) or an explicit local test stub.
