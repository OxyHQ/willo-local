"""Tests for hostname.py's set_device_hostname — renaming this device to
"willo" (so real HAOS mDNS advertises it as willo.local) via HAOS
Supervisor's real host/options API. See hostname.py's module doc comment
for exactly what is and isn't verified here: the SUPERVISOR_TOKEN-absent
path (this sandbox's actual situation, and every plain venv/Docker Core
install) is real and tested for real below; a real Supervisor's actual
response is NOT available to test against in this sandbox — see the
README's "needs real HAOS hardware" list.
"""

from __future__ import annotations

import pytest

from willo_orchestrator.hostname import set_device_hostname


async def test_returns_false_when_supervisor_token_is_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)

    result = await set_device_hostname()

    assert result is False


async def test_returns_false_and_does_not_raise_when_supervisor_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A token happens to be set (e.g. a misconfigured environment) but
    there is no real Supervisor at http://supervisor to answer — this
    must degrade to False, never raise, never hang the caller.
    """
    monkeypatch.setenv("SUPERVISOR_TOKEN", "not-a-real-token")

    result = await set_device_hostname()

    assert result is False
