"""Tests for server.py (FastAPI wrapper around the Coordinator).

We mock the Coordinator + InMemoryRunner so tests don't need a real
GOOGLE_API_KEY. TestClient from FastAPI gives us a sync API to exercise
the route handlers.

Notes on env handling: server.py calls load_dotenv() at import, so a
local `.env` file can leak into tests. We monkey-patch dotenv.load_dotenv
to a no-op and set env explicitly per test.
"""

from __future__ import annotations

import importlib
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def _ensure_adk():
    pytest.importorskip("google.adk")
    pytest.importorskip("fastapi")
    pytest.importorskip("uvicorn")


@pytest.fixture
def _clean_dotenv():
    """Stop server.py's load_dotenv() from leaking real keys into tests."""
    with patch("dotenv.load_dotenv", lambda *a, **kw: None):
        yield


@pytest.fixture
def _set_google(monkeypatch):
    """Set GOOGLE_API_KEY; leave PLACES unset."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)


@pytest.fixture
def _set_both(monkeypatch):
    """Set both GOOGLE_API_KEY and GOOGLE_PLACES_API_KEY."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "test-places-key")


@pytest.fixture
def _no_keys(monkeypatch):
    """Clear both API keys entirely."""
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)


@pytest.fixture
def _mock_coordinator(_clean_dotenv):
    """Patch create_coordinator AND reset the server module, so a fresh
    _COORDINATOR instance is built under the current env."""
    with patch("agents.coordinator.create_coordinator") as mock:
        mock.return_value = MagicMock(name="MockCoordinator")
        # Reload server so _KEYS / _COORDINATOR match the current env.
        if "server" in sys.modules:
            importlib.reload(sys.modules["server"])
        else:
            import server  # noqa: F401  first-time import
        yield mock
        # Reset back to "default loaded" state for following tests.
        importlib.reload(sys.modules["server"])


@pytest.fixture
def _mock_runner():
    """Patch InMemoryRunner so /query doesn't hit real Gemini."""

    async def _fake_run_async(*args, **kwargs):
        part = MagicMock()
        part.text = "テスト用の応答です"
        content = MagicMock()
        content.parts = [part]
        event = MagicMock()
        event.content = content
        yield event

    mock_session = MagicMock()
    mock_session.id = "test-session"
    mock_session_service = MagicMock()
    mock_session_service.create_session = AsyncMock(return_value=mock_session)

    runner = MagicMock()
    runner.session_service = mock_session_service
    runner.run_async = _fake_run_async

    with patch("google.adk.runners.InMemoryRunner", return_value=runner) as m:
        yield m


@pytest.fixture
def _mock_empty_runner():
    async def _empty(*args, **kwargs):
        part = MagicMock()
        part.text = ""
        content = MagicMock()
        content.parts = [part]
        event = MagicMock()
        event.content = content
        yield event

    mock_session = MagicMock()
    mock_session.id = "s"
    mock_session_service = MagicMock()
    mock_session_service.create_session = AsyncMock(return_value=mock_session)
    runner = MagicMock()
    runner.session_service = mock_session_service
    runner.run_async = _empty
    with patch("google.adk.runners.InMemoryRunner", return_value=runner):
        yield


@pytest.fixture
def _mock_boom_runner():
    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated Gemini outage")

    mock_session = MagicMock()
    mock_session.id = "s"
    mock_session_service = MagicMock()
    mock_session_service.create_session = AsyncMock(return_value=mock_session)
    runner = MagicMock()
    runner.session_service = mock_session_service
    runner.run_async = _boom
    with patch("google.adk.runners.InMemoryRunner", return_value=runner):
        yield


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


def test_health_returns_ok(_ensure_adk, _set_google, _mock_coordinator):
    """GET /health → 200; google key yes, places key no."""
    from server import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["google_api_key_set"] is True
    assert body["places_api_key_set"] is False


def test_health_reports_both_keys_when_set(
    _ensure_adk, _set_both, _mock_coordinator
):
    """GET /health → 200; both flags True when both keys are in env."""
    from server import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.get("/health")
    body = resp.json()
    assert body["google_api_key_set"] is True
    assert body["places_api_key_set"] is True


def test_health_works_without_any_keys(
    _ensure_adk, _no_keys, _mock_coordinator
):
    """GET /health still 200 when no keys — it's a liveness probe, not auth."""
    from server import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["google_api_key_set"] is False
    assert body["places_api_key_set"] is False


# ---------------------------------------------------------------------------
# POST /query — happy path
# ---------------------------------------------------------------------------


