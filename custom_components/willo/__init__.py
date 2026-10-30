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

WHAT THIS SENDS: `state_snapshot` (every light/fan/sensor/camera/binary_sensor/
media_player/weather entity, on connect/reconnect) and `state_changed` (one entity, on every HA
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
`media_player` and `weather` feed Frame by Willo's music and weather cards.
A player's artwork URL never leaves this instance (Home Assistant's proxy URL
carries an access token): only a hash of it travels, as `artworkKey`, so a
screen knows when the artwork changed and asks for the image itself.

WHAT THIS RECEIVES: `call_service` (fire-and-forget, matching how Willo's
own UI has always issued commands — no request/response round trip), and the
two real requests, answered by `requestId`: `request_camera_snapshot` (a
camera card asking for a frame) and `request_media_artwork` (a screen asking
for the artwork a player is showing).

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
import hashlib
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
# `/activity`'s real event history, not a device tile. `media_player` and
# `weather` feed Frame by Willo's music and weather cards.
_SUPPORTED_DOMAINS = {"light", "fan", "sensor", "camera", "binary_sensor", "media_player", "weather"}

# Whether it is night is the sun's state, not the weather's: a weather entity is
# re-sent when the sun rises or sets, so its `isNight` follows.
_SUN_ENTITY_ID = "sun.sun"

_UNKNOWN_STATES = ("unknown", "unavailable")


def _domain_of(entity_id: str) -> str:
    return entity_id.split(".")[0]


def _artwork_key(entity_picture: str | None) -> str | None:
    """A stable key for a player's current artwork, never the URL itself: Home
    Assistant's media proxy URL carries an access token, and its `cache`
    parameter (the part that changes per track) is inside it."""
    if not entity_picture:
        return None
    return hashlib.sha256(entity_picture.encode("utf-8")).hexdigest()[:16]


def _volume_percent(volume_level: Any) -> int | None:
    """Home Assistant's `volume_level` (0.0-1.0) as Willo's 0-100, `None` when unknown."""
    if not isinstance(volume_level, (int, float)):
        return None
    return round(min(max(volume_level, 0.0), 1.0) * 100)


def _capabilities_for(state: State, is_night: bool = False) -> list[dict[str, Any]] | None:
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
    if domain == "media_player":
        return [
            {
                "kind": "media",
                # Willo's media capability (`@willo.sh/shared-types`): the app's
                # tile reads `playing` and `volume`; the frame's music card reads
                # what is playing and the artwork's key.
                "playing": state.state == "playing",
                "volume": _volume_percent(state.attributes.get("volume_level")),
                "title": state.attributes.get("media_title"),
                "artist": state.attributes.get("media_artist"),
                "album": state.attributes.get("media_album_name"),
                "artworkKey": _artwork_key(state.attributes.get("entity_picture")),
            }
        ]
    if domain == "weather":
        temperature = state.attributes.get("temperature")
        return [
            {
                "kind": "weather",
                # Home Assistant's condition vocabulary: sunny, clear-night, cloudy, rainy, ...
                "condition": None if state.state in _UNKNOWN_STATES else state.state,
                "temperature": temperature if isinstance(temperature, (int, float)) else None,
                "temperatureUnit": state.attributes.get("temperature_unit"),
                "isNight": is_night,
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


def _is_night(hass: HomeAssistant) -> bool:
    return hass.states.is_state(_SUN_ENTITY_ID, "below_horizon")


def _to_device(
    state: State, room_by_entity_id: dict[str, str | None], is_night: bool = False
) -> dict[str, Any] | None:
    capabilities = _capabilities_for(state, is_night)
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
    is_night = _is_night(hass)
    devices = []
    for state in hass.states.async_all():
        device = _to_device(state, room_by_entity_id, is_night)
        if device is not None:
            devices.append(device)
    return devices


async def _media_artwork(hass: HomeAssistant, entity_id: Any) -> tuple[bytes | None, str | None]:
    """The image a media player is showing, read through the player entity
    itself — the same call Home Assistant's own media proxy makes — so no URL
    or token is involved. `(None, None)` when the entity is not a player or
    shows nothing."""
    if not isinstance(entity_id, str) or _domain_of(entity_id) != "media_player":
        return None, None
    component = hass.data.get("media_player")
    entity = component.get_entity(entity_id) if component is not None else None
    if entity is None:
        return None, None
    return await entity.async_get_media_image()


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

    @sio.on("request_media_artwork", namespace=TUNNEL_NAMESPACE)
    async def _on_request_media_artwork(message: dict[str, Any]) -> None:
        request_id = message.get("requestId")
        entity_id = message.get("entityId")
        image_base64 = ""
        content_type = None
        try:
            image, content_type = await _media_artwork(hass, entity_id)
            if image:
                image_base64 = base64.b64encode(image).decode("ascii")
        except Exception:  # noqa: BLE001 - Willo's own request times out on a missing/empty response; this must not crash the tunnel
            _LOGGER.exception("Failed to read the artwork of %s", entity_id)
        await sio.emit(
            "media_artwork_result",
            {"requestId": request_id, "imageBase64": image_base64, "contentType": content_type},
            namespace=TUNNEL_NAMESPACE,
        )

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

    async def _emit_device(state: State) -> None:
        device = _to_device(state, _cached_room_index(), _is_night(hass))
        if device is None:
            return
        try:
            await sio.emit("state_changed", device, namespace=TUNNEL_NAMESPACE)
        except socketio.exceptions.BadNamespaceError:
            # Disconnected between the namespace check and this emit: nothing
            # is lost, _on_connect sends a full state_snapshot when it is back.
            return

    async def _on_state_changed(event: Event) -> None:
        new_state: State | None = event.data.get("new_state")
        if new_state is None:
            return
        is_sun = new_state.entity_id == _SUN_ENTITY_ID
        if not is_sun and _domain_of(new_state.entity_id) not in _SUPPORTED_DOMAINS:
            return
        # While the tunnel is down (Willo's backend unreachable, or mid-
        # reconnect) there is nobody to send this to: emitting raised
        # BadNamespaceError on EVERY state change, flooding HA's log. Nothing
        # is lost by dropping it — _on_connect sends a full state_snapshot
        # as soon as the tunnel is back.
        if TUNNEL_NAMESPACE not in sio.namespaces:
            return
        if is_sun:
            # Sunrise or sunset: every weather entity's `isNight` just changed.
            old_state: State | None = event.data.get("old_state")
            if old_state is not None and old_state.state == new_state.state:
                return
            for weather in hass.states.async_all("weather"):
                await _emit_device(weather)
            return
        await _emit_device(new_state)

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
