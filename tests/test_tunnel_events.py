"""state_changed forwarding over the tunnel: nothing is emitted (and nothing
raises) while the tunnel is down, and the entity -> room index is reused
between events instead of being rebuilt from the registries on every one.

AsyncClient.connect is mocked by conftest.py, so the client never really
connects; whether the tunnel counts as "up" is driven here through
`sio.namespaces`, the same dict python-socketio fills on connect and empties
on disconnect.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import socketio
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.willo as willo
from custom_components.willo.const import CONF_HOME_ID, CONF_SECRET, DOMAIN, TUNNEL_NAMESPACE


async def _setup(hass: HomeAssistant) -> socketio.AsyncClient:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_HOME_ID: "home-1", CONF_SECRET: "s3cret"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return hass.data[DOMAIN][entry.entry_id]["sio"]


def _state_changed_emits(emit: AsyncMock) -> list:
    return [c for c in emit.await_args_list if c.args[0] == "state_changed"]


async def test_nothing_is_emitted_while_the_tunnel_is_down(hass: HomeAssistant, caplog) -> None:
    with patch.object(socketio.AsyncClient, "emit", new=AsyncMock()) as emit:
        sio = await _setup(hass)
        assert TUNNEL_NAMESPACE not in sio.namespaces

        hass.states.async_set("light.lamp", "on")
        await hass.async_block_till_done()

    assert _state_changed_emits(emit) == []
    assert "BadNamespaceError" not in caplog.text


async def test_state_changes_are_emitted_while_the_tunnel_is_up(hass: HomeAssistant) -> None:
    with patch.object(socketio.AsyncClient, "emit", new=AsyncMock()) as emit:
        sio = await _setup(hass)
        sio.namespaces[TUNNEL_NAMESPACE] = "sid-1"

        hass.states.async_set("light.lamp", "on", {"friendly_name": "Lamp"})
        await hass.async_block_till_done()

    [call] = _state_changed_emits(emit)
    assert call.args[1]["id"] == "light.lamp"
    assert call.kwargs["namespace"] == TUNNEL_NAMESPACE


async def test_a_disconnect_racing_the_emit_is_swallowed(hass: HomeAssistant, caplog) -> None:
    raising_emit = AsyncMock(side_effect=socketio.exceptions.BadNamespaceError("/tunnel is not a connected namespace."))
    with patch.object(socketio.AsyncClient, "emit", new=raising_emit):
        sio = await _setup(hass)
        sio.namespaces[TUNNEL_NAMESPACE] = "sid-1"

        with caplog.at_level(logging.ERROR):
            hass.states.async_set("light.lamp", "on")
            await hass.async_block_till_done()

    assert raising_emit.await_count == 1
    assert "BadNamespaceError" not in caplog.text


async def test_room_index_is_reused_until_a_registry_changes(hass: HomeAssistant) -> None:
    entity = er.async_get(hass).async_get_or_create("light", "test", "lamp-1", suggested_object_id="lamp")

    with (
        patch.object(socketio.AsyncClient, "emit", new=AsyncMock()) as emit,
        patch.object(willo, "_build_room_index", wraps=willo._build_room_index) as build,
    ):
        sio = await _setup(hass)
        sio.namespaces[TUNNEL_NAMESPACE] = "sid-1"

        hass.states.async_set(entity.entity_id, "on")
        hass.states.async_set(entity.entity_id, "off")
        await hass.async_block_till_done()
        assert build.call_count == 1

        kitchen = ar.async_get(hass).async_create("Kitchen")
        er.async_get(hass).async_update_entity(entity.entity_id, area_id=kitchen.id)
        await hass.async_block_till_done()

        hass.states.async_set(entity.entity_id, "on")
        await hass.async_block_till_done()

    assert build.call_count == 2
    assert _state_changed_emits(emit)[-1].args[1]["room"] == "Kitchen"
