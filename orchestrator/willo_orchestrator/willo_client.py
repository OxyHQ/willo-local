"""Client for Willo's device-claim backend contract (OxyHQ/Willo issue #9):

    POST /tunnel/claim                                  -> {claimCode, claimToken, expiresAt}
    GET  /tunnel/claim/status  (Authorization: Bearer <claimToken>)
                                                          -> {status: 'pending'}
                                                          -> {status: 'claimed', homeId, secret}
                                                          -> {status: 'expired'}

STATUS, VERIFIED FOR REAL: `https://api.willo.sh` is reachable from this
sandbox (curl gets a real HTTP response), but `POST /tunnel/claim` answers
404 "Cannot POST /tunnel/claim" — the route genuinely does not exist yet
(it ships in a separate, parallel agent's backend work against this same
issue). This is exactly the "host reachable, endpoint not deployed yet"
case the task called out, not a network problem — so this client tries the
real endpoint first (in case it has shipped by the time this runs) and
falls back to a clearly-labeled in-memory mock, rather than skipping the
rest of the orchestrator's boot sequence or hanging forever.

THE MOCK IS TEST/DEV SCAFFOLDING, NOT PRODUCTION BEHAVIOUR. It exists so
this orchestrator's full boot sequence — onboarding through to a written
config entry and a Core restart — can be exercised end-to-end before the
real backend exists. Once packages/backend ships the real routes, this
mock becomes dead code and should be deleted, not kept "just in case".
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import string
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

import aiohttp

from .const import DEFAULT_CLAIM_STATUS_URL, DEFAULT_CLAIM_URL

_LOGGER = logging.getLogger(__name__)

ClaimStatusValue = Literal["pending", "claimed", "expired"]

# Chosen to be easy to read off a small screen and type/say aloud — same
# spirit as the pairing-code alphabet already used by the existing
# app-initiated pairing flow (packages/backend's PAIRING_CODE_ALPHABET,
# per the issue text), reproduced here since this process has no access
# to that backend constant directly.
_CLAIM_CODE_ALPHABET = "".join(c for c in string.ascii_uppercase + string.digits if c not in "0O1I")


@dataclass
class ClaimResult:
    claim_code: str
    claim_token: str
    expires_at: str


@dataclass
class ClaimStatusResult:
    status: ClaimStatusValue
    home_id: str | None = None
    secret: str | None = None


class _MockClaimBackend:
    """Stands in for the real POST /tunnel/claim + GET /tunnel/claim/status
    while packages/backend's device_claims routes don't exist yet. Auto-
    transitions from pending to claimed a few seconds after the claim was
    requested, simulating a person tapping "claim" in the Willo app — long
    enough to prove the orchestrator's `awaiting-pairing` stage really
    renders and is really being polled, short enough that a full local
    end-to-end run finishes in well under a minute.
    """

    AUTO_CLAIM_AFTER_SECONDS = 6.0

    def __init__(self) -> None:
        self._claim_token: str | None = None
        self._claim_code: str | None = None
        self._requested_at: float | None = None
        self._home_id: str | None = None
        self._secret: str | None = None
        self._delivered = False

    def request_claim(self) -> ClaimResult:
        self._claim_code = "".join(secrets.choice(_CLAIM_CODE_ALPHABET) for _ in range(8))
        self._claim_token = secrets.token_urlsafe(32)
        self._requested_at = time.monotonic()
        self._home_id = f"home_mock_{secrets.token_hex(4)}"
        self._secret = secrets.token_urlsafe(32)
        self._delivered = False
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
        _LOGGER.warning(
            "Willo backend claim routes are not live yet — using the LOCAL MOCK claim backend "
            "(code=%s). This must never happen against real hardware once packages/backend ships "
            "the real /tunnel/claim routes.",
            self._claim_code,
        )
        return ClaimResult(claim_code=self._claim_code, claim_token=self._claim_token, expires_at=expires_at)

    def poll_status(self, claim_token: str) -> ClaimStatusResult:
        if claim_token != self._claim_token or self._requested_at is None:
            return ClaimStatusResult(status="expired")
        if self._delivered:
            # Single-delivery, matching the real backend's contract (the
            # secret is only ever returned once — see the issue's
            # "Security note").
            return ClaimStatusResult(status="expired")
        elapsed = time.monotonic() - self._requested_at
        if elapsed < self.AUTO_CLAIM_AFTER_SECONDS:
            return ClaimStatusResult(status="pending")
        self._delivered = True
        return ClaimStatusResult(status="claimed", home_id=self._home_id, secret=self._secret)


class WilloClaimClient:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        claim_url: str = DEFAULT_CLAIM_URL,
        claim_status_url: str = DEFAULT_CLAIM_STATUS_URL,
    ) -> None:
        self._session = session
        self._claim_url = claim_url
        self._claim_status_url = claim_status_url
        self._mock = _MockClaimBackend()
        self._using_mock = False

    async def request_claim(self) -> ClaimResult:
        try:
            async with self._session.post(self._claim_url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 201:
                    body = await response.json()
                    return ClaimResult(
                        claim_code=body["claimCode"], claim_token=body["claimToken"], expires_at=body["expiresAt"]
                    )
                _LOGGER.warning(
                    "Real POST %s answered %s (backend not deployed yet) — falling back to local mock",
                    self._claim_url,
                    response.status,
                )
        except (aiohttp.ClientError, TimeoutError) as error:
            _LOGGER.warning("Real POST %s unreachable (%s) — falling back to local mock", self._claim_url, error)

        self._using_mock = True
        return self._mock.request_claim()

    async def poll_status(self, claim_token: str) -> ClaimStatusResult:
        if self._using_mock:
            return self._mock.poll_status(claim_token)

        headers = {"Authorization": f"Bearer {claim_token}"}
        async with self._session.get(
            self._claim_status_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)
        ) as response:
            body = await response.json()
            return ClaimStatusResult(status=body["status"], home_id=body.get("homeId"), secret=body.get("secret"))

    async def wait_for_claim(self, claim_token: str, *, poll_interval_seconds: float = 2.0) -> ClaimStatusResult:
        while True:
            result = await self.poll_status(claim_token)
            if result.status != "pending":
                return result
            await asyncio.sleep(poll_interval_seconds)
