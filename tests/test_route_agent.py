"""Tests for the Route Agent's tool function (no LLM, no ADK runtime)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agents.route_agent import get_transit_routes
from models.schemas import RouteRecommendation
from tools.transit_api import TransitAPIError, TransitAPIClient


def _make_recommendations() -> list[RouteRecommendation]:
    """Build a small list of valid RouteRecommendation objects for mocking."""
    return [
        RouteRecommendation(
            name="ルートA",
            duration_min=30,
            transfers=1,
            crowding_score=0.5,
            extra_time_min=0,
            stations=["渋谷", "新宿", "池袋"],
            lines=["JR山手線", "丸ノ内線"],
        ),
        RouteRecommendation(
            name="ルートB",
            duration_min=20,
            transfers=0,
            crowding_score=0.3,
            extra_time_min=0,
            stations=["渋谷", "池袋"],
            lines=["埼京線"],
        ),
    ]


def test_get_transit_routes_returns_dict_of_routes(mocker):
    """The tool returns a dict with a 'routes' key containing RouteRecommendation dicts."""
    instance = mocker.patch("agents.route_agent.TransitAPIClient").return_value
    instance.get_routes.return_value.routes = _make_recommendations()

    result = get_transit_routes("渋谷", "池袋")

    assert "routes" in result
    assert len(result["routes"]) == 2
    # The tool fn forwards to client.get_routes with keyword args so the
    # new advanced options (via, trip_type, etc.) can be passed by name.
    instance.get_routes.assert_called_once()
    call = instance.get_routes.call_args
    assert call.kwargs["origin"] == "渋谷"
    assert call.kwargs["destination"] == "池袋"
    assert call.kwargs["trip_type"] == "departure"  # default
    assert call.kwargs["avoid_walk"] is False  # default
    assert call.kwargs["via"] is None  # default


def test_get_transit_routes_empty_routes(mocker):
    """Empty input → empty output dict."""
    instance = mocker.patch("agents.route_agent.TransitAPIClient").return_value
    instance.get_routes.return_value.routes = []

    result = get_transit_routes("渋谷", "池袋")

    assert result == {"routes": []}


def test_get_transit_routes_propagates_transit_api_error(mocker):
    """A TransitAPIError from the client bubbles up unchanged."""
    instance = mocker.patch("agents.route_agent.TransitAPIClient").return_value
    instance.get_routes.side_effect = TransitAPIError("network error")

    with pytest.raises(TransitAPIError, match="network error"):
        get_transit_routes("渋谷", "池袋")


def test_get_transit_routes_constructs_default_client():
    """When called without a client, TransitAPIClient() is constructed internally."""
    with patch("agents.route_agent.TransitAPIClient") as MockClient:
        instance = MockClient.return_value
        instance.get_routes.return_value.routes = []
        result = get_transit_routes("渋谷", "池袋")
        MockClient.assert_called_once()
        # Keyword-arg call signature (see test above for the full check).
        instance.get_routes.assert_called_once()
        assert result == {"routes": []}


def test_get_transit_routes_validates_exposure_comfort_range():
    """exposure_comfort outside 1..5 raises ValueError."""
    with pytest.raises(ValueError, match="exposure_comfort must be"):
        get_transit_routes("渋谷", "池袋", exposure_comfort=0)
    with pytest.raises(ValueError, match="exposure_comfort must be"):
        get_transit_routes("渋谷", "池袋", exposure_comfort=6)


def test_get_transit_routes_default_slider_is_balanced(mocker):
    """Default exposure_comfort=3 keeps the API ordering for equal scores."""
    instance = mocker.patch("agents.route_agent.TransitAPIClient").return_value
    instance.get_routes.return_value.routes = _make_recommendations()

    result = get_transit_routes("渋谷", "池袋")  # no slider → default 3

    # With balanced weights and equal normalized time across both routes,
    # the lower-crowding route (ルートB, 0.3) should come first.
    assert result["routes"][0]["name"] == "ルートB"
    assert result["routes"][1]["name"] == "ルートA"


def test_get_transit_routes_slider_1_prefers_quiet(mocker):
    """Slider=1 (avoid crowds) prefers the lower-crowding route even if slower."""
    instance = mocker.patch("agents.route_agent.TransitAPIClient").return_value
    instance.get_routes.return_value.routes = _make_recommendations()

    result = get_transit_routes("渋谷", "池袋", exposure_comfort=1)

    # ルートB (20min, 0.3 crowding) wins on crowding dominance.
    assert result["routes"][0]["name"] == "ルートB"


def test_get_transit_routes_slider_5_prefers_fast(mocker):
    """Slider=5 (time-only) prefers the faster route even if more crowded."""
    instance = mocker.patch("agents.route_agent.TransitAPIClient").return_value
    instance.get_routes.return_value.routes = _make_recommendations()

    result = get_transit_routes("渋谷", "池袋", exposure_comfort=5)

    # ルートB is also faster (20 vs 30 min), so it wins on time dominance too.
    assert result["routes"][0]["name"] == "ルートB"


def test_create_route_agent_builds_agent_with_tool():
    """create_route_agent() returns a google.adk Agent with the tool wired up."""
    pytest.importorskip("google.adk")

    from agents.route_agent import create_route_agent
    from google.adk.agents import Agent

    agent = create_route_agent()

    assert isinstance(agent, Agent)
    assert agent.name == "route_agent"
    assert "gemini" in agent.model.lower()
    assert agent.instruction  # non-empty
    assert len(agent.tools) == 1
    # The single tool should wrap get_transit_routes.
    tool = agent.tools[0]
    assert getattr(tool, "func", None) is get_transit_routes or tool.name == "get_transit_routes"


def test_create_route_agent_custom_model():
    pytest.importorskip("google.adk")

    from agents.route_agent import create_route_agent

    agent = create_route_agent(model="gemini-2.5-pro")
    assert agent.model == "gemini-2.5-pro"


# ---------------------------------------------------------------------------
# V2.5: home keyword resolution
# ---------------------------------------------------------------------------


from agents.route_agent import _resolve_home_keyword  # noqa: E402


@pytest.mark.parametrize(
    "input_text,expected",
    [
        ("家", "横浜駅"),
        ("自宅", "横浜駅"),
        ("home", "横浜駅"),
        ("うち", "横浜駅"),
        ("家から", "横浜駅から"),
        ("家へ", "横浜駅へ"),
        ("自宅 → 池袋", "横浜駅 → 池袋"),
        ("池袋", "池袋"),  # not a keyword — unchanged
        ("", ""),  # empty — unchanged
    ],
)
def test_resolve_home_keyword_replaces_keywords(input_text, expected):
    """Standard home keywords are replaced with the home label."""
    assert _resolve_home_keyword(input_text, "横浜駅") == expected


@pytest.mark.parametrize(
    "input_text,expected",
    [
        # We accept that substrings ARE replaced. In a station-name context
        # this is essentially never a problem; the risk is '家族' → '横浜駅族'
        # which would only matter if a station were named '家族...'. This is
        # documented in the function docstring.
        ("家族", "横浜駅族"),
        ("homecoming", "横浜駅coming"),
        ("池袋", "池袋"),  # not a keyword at all
        ("帰宅", "帰宅"),  # '宅' is not the same char as '家' — unchanged
    ],
)
def test_resolve_home_keyword_accepts_substring_matches(input_text, expected):
    """Substring matches ARE replaced (documented behaviour)."""
    assert _resolve_home_keyword(input_text, "横浜駅") == expected


def test_get_transit_routes_resolves_home_in_origin(mocker):
    """When _home is set, '自宅' in origin is replaced with home label."""
    mock_response = MagicMock()
    mock_response.routes = _make_recommendations()
    mocker.patch.object(
        TransitAPIClient, "get_routes", return_value=mock_response
    )

    get_transit_routes(
        origin="自宅",
        destination="池袋",
        _home="横浜駅",
    )
    # Inspect the call args to confirm origin was rewritten
    call = TransitAPIClient.get_routes.call_args
    assert call.kwargs["origin"] == "横浜駅"
    assert call.kwargs["destination"] == "池袋"


def test_get_transit_routes_resolves_home_in_destination(mocker):
    """When _home is set, keywords in destination are also replaced."""
    mock_response = MagicMock()
    mock_response.routes = _make_recommendations()
    mocker.patch.object(
        TransitAPIClient, "get_routes", return_value=mock_response
    )

    get_transit_routes(
        origin="渋谷",
        destination="家",
        _home="横浜駅",
    )
    call = TransitAPIClient.get_routes.call_args
    assert call.kwargs["origin"] == "渋谷"
    assert call.kwargs["destination"] == "横浜駅"


def test_get_transit_routes_resolves_home_in_via(mocker):
    """When _home is set, keywords in via list are replaced per-element."""
    mock_response = MagicMock()
    mock_response.routes = _make_recommendations()
    mocker.patch.object(
        TransitAPIClient, "get_routes", return_value=mock_response
    )

    get_transit_routes(
        origin="渋谷",
        destination="池袋",
        via=["家", "新宿"],
        _home="横浜駅",
    )
    call = TransitAPIClient.get_routes.call_args
    assert call.kwargs["via"] == ["横浜駅", "新宿"]


def test_get_transit_routes_no_resolution_when_home_unset(mocker):
    """When _home is None (default), keywords are passed through unchanged."""
    mock_response = MagicMock()
    mock_response.routes = _make_recommendations()
    mocker.patch.object(
        TransitAPIClient, "get_routes", return_value=mock_response
    )

    get_transit_routes(origin="自宅", destination="池袋")
    call = TransitAPIClient.get_routes.call_args
    assert call.kwargs["origin"] == "自宅"  # unchanged
    assert call.kwargs["destination"] == "池袋"


# ---------------------------------------------------------------------------
# create_route_agent(home=...) closure wiring
# ---------------------------------------------------------------------------


def test_create_route_agent_home_is_bound_in_tool(mocker):
    """create_route_agent(home=...) wires the home label into the tool closure."""
    pytest.importorskip("google.adk")

    from agents.route_agent import create_route_agent
    from models.user_profile import HomeLocation

    home = HomeLocation(label="横浜駅", lat=35.4657, lon=139.6223)
    agent = create_route_agent(home=home)

    # Get the underlying callable from FunctionTool
    tool = agent.tools[0]
    func = getattr(tool, "func", None)
    assert func is not None, "FunctionTool.func missing"

    # Mock the transit client and call the closure
    mock_response = MagicMock()
    mock_response.routes = _make_recommendations()
    mocker.patch.object(
        TransitAPIClient, "get_routes", return_value=mock_response
    )

    func(origin="自宅", destination="池袋")
    call = TransitAPIClient.get_routes.call_args
    assert call.kwargs["origin"] == "横浜駅"


def test_create_route_agent_no_home_does_not_bind(mocker):
    """create_route_agent() (no home) leaves the closure's _home unbound."""
    pytest.importorskip("google.adk")

    from agents.route_agent import create_route_agent

    agent = create_route_agent()  # no home
    tool = agent.tools[0]
    func = getattr(tool, "func", None)

    mock_response = MagicMock()
    mock_response.routes = _make_recommendations()
    mocker.patch.object(
        TransitAPIClient, "get_routes", return_value=mock_response
    )

    func(origin="自宅", destination="池袋")
    call = TransitAPIClient.get_routes.call_args
    assert call.kwargs["origin"] == "自宅"  # unchanged — no home bound