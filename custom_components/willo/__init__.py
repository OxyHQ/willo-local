"""Willo — a persistent OUTBOUND tunnel from this Home Assistant instance to
Willo's backend, so Willo's web app never has to reach this instance
directly.

WHY THIS EXISTS: a browser served over HTTPS (willo.sh) cannot open a plain
HTTP or `ws://` connection to a Home Assistant instance — browsers block
that unconditionally (Mixed Content), and the median self-hosted HA install
(especially the Home Assistant Green hardware Willo pairs with) has no TLS
certificate, no port-forwarding, and no static IP. Rather than ask a
non-technical person to solve any of that, this integration opens the
connection itself, in the one direction that needs zero home-network
configuration: outbound. Willo's backend then relays browser requests over
it — see OxyHQ/Willo's `packages/backend/src/realtime/tunnelNamespace.ts`
for the other end of this exact protocol.

WHAT THIS SENDS: `state_snapshot` (every light/fan/sensor/camera/binary_sensor
entity, on connect/reconnect) and `state_changed` (one entity, on every HA
state change) — both already shaped as Willo's own `Device` JSON, not raw HA
entity dumps, so the translation lives here, in ONE place, instead of
duplicated between this integration and Willo's frontend. This intentionally
mirrors `packages/frontend/providers/home-assistant.ts`'s OLD
`capabilitiesFor`/`toDevice` logic — that file no longer exists in Willo
(the browser doesn't talk to HA anymore), but the domain-translation RULES
it used are reproduced here byte-for-byte, because the frontend still
expects exactly that JSON shape. `binary_sensor` is the one addition beyond
that old logic: Willo's backend turns its `state_changed` transitions into
`/activity`'s real event history (motion/door/safety sensors) — see
OxyHQ/Willo's `packages/backend/src/services/homeEvents.service.ts`.

WHAT THIS RECEIVES: `call_service` (fire-and-forget, matching how Willo's
own UI has always issued commands — no request/response round trip) and
`request_camera_snapshot` (the one exception: a real request/response, since
a camera card is asking a direct question).
"""

from __future__ import annotations

import base64
import importlib.util
import logging
import shutil
from pathlib import Path
from typing import Any

import socketio
from homeassistant.components.camera import async_get_image
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Event, HomeAssistant, State
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er

from .const import CONF_HOME_ID, CONF_SECRET, DEFAULT_TUNNEL_URL, DOMAIN, TUNNEL_NAMESPACE

_LOGGER = logging.getLogger(__name__)

# Willo Local (see OxyHQ/Willo issue #9): the device itself must never show
# Home Assistant's own UI or branding. Rather than fork Core or ship a
# patched OS image, this integration physically deletes these stock
# components from the installed `homeassistant` package on every boot —
# self-healing against a Core update that restores them. Tested against a
# real `homeassistant` pip install to confirm nothing else in stock Core
# imports from `analytics`/`cloud` at import time in a way that would break
# (see this repo's README for the exact command and findings); if a future
# HA version changes that, `_delete_stock_components` below still can't
# crash setup — it only ever logs and moves on.
#
# `frontend` is DELIBERATELY EXCLUDED from this list — do not add it back.
# Deleting `frontend` was tried and reverted after real testing: HA's own
# `homeassistant/bootstrap.py` unconditionally imports `homeassistant.
# components.config` at module level (a performance pre-import, nothing to
# do with configuration.yaml), and `config/__init__.py` imports `frontend`
# at ITS top level — so once `frontend`'s files are gone, the very next
# `hass` process launch crashes outright with `ImportError: cannot import
# name 'frontend' from 'homeassistant.components'`, before Core's own
# recovery-mode logic can even run. This was proven twice: manually, and
# through a full onboarding→cleanup→claim→pair→restart run whose next
# `hass` launch crashed with that exact traceback (see this repo's README,
# "Cleanup deletion" section). Excluding `frontend` from
# `configuration.yaml` does NOT avoid this either and does not even stop
# `frontend` from running — HA's `bootstrap._get_domains()` unconditionally
# merges `DEFAULT_INTEGRATIONS` (which includes `"frontend"`) into every
# non-recovery-mode boot regardless of `configuration.yaml`'s content, and
# recovery mode force-includes `frontend` too — confirmed by booting HA
# with `frontend:` absent from an explicit `configuration.yaml` and
# getting a real `302 → /onboarding.html` serving HA's actual onboarding
# wizard HTML anyway. See the README for the full writeup and the
# network-level mitigation (binding Core's own `http:` to loopback only)
# that was verified to actually achieve "unreachable from outside this
# device" instead — not yet wired into this integration pending a design
# decision, since it changes configuration.yaml, not this file.
_STOCK_COMPONENTS_TO_REMOVE = ("analytics", "cloud")