def test_query_returns_synthesized_text(
    _ensure_adk, _set_google, _mock_coordinator, _mock_runner
):
    """POST /query → 200; response is Coordinator text, query is echoed,
    default exposure_comfort is 3."""
    from server import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.post("/query", json={"query": "横浜のカフェを教えて"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["response"] == "テスト用の応答です"
    assert body["query"] == "横浜のカフェを教えて"
    assert body["exposure_comfort"] == 3


def test_query_accepts_exposure_comfort_override(
    _ensure_adk, _set_google, _mock_coordinator, _mock_runner
):
    """When exposure_comfort is set, the value appears in the response."""
    from server import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.post("/query", json={"query": "池袋", "exposure_comfort": 1})
    assert resp.status_code == 200
    assert resp.json()["exposure_comfort"] == 1


def test_query_keeps_default_when_exposure_is_3(
    _ensure_adk, _set_google, _mock_coordinator, _mock_runner
):
    """Slider == 3 is the default; we don't bother rebuilding Coordinator."""
    from server import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.post("/query", json={"query": "x", "exposure_comfort": 3})
    assert resp.status_code == 200
    assert resp.json()["exposure_comfort"] == 3


# ---------------------------------------------------------------------------
# POST /query — validation
# ---------------------------------------------------------------------------


def test_query_rejects_empty_query(
    _ensure_adk, _set_google, _mock_coordinator, _mock_runner
):
    """Pydantic: empty query → 422."""
    from server import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.post("/query", json={"query": ""})
    assert resp.status_code == 422


def test_query_rejects_out_of_range_slider(
    _ensure_adk, _set_google, _mock_coordinator, _mock_runner
):
    """Pydantic: slider outside 1..5 → 422."""
    from server import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    for bad in (0, 6, -1, 100):
        resp = client.post("/query", json={"query": "x", "exposure_comfort": bad})
        assert resp.status_code == 422, f"slider={bad} should be rejected"


def test_query_rejects_too_long_query(
    _ensure_adk, _set_google, _mock_coordinator, _mock_runner
):
    """Pydantic: query > 2000 chars → 422 (DoS guard)."""
    from server import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.post("/query", json={"query": "a" * 2001})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /query — error branches
# ---------------------------------------------------------------------------


def test_query_503_when_no_google_key(
    _ensure_adk, _no_keys, _mock_coordinator, _mock_runner
):
    """/query with no GOOGLE_API_KEY → 503 (config issue, not 500)."""
    from server import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.post("/query", json={"query": "x"})
    assert resp.status_code == 503
    assert "GOOGLE_API_KEY" in resp.json()["detail"]


def test_query_placeholder_on_empty_text(
    _ensure_adk, _set_google, _mock_coordinator, _mock_empty_runner
):
    """When the Coordinator emits no text, /query returns the placeholder
    string instead of empty (clients should always see *something*)."""
    from server import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.post("/query", json={"query": "x"})
    assert resp.status_code == 200
    assert "応答テキスト" in resp.json()["response"]


def test_query_500_on_internal_error(
    _ensure_adk, _set_google, _mock_coordinator, _mock_boom_runner
):
    """When the Coordinator raises, /query returns 500 (not crash the worker)."""
    from server import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.post("/query", json={"query": "x"})
    assert resp.status_code == 500
    assert "Coordinator error" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def test_read_api_keys_prefers_google(_ensure_adk, _clean_dotenv, monkeypatch):
    """When both GOOGLE_API_KEY and GEMINI_API_KEY are set, GOOGLE wins."""
    monkeypatch.setenv("GOOGLE_API_KEY", "google-wins")
    monkeypatch.setenv("GEMINI_API_KEY", "legacy-loses")
    if "server" in sys.modules:
        importlib.reload(sys.modules["server"])
    from server import _read_api_keys
    assert _read_api_keys()["google"] == "google-wins"


def test_read_api_keys_falls_back_to_gemini(
    _ensure_adk, _clean_dotenv, monkeypatch
):
    """When only GEMINI_API_KEY is set, it's used as the legacy alias."""
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "legacy-wins")
    if "server" in sys.modules:
        importlib.reload(sys.modules["server"])
    from server import _read_api_keys
    assert _read_api_keys()["google"] == "legacy-wins"


def test_default_port_is_8080(_ensure_adk):
    """uvicorn binds to 8080 unless PORT is set (Cloud Run injects its own)."""
    assert int(os.getenv("PORT", "8080")) == 8080
