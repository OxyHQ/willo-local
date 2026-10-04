# willo-claim-ui

The single-screen status/claim UI for Willo Local (see
[OxyHQ/Willo issue #9](https://github.com/OxyHQ/Willo/issues/9) and this
repo's top-level README). Polls the on-device orchestrator's local
`GET /status` roughly once a second and renders the current boot stage —
onboarding, syncing, a claim code + QR once one's generated, then a paired
state. No routing, no state management library: one screen, driven
entirely by that poll.

Standalone Vite + React + TypeScript project — own `package.json`, not
part of the Willo monorepo's workspaces (no reason to share tooling with
an Expo app for a static status screen).

UI is [Bloom](https://www.npmjs.com/package/@oxy.so/bloom) used directly, the
way Bloom documents for a Vite web app: react-native-web via
`vite-plugin-react-native-web`, Tailwind v4 importing Bloom's `theme.css` and
`@source`-scanning its `lib/`, and `BloomProvider` configured with Willo's seed
colours in `src/main.tsx`. Colours are resolved by Bloom at runtime — there is
no app-side theme file.

## Develop

```
bun install
bun dev
```

## Build

```
bun run build
```

Produces `dist/`, which `orchestrator/willo_orchestrator/server.py` serves
directly (see `WILLO_STATIC_DIR` in that package's README section) — build
this before running the orchestrator, or `/status` will still work but
every other path will 404.
