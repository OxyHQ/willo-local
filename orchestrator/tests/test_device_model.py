"""Tests for device_model.py's detect_device_model — the Willo app's
"Connect Home Assistant" auto-detect screen's deviceModel field (see
status.py). See device_model.py's module doc comment for exactly what is
and isn't verified here: the SUPERVISOR_TOKEN-absent path (this sandbox's
actual situation, and every plain venv/Docker Core install) is real and
tested for real below; a real Supervisor's actual response is NOT
available to test against in this sandbox — see the README's "needs real
HAOS hardware" list.
"""

from __future__ import annotations

import pytest

from willo_orchestrator.device_model import detect_device_model


async def test_returns_none_when_supervisor_token_is_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)

    result = await detect_device_model()

    assert result is None


async def test_returns_none_and_does_not_raise_when_supervisor_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A token happens to be set (e.g. a misconfigured environment) but
    there is no real Supervisor at http://supervisor to answer — this
    must degrade to None, never raise, never hang the caller.
    """
    monkeypatch.setenv("SUPERVISOR_TOKEN", "not-a-real-token")

    result = await detect_device_model()

    assert result is None
