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
    """Pop mock responses off a FIFO queue in call order, or by URL prefix."""

    def __init__(self, mocker):
        self.mocker = mocker
        self.queue: list[dict | Exception] = []
        self.url_responses: dict[str, dict | Exception] = {}
        self.calls: list[tuple[str, dict]] = []
        self._patched = False

    def push(self, payload_or_exc: dict | Exception) -> "_MockQueue":
        """FIFO mode — used for the original 2-step (suggest, suggest, plan) flow."""
        self.queue.append(payload_or_exc)
        return self

    def register(self, url_substring: str, payload_or_exc: dict | Exception) -> "_MockQueue":
        """URL-keyed mode — match a substring of the URL and return this payload.

        Used when a test hits endpoints that aren't the (suggest, suggest, plan)
        2-step (e.g. station info, departures, places/suggest, places/reverse).
        URL-keyed entries take priority over the FIFO queue.
        """
        self.url_responses[url_substring] = payload_or_exc
        return self

    def patch(self):
        """Wire `requests.Session.get` to dispatch by URL key first, then FIFO."""
        if self._patched:
            return
        self._patched = True

        def _side_effect(url, **kwargs):
            self.calls.append((url, kwargs))
            # URL-keyed responses first (most specific).
            for substring, payload_or_exc in self.url_responses.items():
                if substring in url:
                    if isinstance(payload_or_exc, Exception):
                        raise payload_or_exc
                    return self._build_response(payload_or_exc)
            # Fall back to FIFO.
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


# ─── New params on /api/v1/plan ─────────────────────────────────────────────


def test_via_param_is_passed_to_api(mocker):
    """via=['id1', 'id2'] goes into the request as repeated via= query params."""
    q = _MockQueue(mocker)
    q.push(_shibuya_suggest_payload())
    q.push(_ikebukuro_suggest_payload())
    q.push(_saikyo_plan_payload())
    q.patch()

    client = TransitAPIClient()
    client.get_routes(
        "渋谷", "池袋",
        via=["scraped-id:Shinjuku", "scraped-id:Ebisu"],
    )

    plan_params = q.calls[2][1]["params"]
    assert plan_params["via"] == ["scraped-id:Shinjuku", "scraped-id:Ebisu"]


def test_trip_type_arrival_is_passed(mocker):
    """trip_type='arrival' goes into the request as type=arrival."""
    q = _MockQueue(mocker)
    q.push(_shibuya_suggest_payload())
    q.push(_ikebukuro_suggest_payload())
    q.push(_saikyo_plan_payload())
    q.patch()

    client = TransitAPIClient()
    client.get_routes("渋谷", "池袋", trip_type="arrival")

    assert q.calls[2][1]["params"]["type"] == "arrival"


def test_trip_type_last_is_passed(mocker):
    """trip_type='last' (終電) goes into the request as type=last."""
    q = _MockQueue(mocker)
    q.push(_shibuya_suggest_payload())
    q.push(_ikebukuro_suggest_payload())
    q.push({"journeys": []})
    q.patch()

    client = TransitAPIClient()
    client.get_routes("渋谷", "池袋", trip_type="last")

    assert q.calls[2][1]["params"]["type"] == "last"


def test_invalid_trip_type_raises(mocker):
    """trip_type outside the enum raises BEFORE making any HTTP call."""
    q = _MockQueue(mocker)
    q.patch()  # no payloads queued — the validation must short-circuit

    client = TransitAPIClient()
    with pytest.raises(TransitAPIError, match="invalid trip_type"):
        client.get_routes_by_id(
            from_id="x", to_id="y", trip_type="now",
        )
    # No HTTP call should have been made (fail-fast on bad input).
    assert q.calls == []


def test_too_many_via_raises(mocker):
    """via accepts at most 3 waypoints; 4 raises before any HTTP call."""
    client = TransitAPIClient()
    with pytest.raises(TransitAPIError, match="at most 3 waypoints"):
        client.get_routes_by_id(
            from_id="x", to_id="y",
            via=["a", "b", "c", "d"],
        )


def test_avoid_modes_is_joined_with_commas(mocker):
    """avoid_modes=['bus', 'air'] → 'avoidModes=bus,air' (single string)."""
    q = _MockQueue(mocker)
    q.push(_shibuya_suggest_payload())
    q.push(_ikebukuro_suggest_payload())
    q.push(_saikyo_plan_payload())
    q.patch()

    client = TransitAPIClient()
    client.get_routes("渋谷", "池袋", avoid_modes=["bus", "air"])

    assert q.calls[2][1]["params"]["avoidModes"] == "bus,air"


