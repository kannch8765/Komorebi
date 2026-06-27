"""Hermetic tests for tools.transit_api.TransitAPIClient.

The client makes two HTTP calls (locations/suggest + plan) so tests use a
queue of mock responses keyed by URL.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import requests

from tools.transit_api import TransitAPIError, TransitAPIClient


# ─── Mock helpers ────────────────────────────────────────────────────────────


class _MockQueue:
    """Pop mock responses off a FIFO queue in call order."""

    def __init__(self, mocker):
        self.mocker = mocker
        self.queue: list[dict | Exception] = []
        self.calls: list[tuple[str, dict]] = []
        self._patched = False

    def push(self, payload_or_exc: dict | Exception) -> "_MockQueue":
        self.queue.append(payload_or_exc)
        return self

    def patch(self):
        """Wire `requests.Session.get` to dispatch off the queue."""
        if self._patched:
            return
        self._patched = True

        def _side_effect(url, **kwargs):
            self.calls.append((url, kwargs))
            if not self.queue:
                raise AssertionError(f"unexpected URL with empty queue: {url}")
            payload_or_exc = self.queue.pop(0)
            if isinstance(payload_or_exc, Exception):
                raise payload_or_exc
            return self._build_response(payload_or_exc)

        self.mocker.patch("requests.Session.get", side_effect=_side_effect)

    def _build_response(self, payload):
        mock_response = self.mocker.Mock()
        mock_response.json.return_value = payload
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        return mock_response


def _shibuya_suggest_payload() -> dict:
    return {
        "stations": [
            {
                "id": "scrape-jreast-saikyo:odpt.Station:JR-East.SaikyoKawagoe.Shibuya",
                "name": "渋谷",
                "weight": 29,
                "score": 3,
            }
        ]
    }


def _ikebukuro_suggest_payload() -> dict:
    return {
        "stations": [
            {
                "id": "scrape-jreast-saikyo:odpt.Station:JR-East.SaikyoKawagoe.Ikebukuro",
                "name": "池袋",
                "weight": 29,
                "score": 3,
            }
        ]
    }


def _saikyo_plan_payload() -> dict:
    return {
        "from": {"id": "...Shibuya", "name": "渋谷"},
        "to": {"id": "...Ikebukuro", "name": "池袋"},
        "journeys": [
            {
                "durationSecs": 780,
                "transferCount": 0,
                "legs": [
                    {
                        "kind": "transit",
                        "routeName": "埼京線（大宮・川越方面）",
                        "mode": "rail",
                        "from": {"name": "渋谷"},
                        "to": {"name": "池袋"},
                    }
                ],
            }
        ],
    }


# ─── Tests ───────────────────────────────────────────────────────────────────


def test_successful_route_fetch(mocker):
    q = _MockQueue(mocker)
    q.push(_shibuya_suggest_payload())
    q.push(_ikebukuro_suggest_payload())
    q.push(_saikyo_plan_payload())
    q.patch()

    client = TransitAPIClient()
    result = client.get_routes("渋谷", "池袋")

    assert len(result.routes) == 1
    route = result.routes[0]
    assert route.name == "埼京線（大宮・川越方面）"  # synthesized from legs
    assert route.duration_min == 13  # 780 sec / 60, rounded
    assert route.transfers == 0
    # crowding_score is now computed by tools.crowding (no longer placeholder 0.5)
    assert 0.0 <= route.crowding_score <= 1.0
    assert route.extra_time_min == 0
    assert route.stations == ["渋谷", "池袋"]
    assert route.lines == ["埼京線（大宮・川越方面）"]


def test_multiple_journeys_with_transfers(mocker):
    plan_payload = {
        "journeys": [
            {
                "durationSecs": 780,
                "transferCount": 0,
                "legs": [
                    {
                        "routeName": "埼京線",
                        "from": {"name": "渋谷"},
                        "to": {"name": "池袋"},
                    }
                ],
            },
            {
                "durationSecs": 1080,
                "transferCount": 1,
                "legs": [
                    {
                        "routeName": "JR山手線",
                        "from": {"name": "渋谷"},
                        "to": {"name": "新宿"},
                    },
                    {
                        "routeName": "丸ノ内線",
                        "from": {"name": "新宿"},
                        "to": {"name": "池袋"},
                    },
                ],
            },
        ]
    }
    q = _MockQueue(mocker)
    q.push(_shibuya_suggest_payload())
    q.push(_ikebukuro_suggest_payload())
    q.push(plan_payload)
    q.patch()

    client = TransitAPIClient()
    result = client.get_routes("渋谷", "池袋")

    assert len(result.routes) == 2
    assert result.routes[0].transfers == 0
    assert result.routes[0].lines == ["埼京線"]
    assert result.routes[1].transfers == 1
    assert result.routes[1].lines == ["JR山手線", "丸ノ内線"]
    assert result.routes[1].stations == ["渋谷", "新宿", "池袋"]
    assert "1 回乗換" in result.routes[1].name


def test_empty_journeys_list(mocker):
    q = _MockQueue(mocker)
    q.push(_shibuya_suggest_payload())
    q.push(_ikebukuro_suggest_payload())
    q.push({"journeys": []})
    q.patch()

    client = TransitAPIClient()
    result = client.get_routes("渋谷", "池袋")

    assert result.routes == []


def test_station_not_found_raises(mocker):
    q = _MockQueue(mocker)
    q.push({"stations": []})  # first station missing
    q.patch()

    client = TransitAPIClient()
    with pytest.raises(TransitAPIError, match="station not found"):
        client.get_routes("虚空", "池袋")


def test_http_error_on_plan_raises(mocker):
    """500 from plan call should raise TransitAPIError matching 'HTTP 500'."""
    mock_500 = mocker.Mock()
    mock_500.json.return_value = {}
    mock_500.status_code = 500
    mock_500.raise_for_status.side_effect = requests.HTTPError("500")

    ok_200 = mocker.Mock()
    ok_200.json.return_value = {}
    ok_200.status_code = 200
    ok_200.raise_for_status.return_value = None

    mocker.patch(
        "requests.Session.get",
        side_effect=[
            _build_ok(mocker, _shibuya_suggest_payload()),
            _build_ok(mocker, _ikebukuro_suggest_payload()),
            mock_500,
        ],
    )

    client = TransitAPIClient()
    with pytest.raises(TransitAPIError, match="HTTP 500"):
        client.get_routes("渋谷", "池袋")


def _build_ok(mocker, payload):
    r = mocker.Mock()
    r.json.return_value = payload
    r.status_code = 200
    r.raise_for_status.return_value = None
    return r


def test_network_error_raises(mocker):
    mocker.patch(
        "requests.Session.get",
        side_effect=requests.ConnectionError("boom"),
    )

    client = TransitAPIClient()
    with pytest.raises(TransitAPIError, match="network error"):
        client.get_routes("渋谷", "池袋")


def test_timeout_raises(mocker):
    mocker.patch(
        "requests.Session.get",
        side_effect=requests.Timeout("timed out"),
    )

    client = TransitAPIClient(timeout=5)
    with pytest.raises(TransitAPIError, match="network error"):
        client.get_routes("渋谷", "池袋")


def test_malformed_json_raises(mocker):
    mock_response = mocker.Mock()
    mock_response.json.side_effect = ValueError("not json")
    mock_response.raise_for_status.return_value = None
    mocker.patch("requests.Session.get", return_value=mock_response)

    client = TransitAPIClient()
    with pytest.raises(TransitAPIError, match="malformed JSON"):
        client.get_routes("渋谷", "池袋")


def test_get_routes_makes_two_suggest_calls_then_one_plan(mocker):
    """Verify the orchestration: name resolution precedes plan."""
    q = _MockQueue(mocker)
    q.push(_shibuya_suggest_payload())
    q.push(_ikebukuro_suggest_payload())
    q.push(_saikyo_plan_payload())
    q.patch()

    client = TransitAPIClient()
    client.get_routes("渋谷", "池袋")

    # Three HTTP calls: suggest(渋谷), suggest(池袋), plan
    assert len(q.calls) == 3
    urls = [c[0] for c in q.calls]
    assert "/api/v1/locations/suggest" in urls[0]
    assert "/api/v1/locations/suggest" in urls[1]
    assert urls[2].endswith("/api/v1/plan")
    # Plan call uses IDs, not names
    plan_params = q.calls[2][1]["params"]
    assert "from" in plan_params
    assert "to" in plan_params
    assert plan_params["from"].endswith(".Shibuya")
    assert plan_params["to"].endswith(".Ikebukuro")


def test_resolve_station_id_prefers_score3_over_score2(mocker):
    """Prefer rail (score=3) over bus stops (score=2), regardless of weight."""
    q = _MockQueue(mocker)
    q.push(
        {
            "stations": [
                {"id": "bus-stop", "name": "渋谷", "weight": 80, "score": 2},
                {"id": "jr-rail", "name": "渋谷", "weight": 29, "score": 3},
            ]
        },
    )
    q.patch()

    client = TransitAPIClient()
    station_id = client.resolve_station_id("渋谷")
    assert station_id == "jr-rail"


def test_resolve_station_id_breaks_weight_ties(mocker):
    """Within the same score, pick the higher weight."""
    q = _MockQueue(mocker)
    q.push(
        {
            "stations": [
                {"id": "low-weight", "name": "渋谷", "weight": 5, "score": 3},
                {"id": "high-weight", "name": "渋谷", "weight": 50, "score": 3},
            ]
        },
    )
    q.patch()

    client = TransitAPIClient()
    station_id = client.resolve_station_id("渋谷")
    assert station_id == "high-weight"


def test_crowding_score_uses_injected_time(mocker):
    """When current_time is provided, crowding reflects that time of day.

    A Monday 08:00 + Yamanote + Shinjuku transfer (rush + busy line + tier-1
    hub) should score notably higher than a Tuesday 03:00 same-route call.
    """
    from datetime import datetime

    q = _MockQueue(mocker)
    q.push(_shibuya_suggest_payload())
    q.push(_ikebukuro_suggest_payload())
    q.push(_saikyo_plan_payload())
    q.patch()

    client = TransitAPIClient()
    rush = client.get_routes(
        "渋谷", "池袋",
        current_time=datetime(2026, 6, 22, 8, 0),  # Monday morning rush
    )
    q.push(_shibuya_suggest_payload())
    q.push(_ikebukuro_suggest_payload())
    q.push(_saikyo_plan_payload())
    q.patch()

    quiet = client.get_routes(
        "渋谷", "池袋",
        current_time=datetime(2026, 6, 23, 3, 0),  # Tuesday 3am
    )

    assert rush.routes[0].crowding_score > quiet.routes[0].crowding_score
    assert rush.routes[0].crowding_score - quiet.routes[0].crowding_score >= 0.3