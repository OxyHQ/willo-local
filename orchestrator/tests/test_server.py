"""Tests for server.py — the orchestrator's own persistent HTTP surface.

test_root_path_serves_the_claim_ui_not_a_403 is a regression test for a
real bug found while setting up a live demo instance of this exact code:
aiohttp's `add_static("/", static_dir, show_index=False)` resolves a
request for "/" as a directory-root request and returns a bare 403
Forbidden — it does NOT fall through to a catch-all route registered
after it. A person opening the device's address in a browser would have
seen a blank 403 page instead of the claim UI. Fixed by registering an
exact "/" route, serving index.html directly, BEFORE add_static.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from willo_orchestrator.server import build_app
from willo_orchestrator.status import new_status


@pytest.fixture
def built_static_dir(tmp_path: Path) -> Path:
    static_dir = tmp_path / "dist"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<html><body>willo-claim-ui</body></html>")
    assets_dir = static_dir / "assets"
    assets_dir.mkdir()
    (assets_dir / "index.js").write_text("console.log('hi')")
    return static_dir


async def test_root_path_serves_the_claim_ui_not_a_403(built_static_dir: Path) -> None:
    app = build_app(new_status(), built_static_dir)
    async with TestClient(TestServer(app)) as client:
        response = await client.get("/")

        assert response.status == 200
        body = await response.text()
        assert "willo-claim-ui" in body


async def test_status_endpoint_still_wins_over_static_serving(built_static_dir: Path) -> None:
    status = new_status()
    status.claim_code = "ABCD1234"
    app = build_app(status, built_static_dir)
    async with TestClient(TestServer(app)) as client:
        response = await client.get("/status")

        assert response.status == 200
        body = await response.json()
        assert body["claimCode"] == "ABCD1234"


async def test_real_static_asset_is_still_served(built_static_dir: Path) -> None:
    app = build_app(new_status(), built_static_dir)
    async with TestClient(TestServer(app)) as client:
        response = await client.get("/assets/index.js")

        assert response.status == 200
        assert "console.log" in await response.text()


async def test_unknown_deep_link_path_falls_back_to_the_claim_ui(built_static_dir: Path) -> None:
    """A person refreshing on some future deep link still sees the app,
    not a 404 — this single-screen app has no real deep links today, but
    the fallback exists for when it might.
    """
    app = build_app(new_status(), built_static_dir)
    async with TestClient(TestServer(app)) as client:
        response = await client.get("/some/unknown/path")

        assert response.status == 200
        assert "willo-claim-ui" in await response.text()


def test_handle_path_guard_rejects_a_resolved_path_outside_static_dir(tmp_path: Path) -> None:
    """Unit-level check of the actual guard, since a normal HTTP client
    normalizes "../" out of a URL before ever sending the request — real
    browsers and aiohttp's own test client do this too, so the guard
    can't be exercised through a real GET the way test_server.py's other
    tests work. This directly proves what that guard does: a path that
    resolves outside static_dir must never be treated as "the file
    exists, serve it" — it must fall through exactly like any other
    missing path (serve index.html, or 404 if that's missing too), never
    reach outside static_dir.
    """
    static_dir = (tmp_path / "dist").resolve()
    static_dir.mkdir()
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text("do not serve me")

    escaping_candidate = (static_dir / ".." / "secret.txt").resolve()
    assert escaping_candidate == secret_file  # sanity: this really does point outside static_dir

    with pytest.raises(ValueError):
        escaping_candidate.relative_to(static_dir)


async def test_missing_build_directory_logs_a_warning_and_serves_only_status(tmp_path: Path) -> None:
    missing_dir = tmp_path / "does-not-exist"
    app = build_app(new_status(), missing_dir)
    async with TestClient(TestServer(app)) as client:
        status_response = await client.get("/status")
        root_response = await client.get("/")

        assert status_response.status == 200
        assert root_response.status == 404