def test_allow_modes_is_joined_with_commas(mocker):
    """allow_modes=['rail', 'subway'] → 'allowModes=rail,subway'."""
    q = _MockQueue(mocker)
    q.push(_shibuya_suggest_payload())
    q.push(_ikebukuro_suggest_payload())
    q.push(_saikyo_plan_payload())
    q.patch()

    client = TransitAPIClient()
    client.get_routes("渋谷", "池袋", allow_modes=["rail", "subway"])

    assert q.calls[2][1]["params"]["allowModes"] == "rail,subway"


def test_avoid_walk_true_becomes_string_true(mocker):
    """avoid_walk=True → 'avoidWalk=true' (string, NOT bool)."""
    q = _MockQueue(mocker)
    q.push(_shibuya_suggest_payload())
    q.push(_ikebukuro_suggest_payload())
    q.push(_saikyo_plan_payload())
    q.patch()

    client = TransitAPIClient()
    client.get_routes("渋谷", "池袋", avoid_walk=True)

    assert q.calls[2][1]["params"]["avoidWalk"] == "true"


def test_avoid_walk_default_is_false(mocker):
    """Default avoid_walk=False → 'avoidWalk=false'."""
    q = _MockQueue(mocker)
    q.push(_shibuya_suggest_payload())
    q.push(_ikebukuro_suggest_payload())
    q.push(_saikyo_plan_payload())
    q.patch()

    client = TransitAPIClient()
    client.get_routes("渋谷", "池袋")

    assert q.calls[2][1]["params"]["avoidWalk"] == "false"


def test_max_transfers_passed_when_set(mocker):
    """max_transfers=0 → 'maxTransfers=0' (for 乗り換えたくない queries)."""
    q = _MockQueue(mocker)
    q.push(_shibuya_suggest_payload())
    q.push(_ikebukuro_suggest_payload())
    q.push(_saikyo_plan_payload())
    q.patch()

    client = TransitAPIClient()
    client.get_routes("渋谷", "池袋", max_transfers=0)

    assert q.calls[2][1]["params"]["maxTransfers"] == 0


def test_max_transfers_out_of_range_raises():
    """max_transfers outside 0..8 raises before any HTTP call."""
    client = TransitAPIClient()
    with pytest.raises(TransitAPIError, match="max_transfers must be in 0..8"):
        client.get_routes_by_id(from_id="x", to_id="y", max_transfers=9)
    with pytest.raises(TransitAPIError, match="max_transfers must be in 0..8"):
        client.get_routes_by_id(from_id="x", to_id="y", max_transfers=-1)


def test_date_and_time_passed_through(mocker):
    """date='20260627', time='18:00' go into the request verbatim."""
    q = _MockQueue(mocker)
    q.push(_shibuya_suggest_payload())
    q.push(_ikebukuro_suggest_payload())
    q.push(_saikyo_plan_payload())
    q.patch()

    client = TransitAPIClient()
    client.get_routes("渋谷", "池袋", date="20260627", time="18:00", trip_type="arrival")

    params = q.calls[2][1]["params"]
    assert params["date"] == "20260627"
    assert params["time"] == "18:00"
    assert params["type"] == "arrival"


def test_labels_passed_when_provided(mocker):
    """from_label / to_label / via_label go into the request as the *Label params."""
    q = _MockQueue(mocker)
    q.push(_shibuya_suggest_payload())
    q.push(_ikebukuro_suggest_payload())
    q.push(_saikyo_plan_payload())
    q.patch()

    client = TransitAPIClient()
    client.get_routes(
        "渋谷", "池袋",
        from_label="Shibuya (渋谷)",
        to_label="Ikebukuro (池袋)",
        via=["scraped-id:Shinjuku"],
        via_label=["Shinjuku (新宿)"],
    )

    params = q.calls[2][1]["params"]
    assert params["fromLabel"] == "Shibuya (渋谷)"
    assert params["toLabel"] == "Ikebukuro (池袋)"
    assert params["via"] == ["scraped-id:Shinjuku"]
    assert params["viaLabel"] == ["Shinjuku (新宿)"]


def test_omitted_optional_params_not_in_request(mocker):
    """When optional params are None / default, they should NOT be in the query."""
    q = _MockQueue(mocker)
    q.push(_shibuya_suggest_payload())
    q.push(_ikebukuro_suggest_payload())
    q.push(_saikyo_plan_payload())
    q.patch()

    client = TransitAPIClient()
    client.get_routes("渋谷", "池袋")  # all defaults

    params = q.calls[2][1]["params"]
    assert "via" not in params
    assert "viaLabel" not in params
    assert "fromLabel" not in params
    assert "toLabel" not in params
    assert "date" not in params
    assert "time" not in params
    assert "allowModes" not in params
    assert "avoidModes" not in params
    assert "maxTransfers" not in params
    # type, numItineraries, avoidWalk always present (have defaults).
    assert params["type"] == "departure"
    assert params["numItineraries"] == 3
    assert params["avoidWalk"] == "false"


