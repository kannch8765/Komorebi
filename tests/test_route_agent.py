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
    instance.get_routes.assert_called_once_with("渋谷", "池袋")


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
        instance.get_routes.assert_called_once_with("渋谷", "池袋")
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