def _delete_stock_components() -> None:
    """Delete analytics/ and cloud/ from the installed homeassistant
    package so this device never phones home to Nabu Casa's cloud
    services or Home Assistant's own analytics collection — even after a
    Core update restores them, since this runs on every boot. (`frontend`
    is NOT deleted here — see the module-level comment on
    `_STOCK_COMPONENTS_TO_REMOVE` above for why, and this repo's README
    for the underlying finding.)

    The install path is resolved via `importlib`, never hardcoded, so this
    survives HA version bumps that change the install layout (venv vs.
    system site-packages vs. HAOS's container layout).

    This function must NEVER raise. A missing directory (already deleted,
    or a future HA release renaming/removing the component), a permission
    error, or any other failure is logged as a warning and skipped — this
    is defense-in-depth, not a precondition for the tunnel itself working,
    and must never block integration setup.
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
        for component_name in _STOCK_COMPONENTS_TO_REMOVE:
            component_dir = components_dir / component_name
            try:
                if component_dir.is_dir():
                    shutil.rmtree(component_dir)
                    _LOGGER.info("Willo: deleted stock '%s' component at %s", component_name, component_dir)
            except OSError:
                _LOGGER.warning(
                    "Willo: failed to delete stock '%s' component at %s — leaving it in place",
                    component_name,
                    component_dir,
                    exc_info=True,
                )

# The domains Willo's UI knows how to render. An entity in any other domain
# (automations, scripts, switches, climate, …) is dropped, not sent with
# empty capabilities — curation is "which domains", decided once, here.
# `binary_sensor` is the one domain beyond the original set (light/fan/
# sensor/camera, matching the OLD frontend behaviour exactly) — it feeds
# `/activity`'s real event history, not a device tile.
_SUPPORTED_DOMAINS = {"light", "fan", "sensor", "camera", "binary_sensor"}


def _domain_of(entity_id: str) -> str:
    return entity_id.split(".")[0]


def _capabilities_for(state: State) -> list[dict[str, Any]] | None:
    domain = _domain_of(state.entity_id)

    if domain == "light":
        brightness = state.attributes.get("brightness")
        rgb = state.attributes.get("rgb_color")
        return [
            {"kind": "onOff", "on": state.state == "on"},
            {"kind": "brightness", "percent": round((brightness / 255) * 100) if brightness is not None else None},
            {"kind": "color", "color": f"rgb({rgb[0]}, {rgb[1]}, {rgb[2]})" if rgb else None},
        ]
    if domain == "fan":
        return [
            {"kind": "onOff", "on": state.state == "on"},
            {"kind": "fanSpeed", "percent": state.attributes.get("percentage")},
        ]
    if domain == "sensor":
        value: float | None = None
        if state.state not in ("unknown", "unavailable"):
            try:
                value = float(state.state)
            except ValueError:
                value = None
        return [
            {
                "kind": "measurement",
                "value": value,
                "unit": state.attributes.get("unit_of_measurement"),
                "deviceClass": state.attributes.get("device_class"),
            }
        ]
    if domain == "camera":
        # `snapshotUrl` is filled in on the FRONTEND (`providers/willo-tunnel.ts`),
        # which is the one place that knows Willo's own backend host — this
        # integration has no reason to know it and never sets it.
        return [{"kind": "camera", "snapshotUrl": None}]
    if domain == "binary_sensor":
        return [
            {
                "kind": "binarySensor",
                "active": state.state == "on",
                "deviceClass": state.attributes.get("device_class"),
            }
        ]
    return None


def _build_room_index(hass: HomeAssistant) -> dict[str, str | None]:
    """entity_id -> area name, resolving an entity's own area first, then its device's — the same two-step fallback the old frontend WebSocket code used."""
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    area_registry = ar.async_get(hass)

    room_by_entity_id: dict[str, str | None] = {}
    for entity in entity_registry.entities.values():
        area_id = entity.area_id
        if area_id is None and entity.device_id:
            device = device_registry.async_get(entity.device_id)
            area_id = device.area_id if device else None
        area = area_registry.async_get_area(area_id) if area_id else None
        room_by_entity_id[entity.entity_id] = area.name if area else None
    return room_by_entity_id


def _to_device(state: State, room_by_entity_id: dict[str, str | None]) -> dict[str, Any] | None:
    capabilities = _capabilities_for(state)
    if capabilities is None:
        return None
    return {
        "id": state.entity_id,
        "name": state.attributes.get("friendly_name", state.entity_id),
        "room": room_by_entity_id.get(state.entity_id),
        "domain": _domain_of(state.entity_id),
        "capabilities": capabilities,
    }


def _snapshot_devices(hass: HomeAssistant) -> list[dict[str, Any]]:
    room_by_entity_id = _build_room_index(hass)
    devices = []
    for state in hass.states.async_all():
        device = _to_device(state, room_by_entity_id)
        if device is not None:
            devices.append(device)
    return devices


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # Runs unconditionally, before anything else, on every single boot —
    # see _delete_stock_components' doc comment above.
    await hass.async_add_executor_job(_delete_stock_components)

    home_id: str = entry.data[CONF_HOME_ID]
    secret: str = entry.data[CONF_SECRET]
    tunnel_url: str = entry.options.get("tunnel_url", DEFAULT_TUNNEL_URL)

    sio = socketio.AsyncClient(reconnection=True, reconnection_delay=2, reconnection_delay_max=30)

    @sio.on("connect", namespace=TUNNEL_NAMESPACE)
    async def _on_connect() -> None:
        _LOGGER.info("Willo tunnel connected for Home %s", home_id)
        await sio.emit("state_snapshot", _snapshot_devices(hass), namespace=TUNNEL_NAMESPACE)

    @sio.on("disconnect", namespace=TUNNEL_NAMESPACE)
    async def _on_disconnect() -> None:
        _LOGGER.warning("Willo tunnel disconnected for Home %s — reconnecting", home_id)

    @sio.on("call_service", namespace=TUNNEL_NAMESPACE)
    async def _on_call_service(message: dict[str, Any]) -> None:
        try:
            await hass.services.async_call(
                message["domain"],
                message["service"],
                {"entity_id": message["entityId"], **message.get("serviceData", {})},
                blocking=False,
            )
        except Exception:  # noqa: BLE001 - a bad/unsupported command must not kill the tunnel connection
            _LOGGER.exception("Failed to execute a command Willo relayed for Home %s", home_id)

    @sio.on("request_camera_snapshot", namespace=TUNNEL_NAMESPACE)
    async def _on_request_camera_snapshot(message: dict[str, Any]) -> None:
        request_id = message.get("requestId")
        entity_id = message.get("entityId")
        image_base64 = ""
        try:
            image = await async_get_image(hass, entity_id)
            image_base64 = base64.b64encode(image.content).decode("ascii")
        except Exception:  # noqa: BLE001 - Willo's own request times out on a missing/empty response; this must not crash the tunnel
            _LOGGER.exception("Failed to capture a camera snapshot for %s", entity_id)
        await sio.emit("camera_snapshot_result", {"requestId": request_id, "imageBase64": image_base64}, namespace=TUNNEL_NAMESPACE)

    async def _on_state_changed(event: Event) -> None:
        new_state: State | None = event.data.get("new_state")
        if new_state is None or _domain_of(new_state.entity_id) not in _SUPPORTED_DOMAINS:
            return
        device = _to_device(new_state, _build_room_index(hass))
        if device is not None:
            await sio.emit("state_changed", device, namespace=TUNNEL_NAMESPACE)

    remove_listener = hass.bus.async_listen(EVENT_STATE_CHANGED, _on_state_changed)

    try:
        await sio.connect(
            tunnel_url,
            namespaces=[TUNNEL_NAMESPACE],
            auth={"homeId": home_id, "secret": secret},
            transports=["websocket"],
        )
    except socketio.exceptions.ConnectionError as error:
        remove_listener()
        raise ConfigEntryNotReady(f"Could not reach Willo's tunnel at {tunnel_url}") from error

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"sio": sio, "remove_listener": remove_listener}
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if data:
        data["remove_listener"]()
        await data["sio"].disconnect()
    return True
