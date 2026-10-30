"""Media players and weather over the tunnel, for Frame by Willo's music and
weather cards: what each one sends, that a player's artwork URL (which carries
a Home Assistant access token) never leaves this instance, that the weather is
re-sent when the sun rises or sets, and that `request_media_artwork` answers
with the image the player itself serves.

AsyncClient.connect is mocked by conftest.py; the tunnel counts as "up" when
`sio.namespaces` holds it, as in test_tunnel_events.py.
"""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import socketio
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.willo as willo
from custom_components.willo.const import CONF_HOME_ID, CONF_SECRET, DOMAIN, TUNNEL_NAMESPACE

PROXY_URL = "/api/media_player_proxy/media_player.studio?token=0123456789abcdef&cache=a1b2c3"


async def _setup(hass: HomeAssistant) -> socketio.AsyncClient:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_HOME_ID: "home-1", CONF_SECRET: "s3cret"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    sio = hass.data[DOMAIN][entry.entry_id]["sio"]
    sio.namespaces[TUNNEL_NAMESPACE] = "sid-1"
    return sio


def _sent(emit: AsyncMock, event: str = "state_changed") -> list[dict]:
    return [c.args[1] for c in emit.await_args_list if c.args[0] == event]


async def test_a_playing_player_sends_what_is_playing_and_only_a_hash_of_its_artwork(hass: HomeAssistant) -> None:
    with patch.object(socketio.AsyncClient, "emit", new=AsyncMock()) as emit:
        await _setup(hass)
        hass.states.async_set(
            "media_player.studio",
            "playing",
            {
                "friendly_name": "Studio speakers",
                "media_title": "Teardrop",
                "media_artist": "Massive Attack",
                "media_album_name": "Mezzanine",
                "entity_picture": PROXY_URL,
            },
        )
        await hass.async_block_till_done()

    [device] = _sent(emit)
    [media] = device["capabilities"]
    assert media["kind"] == "media"
    assert media["state"] == "playing"
    assert (media["title"], media["artist"], media["album"]) == ("Teardrop", "Massive Attack", "Mezzanine")
    assert media["artworkKey"] and len(media["artworkKey"]) == 16
    # The proxy URL and its token stay here.
    assert "token" not in repr(device)
    assert "media_player_proxy" not in repr(device)


async def test_new_artwork_gets_a_new_key_and_no_artwork_none(hass: HomeAssistant) -> None:
    with patch.object(socketio.AsyncClient, "emit", new=AsyncMock()) as emit:
        await _setup(hass)
        hass.states.async_set("media_player.studio", "playing", {"entity_picture": PROXY_URL})
        await hass.async_block_till_done()
        hass.states.async_set("media_player.studio", "playing", {"entity_picture": PROXY_URL.replace("a1b2c3", "d4e5f6")})
        await hass.async_block_till_done()
        hass.states.async_set("media_player.studio", "idle", {})
        await hass.async_block_till_done()

    keys = [device["capabilities"][0]["artworkKey"] for device in _sent(emit)]
    assert keys[0] != keys[1]
    assert keys[2] is None


async def test_weather_sends_its_condition_temperature_and_whether_it_is_night(hass: HomeAssistant) -> None:
    hass.states.async_set("sun.sun", "below_horizon")
    with patch.object(socketio.AsyncClient, "emit", new=AsyncMock()) as emit:
        await _setup(hass)
        hass.states.async_set("weather.home", "partlycloudy", {"temperature": 14.2, "temperature_unit": "°C"})
        await hass.async_block_till_done()

    [device] = _sent(emit)
    assert device["capabilities"] == [
        {
            "kind": "weather",
            "condition": "partlycloudy",
            "temperature": 14.2,
            "temperatureUnit": "°C",
            "isNight": True,
        }
    ]


async def test_sunrise_resends_every_weather_entity_and_nothing_else(hass: HomeAssistant) -> None:
    hass.states.async_set("sun.sun", "below_horizon")
    hass.states.async_set("weather.home", "sunny", {"temperature": 20})
    hass.states.async_set("light.lamp", "on")
    with patch.object(socketio.AsyncClient, "emit", new=AsyncMock()) as emit:
        await _setup(hass)
        hass.states.async_set("sun.sun", "above_horizon")
        await hass.async_block_till_done()
        # An attribute-only update of the sun (its elevation, every few minutes) is not a sunrise.
        hass.states.async_set("sun.sun", "above_horizon", {"elevation": 12})
        await hass.async_block_till_done()

    sent = _sent(emit)
    assert [device["id"] for device in sent] == ["weather.home"]
    assert sent[0]["capabilities"][0]["isNight"] is False


async def test_artwork_requests_are_answered_with_the_players_own_image(hass: HomeAssistant) -> None:
    player = MagicMock()
    player.async_get_media_image = AsyncMock(return_value=(b"\xff\xd8jpeg", "image/jpeg"))
    component = MagicMock()
    component.get_entity = MagicMock(side_effect=lambda entity_id: player if entity_id == "media_player.studio" else None)

    with patch.object(socketio.AsyncClient, "emit", new=AsyncMock()) as emit:
        sio = await _setup(hass)
        hass.data["media_player"] = component
        handler = sio.handlers[TUNNEL_NAMESPACE]["request_media_artwork"]
        await handler({"requestId": "r-1", "entityId": "media_player.studio"})
        await handler({"requestId": "r-2", "entityId": "media_player.elsewhere"})
        await handler({"requestId": "r-3", "entityId": "camera.door"})

    results = {result["requestId"]: result for result in _sent(emit, "media_artwork_result")}
    assert base64.b64decode(results["r-1"]["imageBase64"]) == b"\xff\xd8jpeg"
    assert results["r-1"]["contentType"] == "image/jpeg"
    # A player that is not there, or an entity that is not a player: an empty
    # answer, so Willo's request ends at once instead of timing out.
    assert results["r-2"]["imageBase64"] == ""
    assert results["r-3"]["imageBase64"] == ""
    assert component.get_entity.call_args_list[-1].args == ("media_player.elsewhere",)


async def test_the_artwork_key_is_not_the_url(hass: HomeAssistant) -> None:
    assert willo._artwork_key(None) is None
    assert willo._artwork_key("") is None
    key = willo._artwork_key(PROXY_URL)
    assert key is not None and key not in PROXY_URL and "token" not in key
