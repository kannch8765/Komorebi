"""Hermetic tests for tools.transit_api.TransitAPIClient."""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _ensure_models_schemas():
    """Inject a minimal models.schemas module if Module 1 has not landed yet."""
    if "models.schemas" in sys.modules:
        return

    try:
        importlib.import_module("models.schemas")
        return
    except ModuleNotFoundError:
        pass

    try:
        import pydantic  # noqa: F401
        _impl = "pydantic"
    except ModuleNotFoundError:
        _impl = "dataclass"

    if _impl == "pydantic":
        from pydantic import BaseModel

        class RouteRecommendation(BaseModel):
            name: str
            duration_min: int
            transfers: int
            crowding_score: float = 0.5
            extra_time_min: int = 0
            stations: list[str] = []
            lines: list[str] = []

        class RouteResponse(BaseModel):
            routes: list[RouteRecommendation] = []
    else:
        from dataclasses import dataclass, field

        @dataclass
        class RouteRecommendation:
            name: str
            duration_min: int
            transfers: int
            crowding_score: float = 0.5
            extra_time_min: int = 0
            stations: list[str] = field(default_factory=list)
            lines: list[str] = field(default_factory=list)

        @dataclass
        class RouteResponse:
            routes: list[RouteRecommendation] = field(default_factory=list)

    models_pkg = types.ModuleType("models")
    models_pkg.__path__ = []  # mark as package
    schemas_mod = types.ModuleType("models.schemas")
    schemas_mod.RouteRecommendation = RouteRecommendation
    schemas_mod.RouteResponse = RouteResponse
    sys.modules["models"] = models_pkg
    sys.modules["models.schemas"] = schemas_mod

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))


_ensure_models_schemas()

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.transit_api import TransitAPIError, TransitAPIClient  # noqa: E402


def _mock_response(mocker, json_payload, status: int = 200):
    """Build a mock requests.Response and patch requests.Session.get."""
    mock_response = mocker.Mock()
    mock_response.json.return_value = json_payload
    mock_response.status_code = status

    def _raise_for_status():
        if status >= 400:
            import requests

            raise requests.HTTPError(f"HTTP {status}")

    mock_response.raise_for_status.side_effect = _raise_for_status

    mocker.patch("requests.Session.get", return_value=mock_response)
    return mock_response


def test_successful_route_fetch(mocker):
    _mock_response(
        mocker,
        {
            "routes": [
                {
                    "name": "最短ルート",
                    "duration_min": 30,
                    "transfers": 1,
                    "crowding_score": 0.5,
                    "extra_time_min": 0,
                    "stations": ["渋谷", "新宿"],
                    "lines": ["JR山手線"],
                }
            ]
        },
    )

    client = TransitAPIClient()
    result = client.get_routes("渋谷", "池袋")

    assert len(result.routes) == 1
    assert result.routes[0].name == "最短ルート"
    assert result.routes[0].duration_min == 30
    assert result.routes[0].transfers == 1
    assert result.routes[0].crowding_score == 0.5
    assert result.routes[0].extra_time_min == 0
    assert result.routes[0].stations == ["渋谷", "新宿"]
    assert result.routes[0].lines == ["JR山手線"]


def test_multiple_routes_parsed(mocker):
    _mock_response(
        mocker,
        {
            "routes": [
                {
                    "name": "最速",
                    "duration_min": 25,
                    "transfers": 1,
                    "stations": ["渋谷", "新宿", "池袋"],
                    "lines": ["JR山手線"],
                },
                {
                    "name": "ゆっくり",
                    "duration_min": 40,
                    "transfers": 2,
                    "crowding_score": 0.2,
                    "extra_time_min": 15,
                    "stations": ["渋谷", "表参道", "池袋"],
                    "lines": ["千代田線", "有楽町線"],
                },
            ]
        },
    )

    client = TransitAPIClient()
    result = client.get_routes("渋谷", "池袋")

    assert len(result.routes) == 2
    assert [r.name for r in result.routes] == ["最速", "ゆっくり"]
    # defaults applied when fields missing
    assert result.routes[0].crowding_score == 0.5
    assert result.routes[0].extra_time_min == 0
    assert result.routes[1].crowding_score == 0.2
    assert result.routes[1].extra_time_min == 15


def test_empty_routes_list(mocker):
    _mock_response(mocker, {"routes": []})

    client = TransitAPIClient()
    result = client.get_routes("渋谷", "池袋")

    assert result.routes == []


def test_http_error_raises(mocker):
    _mock_response(mocker, {"detail": "server is sad"}, status=500)

    client = TransitAPIClient()
    with pytest.raises(TransitAPIError, match="HTTP 500"):
        client.get_routes("渋谷", "池袋")


def test_network_error_raises(mocker):
    import requests

    mocker.patch(
        "requests.Session.get",
        side_effect=requests.ConnectionError("boom"),
    )

    client = TransitAPIClient()
    with pytest.raises(TransitAPIError, match="network error"):
        client.get_routes("渋谷", "池袋")


def test_timeout_raises(mocker):
    import requests

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


def test_sends_origin_and_destination_as_query_params(mocker):
    mock_response = mocker.Mock()
    mock_response.json.return_value = {"routes": []}
    mock_response.raise_for_status.return_value = None

    mock_get = mocker.patch("requests.Session.get", return_value=mock_response)

    client = TransitAPIClient(base_url="https://api.transit.ls8h.com")
    client.get_routes("渋谷", "池袋")

    # call_args unpacks as (positional_args_tuple, kwargs_dict); URL is args[0]
    called_args, called_kwargs = mock_get.call_args
    assert called_args[0] == "https://api.transit.ls8h.com/api/v1/routes"
    assert called_kwargs["params"] == {"origin": "渋谷", "destination": "池袋"}
    assert called_kwargs["timeout"] == 30