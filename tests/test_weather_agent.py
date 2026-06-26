"""Tests for the Weather Agent's tool function (no LLM, no ADK runtime)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agents.weather_agent import get_current_weather
from tools.weather_api import TOKYO_LAT, TOKYO_LON, WeatherAPIClient, WeatherAPIError


def _mock_client(payload: dict | None = None, side_effect: Exception | None = None):
    """Build a mock WeatherAPIClient whose get_weather returns the given dict."""
    mock = MagicMock(spec=WeatherAPIClient)
    if side_effect is not None:
        mock.get_weather.side_effect = side_effect
    else:
        mock_response = MagicMock()
        mock_response.model_dump.return_value = payload or {
            "weather": "晴れ",
            "temp_c": 26.0,
            "rain_probability": 0.1,
            "outdoor_suitable": True,
        }
        mock.get_weather.return_value = mock_response
    return mock


def test_get_current_weather_uses_tokyo_by_default():
    client = _mock_client()
    result = get_current_weather(client=client)
    assert "weather" in result
    client.get_weather.assert_called_once_with(TOKYO_LAT, TOKYO_LON)


def test_get_current_weather_uses_provided_coords():
    client = _mock_client()
    get_current_weather(lat=34.7, lon=135.5, client=client)
    client.get_weather.assert_called_once_with(34.7, 135.5)


def test_get_current_weather_only_lat_overrides():
    """Partial override: lat given, lon falls back to default."""
    client = _mock_client()
    get_current_weather(lat=34.7, client=client)
    client.get_weather.assert_called_once_with(34.7, TOKYO_LON)


def test_get_current_weather_returns_payload_dict():
    payload = {
        "weather": "雨",
        "temp_c": 22.0,
        "rain_probability": 0.8,
        "outdoor_suitable": False,
    }
    client = _mock_client(payload=payload)
    result = get_current_weather(client=client)
    assert result == payload


def test_get_current_weather_propagates_weather_api_error():
    client = _mock_client(side_effect=WeatherAPIError("network error"))
    with pytest.raises(WeatherAPIError, match="network error"):
        get_current_weather(client=client)


def test_create_weather_agent_builds_agent_with_tool():
    pytest.importorskip("google.adk")

    from agents.weather_agent import create_weather_agent
    from google.adk.agents import Agent

    agent = create_weather_agent()
    assert isinstance(agent, Agent)
    assert agent.name == "weather_agent"
    assert "gemini" in agent.model.lower()
    assert agent.instruction
    assert len(agent.tools) == 1


def test_create_weather_agent_custom_model():
    pytest.importorskip("google.adk")

    from agents.weather_agent import create_weather_agent

    agent = create_weather_agent(model="gemini-2.5-pro")
    assert agent.model == "gemini-2.5-pro"