# ─── New endpoint methods ───────────────────────────────────────────────────


def test_suggest_places_calls_places_suggest_endpoint(mocker):
    """suggest_places('渋谷') → GET /api/v1/places/suggest?q=渋谷."""
    q = _MockQueue(mocker)
    q.register(
        "/api/v1/places/suggest",
        {
            "places": [
                {"id": "facility-x", "name": "代官山蔦屋書店", "kind": "facility"},
                {"id": "addr-y", "name": "渋谷区代官山町", "kind": "address"},
            ]
        },
    )
    q.patch()

    client = TransitAPIClient()
    results = client.suggest_places("代官山", limit=5)

    assert len(results) == 2
    assert results[0]["name"] == "代官山蔦屋書店"
    # The URL had the right query.
    assert "/api/v1/places/suggest" in q.calls[0][0]
    assert q.calls[0][1]["params"]["q"] == "代官山"
    assert q.calls[0][1]["params"]["limit"] == 5


def test_suggest_places_empty_list(mocker):
    """Empty response → empty list (not an error)."""
    q = _MockQueue(mocker)
    q.register("/api/v1/places/suggest", {"places": []})
    q.patch()

    client = TransitAPIClient()
    assert client.suggest_places("何もない") == []


def test_reverse_geocode_calls_places_reverse_endpoint(mocker):
    """reverse_geocode(35.658, 139.701) → GET /api/v1/places/reverse."""
    q = _MockQueue(mocker)
    q.register(
        "/api/v1/places/reverse",
        {
            "places": [
                {"id": "scraped-id:Shibuya", "name": "渋谷", "distance": 120}
            ]
        },
    )
    q.patch()

    client = TransitAPIClient()
    results = client.reverse_geocode(35.658, 139.701, radius_meters=200, limit=3)

    assert len(results) == 1
    assert results[0]["name"] == "渋谷"
    assert "/api/v1/places/reverse" in q.calls[0][0]
    assert q.calls[0][1]["params"]["lat"] == 35.658
    assert q.calls[0][1]["params"]["lon"] == 139.701
    assert q.calls[0][1]["params"]["radiusMeters"] == 200
    assert q.calls[0][1]["params"]["limit"] == 3


def test_get_station_info_calls_stations_endpoint(mocker):
    """get_station_info('scraped-id:Shibuya') → GET /api/v1/stations/{id}."""
    q = _MockQueue(mocker)
    q.register(
        "/api/v1/stations/",
        {
            "id": "scraped-id:Shibuya",
            "name": "渋谷",
            "platforms": [{"name": "1番線"}, {"name": "2番線"}],
            "routes": ["JR山手線", "JR埼京線", "東京メトロ副都心線"],
        },
    )
    q.patch()

    client = TransitAPIClient()
    info = client.get_station_info("scraped-id:Shibuya")

    assert info["name"] == "渋谷"
    assert len(info["platforms"]) == 2
    assert "JR山手線" in info["routes"]
    assert "/api/v1/stations/" in q.calls[0][0]


def test_get_departures_calls_departures_endpoint(mocker):
    """get_departures(id) → GET /api/v1/stations/{id}/departures."""
    q = _MockQueue(mocker)
    q.register(
        "/departures",
        {
            "departures": [
                {"routeName": "JR山手線", "headsign": "池袋方面", "departureSecs": 77000},
                {"routeName": "東京メトロ銀座線", "headsign": "浅草方面", "departureSecs": 77240},
            ]
        },
    )
    q.patch()

    client = TransitAPIClient()
    deps = client.get_departures("scraped-id:Shibuya", date="20260627", time="21:30", limit=10)

    assert len(deps) == 2
    assert deps[0]["routeName"] == "JR山手線"
    params = q.calls[0][1]["params"]
    assert params["date"] == "20260627"
    assert params["time"] == "21:30"
    assert params["limit"] == 10


def test_get_departures_tolerates_list_response(mocker):
    """Some feeds may return a list directly. The client should tolerate both."""
    q = _MockQueue(mocker)
    q.register("/departures", [{"routeName": "X"}])
    q.patch()

    client = TransitAPIClient()
    deps = client.get_departures("scraped-id:Shibuya")

    assert deps == [{"routeName": "X"}]