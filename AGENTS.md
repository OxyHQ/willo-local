# Willo Local

Home Assistant integration for Willo (`custom_components/willo`, installed through HACS), plus the on-device onboarding orchestrator and its claim UI for factory-provisioned devices.

## Commands

```bash
uv venv --python 3.14 && uv pip install -r requirements-test.txt   # as CI does
uv run --no-project python -m pytest tests -q                      # integration tests
pip install -e "orchestrator[test]" && pytest orchestrator/tests   # orchestrator tests
bun install                      # pinned Bun is in package.json "packageManager"
bunx biome ci .                  # lint and format check (CI)
bun run --cwd willo-claim-ui build   # claim UI; the orchestrator serves its dist/
```

## Map

- `custom_components/willo`: the integration. Its `__init__.py` module doc comment is the wire protocol to the Willo backend (`packages/backend/src/realtime/tunnelNamespace.ts` in [OxyHQ/Willo](https://github.com/OxyHQ/Willo)).
- `orchestrator/willo_orchestrator`: on-device process (onboarding, cleanup, claim, `GET /status`). `willo-claim-ui`: Vite status screen. `haos-addon`: add-on packaging.
- Design notes, the verified-how and open items for Willo Local are in [README.md](./README.md).

## Conventions that differ from defaults

- The `willo` integration never modifies the Home Assistant installation it runs in (no deleting components, no config edits): it also runs on people's own instances. `tests/test_setup_leaves_ha_alone.py` guards this.
- The orchestrator never deletes the `frontend` component; the README section "Cleanup deletion" explains why. Read it before editing `orchestrator/willo_orchestrator/cleanup.py`.
- Tests use a real in-process Home Assistant (`pytest-homeassistant-custom-component`), not a mock of HA. Bump that pin only together with the Home Assistant release Willo supports.
- The integration opens one outbound connection; never add inbound ports, URLs or certificates for users to configure.
- First-party never asks people for permissions: this app acts for a person with `actingFor` on what oxy's first-party registry declares (oxy ADR 0066); permissions, scopes and consent are only for third parties.
- Biome (`bunx biome ci .`) checks the claim UI; general Oxy rules: [engineering standards](https://github.com/OxyHQ/engineering/blob/main/AGENTS.md).

## Boundaries

- Never make the claim UI server or `GET /status` depend on later onboarding stages: they must keep serving independently (README "Cleanup deletion").
- Ask first before changing the pairing/claim protocol: it must stay in step with `OxyHQ/Willo`'s `/tunnel/claim` endpoints.
- Never test against a real user's Home Assistant; use a disposable instance and a fresh config directory.

## Testing

- Integration or orchestrator change: run the matching pytest suite above. Claim UI change: `bunx biome ci .` and `bun run --cwd willo-claim-ui build`.
- Done means the same checks CI runs (`tests.yml`, `lint.yml`) pass.

## Pull requests

- Imperative commit messages that say why; one logical change per commit; PR body says what, why and how tested. Branch from `origin/main`; `main` requires the `protect` ruleset checks. Never force-push a shared branch.

## Secrets

- Pairing codes and tunnel secrets are never logged or committed; the orchestrator writes them only to Home Assistant's `.storage` on the device.

## Links

- [Oxy engineering standards](https://github.com/OxyHQ/engineering/blob/main/AGENTS.md)
- [Lint and format](https://github.com/OxyHQ/oxy/blob/main/docs/engineering/lint-and-format.md)
- [Willo app and backend](https://github.com/OxyHQ/Willo)

Owner: Nate Isern. Last reviewed: 2026-11-11.
