"""Tests for the Places Agent's tool function (no LLM, no ADK runtime)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agents.places_agent import TOKYO_COORDS, search_places


# ---------------------------------------------------------------------------
# search_places tool function
# ---------------------------------------------------------------------------


def test_search_places_calls_places_api_client(mocker):
    """search_places constructs PlacesAPIClient and forwards args."""
    instance = mocker.patch("tools.places_api.PlacesAPIClient").return_value
    instance.nearby_search.return_value.model_dump.return_value = {
        "results": [{"place_id": "abc", "name": "Test Cafe"}]
    }

    result = search_places(35.6580, 139.7016, "cafe", radius_m=300, max_results=3)

    instance.nearby_search.assert_called_once_with(
        lat=35.6580, lon=139.7016, place_type="cafe",
        radius_m=300, max_results=3,
    )
    assert result == {"results": [{"place_id": "abc", "name": "Test Cafe"}]}


def test_search_places_default_args(mocker):
    """Default radius=500m, max_results=5."""
    instance = mocker.patch("tools.places_api.PlacesAPIClient").return_value
    instance.nearby_search.return_value.model_dump.return_value = {"results": []}

    search_places(35.6580, 139.7016, "park")

    instance.nearby_search.assert_called_once_with(
        lat=35.6580, lon=139.7016, place_type="park",
        radius_m=500, max_results=5,
    )


def test_search_places_propagates_places_api_error(mocker):
    """A PlacesAPIError from the client bubbles up unchanged."""
    from tools.places_api import PlacesAPIError

    mocker.patch(
        "tools.places_api.PlacesAPIClient",
        side_effect=PlacesAPIError("GOOGLE_PLACES_API_KEY is not set"),
    )

    with pytest.raises(PlacesAPIError, match="GOOGLE_PLACES_API_KEY is not set"):
        search_places(35.6580, 139.7016, "cafe")


# ---------------------------------------------------------------------------
# Tokyo coord table
# ---------------------------------------------------------------------------


def test_tokyo_coords_has_common_stations():
    """The hardcoded coord table should cover the most common Tokyo stations."""
    expected = ["渋谷", "新宿", "東京", "池袋", "品川", "上野", "横浜"]
    for station in expected:
        assert station in TOKYO_COORDS, f"missing coord for {station}"
        lat, lon = TOKYO_COORDS[station]
        # Sanity: should be in Tokyo's bounding box.
        assert 35.4 < lat < 36.0
        assert 139.4 < lon < 140.0


def test_tokyo_coords_values_are_reasonable():
    """Specific known coords should be approximately correct."""
    # Shibuya Station is at ~35.6580, 139.7016
    assert TOKYO_COORDS["渋谷"] == pytest.approx((35.6580, 139.7016), abs=1e-3)
    # Tokyo Station is at ~35.6812, 139.7671
    assert TOKYO_COORDS["東京"] == pytest.approx((35.6812, 139.7671), abs=1e-3)


# ---------------------------------------------------------------------------
# ADK agent factory
# ---------------------------------------------------------------------------


def test_create_places_agent_builds_agent_with_tool():
    """create_places_agent() returns a google.adk Agent with the tool wired up."""
    pytest.importorskip("google.adk")

    from agents.places_agent import create_places_agent
    from google.adk.agents import Agent

    agent = create_places_agent()

    assert isinstance(agent, Agent)
    assert agent.name == "places_agent"
    assert "gemini" in agent.model.lower()
    assert agent.instruction  # non-empty
    assert len(agent.tools) == 1
    # The single tool should wrap search_places.
    tool = agent.tools[0]
    assert getattr(tool, "func", None) is search_places or tool.name == "search_places"


def test_create_places_agent_custom_model():
    pytest.importorskip("google.adk")

    from agents.places_agent import create_places_agent

    agent = create_places_agent(model="gemini-2.5-pro")
    assert agent.model == "gemini-2.5-pro"


def test_create_places_agent_instruction_includes_coord_table():
    """The agent instruction should embed the Tokyo coord table so the LLM
    can resolve district/station mentions without a geocoding tool."""
    pytest.importorskip("google.adk")

    from agents.places_agent import create_places_agent

    agent = create_places_agent()
    # At least Shibuya + Shinjuku + Tokyo should be in the coord table in the instruction
    assert "渋谷" in agent.instruction
    assert "新宿" in agent.instruction
    assert "東京" in agent.instruction