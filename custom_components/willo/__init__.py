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

WHAT THIS NEVER DOES: modify the Home Assistant installation it runs in.
It is installed on people's own Home Assistant instances, not only on Willo
Local devices, so it must not delete or replace stock components. Earlier
versions deleted `analytics`/`cloud` and swapped `frontend` for a stub on
every boot; on a normal install that breaks `default_config` (it hard-depends
on `cloud`) and leaves the owner without a UI. Neither was needed. `cloud` is
only loaded when the configuration asks for it, and Willo Local's explicit
allow-list never does. `analytics` sends nothing unless its preferences are
turned on. What keeps Core unreachable from the network on Willo Local is
loopback binding (`http.server_host: 127.0.0.1`), which the orchestrator
writes.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

import socketio
from homeassistant.components.camera import async_get_image
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er

from .const import CONF_HOME_ID, CONF_SECRET, DEFAULT_TUNNEL_URL, DOMAIN, TUNNEL_NAMESPACE

_LOGGER = logging.getLogger(__name__)

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

    # entity_id -> room, cached and rebuilt only after the entity/device/area
    # registries change. Building it walks the whole entity registry, and
    # state_changed fires many times a second on a busy instance (BLE
    # trackers, power meters), so rebuilding it per event was pure waste.
    room_index: dict[str, str | None] | None = None

    @callback
    def _invalidate_room_index(_event: Event) -> None:
        nonlocal room_index
        room_index = None

    def _cached_room_index() -> dict[str, str | None]:
        nonlocal room_index
        if room_index is None:
            room_index = _build_room_index(hass)
        return room_index

    async def _on_state_changed(event: Event) -> None:
        new_state: State | None = event.data.get("new_state")
        if new_state is None or _domain_of(new_state.entity_id) not in _SUPPORTED_DOMAINS:
            return
        # While the tunnel is down (Willo's backend unreachable, or mid-
        # reconnect) there is nobody to send this to: emitting raised
        # BadNamespaceError on EVERY state change, flooding HA's log. Nothing
        # is lost by dropping it — _on_connect sends a full state_snapshot
        # as soon as the tunnel is back.
        if TUNNEL_NAMESPACE not in sio.namespaces:
            return
        device = _to_device(new_state, _cached_room_index())
        if device is None:
            return
        try:
            await sio.emit("state_changed", device, namespace=TUNNEL_NAMESPACE)
        except socketio.exceptions.BadNamespaceError:
            # Disconnected between the check above and this emit — same as above.
            return

    unsubscribers = [
        hass.bus.async_listen(EVENT_STATE_CHANGED, _on_state_changed),
        hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, _invalidate_room_index),
        hass.bus.async_listen(dr.EVENT_DEVICE_REGISTRY_UPDATED, _invalidate_room_index),
        hass.bus.async_listen(ar.EVENT_AREA_REGISTRY_UPDATED, _invalidate_room_index),
    ]

    def remove_listener() -> None:
        for unsubscribe in unsubscribers:
            unsubscribe()

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
