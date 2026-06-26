"""Tests for the Route Agent's tool function (no LLM, no ADK runtime)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agents.route_agent import get_transit_routes
from tools.transit_api import TransitAPIError, TransitAPIClient


def _mock_client(routes: list[dict] | None = None, side_effect: Exception | None = None):
    """Build a mock TransitAPIClient whose get_routes returns the given dict list."""
    mock = MagicMock(spec=TransitAPIClient)
    if side_effect is not None:
        mock.get_routes.side_effect = side_effect
    else:
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {"routes": routes or []}
        mock.get_routes.return_value = mock_response
    return mock


def test_get_transit_routes_returns_dict_of_routes(mocker):
    routes = [
        {
            "name": "最短ルート",
            "duration_min": 30,
            "transfers": 1,
            "crowding_score": 0.5,
            "extra_time_min": 0,
            "stations": ["渋谷", "新宿", "池袋"],
            "lines": ["JR山手線", "丸ノ内線"],
        }
    ]
    instance = mocker.patch("agents.route_agent.TransitAPIClient").return_value
    instance.get_routes.return_value = MagicMock(model_dump=lambda: {"routes": routes})

    result = get_transit_routes("渋谷", "池袋")

    assert result == {"routes": routes}
    instance.get_routes.assert_called_once_with("渋谷", "池袋")


def test_get_transit_routes_empty_routes(mocker):
    instance = mocker.patch("agents.route_agent.TransitAPIClient").return_value
    instance.get_routes.return_value = MagicMock(model_dump=lambda: {"routes": []})

    result = get_transit_routes("渋谷", "池袋")

    assert result == {"routes": []}


def test_get_transit_routes_propagates_transit_api_error(mocker):
    instance = mocker.patch("agents.route_agent.TransitAPIClient").return_value
    instance.get_routes.side_effect = TransitAPIError("network error")

    with pytest.raises(TransitAPIError, match="network error"):
        get_transit_routes("渋谷", "池袋")


def test_get_transit_routes_constructs_default_client():
    """When called without a client, TransitAPIClient() is constructed internally."""
    with patch("agents.route_agent.TransitAPIClient") as MockClient:
        instance = MockClient.return_value
        instance.get_routes.return_value = MagicMock(model_dump=lambda: {"routes": []})
        result = get_transit_routes("渋谷", "池袋")
        MockClient.assert_called_once()
        instance.get_routes.assert_called_once_with("渋谷", "池袋")
        assert result == {"routes": []}


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