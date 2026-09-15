"""A thin client for Home Assistant Core's REST API — onboarding, auth,
and the `homeassistant.restart` service.

Every endpoint and payload shape here was verified empirically against a
real, local Home Assistant Core 2026.2.3 instance (a disposable Python venv
install — see this repo's README, "Real local HA Core instance" section).
None of this was guessed from memory or from HA's docs site — this module
mirrors exactly what was proven to work by driving `curl`/a Python script
against a live `hass` process and reading its real HTTP responses.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import aiohttp

from .const import DEFAULT_HA_BASE_URL

_LOGGER = logging.getLogger(__name__)


class HAClientError(Exception):
    """Raised when a Home Assistant REST call fails in a way the caller must react to."""


class HAClient:
    """Talks to the LOCAL Home Assistant Core instance this orchestrator
    is provisioning — never anything else. See this repo's README for the
    explicit confirmation that no code anywhere in this package reaches
    outside localhost for Core traffic.
    """

    def __init__(self, session: aiohttp.ClientSession, base_url: str = DEFAULT_HA_BASE_URL) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")

    async def wait_until_api_ready(self, *, poll_interval_seconds: float = 2.0, timeout_seconds: float = 300.0) -> None:
        """Poll Core's REST API until it answers at all. A 401 (unauthenticated)
        counts as "ready" — it proves the HTTP server and the `api` component
        are up; we are not authenticated yet at this point in the boot sequence.
        """
        deadline = time.monotonic() + timeout_seconds
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                async with self._session.get(f"{self._base_url}/api/", timeout=aiohttp.ClientTimeout(total=5)) as response:
                    if response.status in (200, 401):
                        return
                    last_error = HAClientError(f"Unexpected status {response.status} from {self._base_url}/api/")
            except (aiohttp.ClientError, TimeoutError) as error:
                last_error = error
            await asyncio.sleep(poll_interval_seconds)
        raise HAClientError(f"Core's REST API never became ready at {self._base_url}") from last_error

    async def get_onboarding_status(self) -> list[dict[str, Any]]:
        async with self._session.get(f"{self._base_url}/api/onboarding") as response:
            if response.status != 200:
                raise HAClientError(f"GET /api/onboarding -> {response.status}")
            result: list[dict[str, Any]] = await response.json()
            return result

    async def create_admin_user(self, *, name: str, username: str, password: str, client_id: str, language: str = "en") -> str:
        """POST /api/onboarding/users. Returns an auth_code — exchange it
        with exchange_auth_code() for a real access/refresh token pair.
        """
        payload = {
            "name": name,
            "username": username,
            "password": password,
            "client_id": client_id,
            "language": language,
        }
        async with self._session.post(f"{self._base_url}/api/onboarding/users", json=payload) as response:
            body = await response.json()
            if response.status != 200:
                raise HAClientError(f"POST /api/onboarding/users -> {response.status} {body}")
            auth_code: str = body["auth_code"]
            return auth_code

    async def exchange_auth_code(self, *, auth_code: str, client_id: str) -> dict[str, Any]:
        data = {"grant_type": "authorization_code", "code": auth_code, "client_id": client_id}
        async with self._session.post(f"{self._base_url}/auth/token", data=data) as response:
            body: dict[str, Any] = await response.json()
            if response.status != 200:
                raise HAClientError(f"POST /auth/token (authorization_code) -> {response.status} {body}")
            return body

    async def refresh_access_token(self, *, refresh_token: str, client_id: str) -> str:
        data = {"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": client_id}
        async with self._session.post(f"{self._base_url}/auth/token", data=data) as response:
            body = await response.json()
            if response.status != 200:
                raise HAClientError(f"POST /auth/token (refresh_token) -> {response.status} {body}")
            access_token: str = body["access_token"]
            return access_token

    async def finish_core_config_step(self, *, access_token: str) -> None:
        headers = {"Authorization": f"Bearer {access_token}"}
        async with self._session.post(f"{self._base_url}/api/onboarding/core_config", headers=headers) as response:
            if response.status != 200:
                raise HAClientError(f"POST /api/onboarding/core_config -> {response.status}")

    async def finish_analytics_step(self, *, access_token: str) -> None:
        headers = {"Authorization": f"Bearer {access_token}"}
        async with self._session.post(f"{self._base_url}/api/onboarding/analytics", headers=headers) as response:
            if response.status != 200:
                raise HAClientError(f"POST /api/onboarding/analytics -> {response.status}")

    async def finish_integration_step(self, *, access_token: str, client_id: str, redirect_uri: str) -> None:
        headers = {"Authorization": f"Bearer {access_token}"}
        payload = {"client_id": client_id, "redirect_uri": redirect_uri}
        async with self._session.post(
            f"{self._base_url}/api/onboarding/integration", json=payload, headers=headers
        ) as response:
            if response.status != 200:
                raise HAClientError(f"POST /api/onboarding/integration -> {response.status}")

    async def restart_core(self, *, access_token: str) -> None:
        """Calls the real, stock `homeassistant.restart` service — the
        SAME call a real HAOS deployment relies on (Supervisor watches for
        Core's exit and relaunches its container; a bare `hass` process,
        like the ones in this repo's own sandbox tests, just exits and
        needs an external supervisor loop — see this repo's README,
        "restarting Core in a plain venv" note, and
        scripts/dev_supervise_hass.py for the sandbox-only stand-in for
        that role).
        """
        headers = {"Authorization": f"Bearer {access_token}"}
        async with self._session.post(
            f"{self._base_url}/api/services/homeassistant/restart", headers=headers
        ) as response:
            if response.status not in (200, 201):
                raise HAClientError(f"POST /api/services/homeassistant/restart -> {response.status}")
