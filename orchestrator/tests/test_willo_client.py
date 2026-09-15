"""Tests for willo_client.py's _MockClaimBackend — the test/dev
scaffolding standing in for the real POST /tunnel/claim + GET
/tunnel/claim/status while (or if) those routes are unreachable (see
willo_client.py's module doc comment). The real request_claim()/
poll_status() HTTP paths were verified against the actual live
api.willo.sh backend instead (see this repo's README) — this class is
pure local logic with no network calls, so it's what an automated test
can actually exercise quickly and deterministically.
"""

from __future__ import annotations

import time

from willo_orchestrator.willo_client import _MockClaimBackend


def test_request_claim_returns_a_pending_looking_code() -> None:
    backend = _MockClaimBackend()
    result = backend.request_claim()

    assert len(result.claim_code) == 8
    assert result.claim_token
    assert result.expires_at


def test_poll_status_is_pending_immediately_after_request() -> None:
    backend = _MockClaimBackend()
    claim = backend.request_claim()

    status = backend.poll_status(claim.claim_token)

    assert status.status == "pending"
    assert status.home_id is None
    assert status.secret is None


def test_poll_status_transitions_to_claimed_after_the_auto_claim_delay() -> None:
    backend = _MockClaimBackend()
    backend.AUTO_CLAIM_AFTER_SECONDS = 0.01  # keep the test fast
    claim = backend.request_claim()

    time.sleep(0.02)
    status = backend.poll_status(claim.claim_token)

    assert status.status == "claimed"
    assert status.home_id is not None
    assert status.secret is not None


def test_poll_status_only_delivers_the_secret_once() -> None:
    """Mirrors the real backend's single-delivery contract for the
    plaintext secret (see the issue's "Security note").
    """
    backend = _MockClaimBackend()
    backend.AUTO_CLAIM_AFTER_SECONDS = 0.01
    claim = backend.request_claim()

    time.sleep(0.02)
    first = backend.poll_status(claim.claim_token)
    second = backend.poll_status(claim.claim_token)

    assert first.status == "claimed"
    assert second.status == "expired"


def test_poll_status_with_wrong_token_is_expired() -> None:
    backend = _MockClaimBackend()
    backend.request_claim()

    status = backend.poll_status("not-the-real-token")

    assert status.status == "expired"
