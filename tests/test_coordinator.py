"""Tests for the Coordinator (L1 agent)."""

from __future__ import annotations

import pytest


def test_create_coordinator_returns_agent_with_sub_agents():
    pytest.importorskip("google.adk")

    from agents.coordinator import create_coordinator
    from google.adk.agents import Agent

    coordinator = create_coordinator()
    assert isinstance(coordinator, Agent)
    assert coordinator.name == "coordinator"
    assert "gemini" in coordinator.model.lower()
    assert coordinator.instruction

    # Coordinator V2 has THREE sub-agents (Module 11): route + weather + places.
    sub_agent_names = {a.name for a in coordinator.sub_agents}
    assert sub_agent_names == {"route_agent", "weather_agent", "places_agent"}


def test_create_coordinator_custom_model_propagates_to_sub_agents():
    pytest.importorskip("google.adk")

    from agents.coordinator import create_coordinator

    coordinator = create_coordinator(model="gemini-2.5-pro")
    assert coordinator.model == "gemini-2.5-pro"
    for sub in coordinator.sub_agents:
        assert sub.model == "gemini-2.5-pro"


def test_create_coordinator_routing_rules_in_instruction():
    """Instruction should mention all 3 sub-agent names to anchor delegation."""
    pytest.importorskip("google.adk")

    from agents.coordinator import create_coordinator

    coordinator = create_coordinator()
    instruction = coordinator.instruction
    assert "route_agent" in instruction
    assert "weather_agent" in instruction
    assert "places_agent" in instruction


def test_create_coordinator_v2_routing_keywords():
    """V2 routing rules include places routing + slider keyword hints."""
    pytest.importorskip("google.adk")

    from agents.coordinator import create_coordinator

    coordinator = create_coordinator()
    instruction = coordinator.instruction
    # Places routing keywords
    assert "FIND A PLACE" in instruction or "places_agent" in instruction
    # Slider keyword hints (Japanese + English)
    assert "人混み避けたい" in instruction
    assert "急いでる" in instruction
    assert "slider = 1" in instruction or "slider=1" in instruction
    assert "slider = 5" in instruction or "slider=5" in instruction


def test_create_coordinator_embeds_exposure_comfort_when_provided():
    """When preferences are passed, the slider value appears in the instruction."""
    pytest.importorskip("google.adk")

    from agents.coordinator import create_coordinator
    from models.user_preferences import UserPreferences

    coordinator = create_coordinator(
        preferences=UserPreferences(exposure_comfort=2),
    )
    instruction = coordinator.instruction
    assert "exposure_comfort slider = 2" in instruction
    # Weights at slider=2: weight_crowding=0.675 → rounded to 0.68, weight_time=0.325 → 0.32
    assert "weight_crowding=0.68" in instruction
    assert "weight_time=0.32" in instruction


def test_create_coordinator_default_slider_when_no_preferences():
    """When preferences=None, default slider=3 appears in the instruction."""
    pytest.importorskip("google.adk")

    from agents.coordinator import create_coordinator

    coordinator = create_coordinator()
    instruction = coordinator.instruction
    assert "exposure_comfort slider = 3" in instruction
    assert "weight_crowding=0.50" in instruction
    assert "weight_time=0.50" in instruction