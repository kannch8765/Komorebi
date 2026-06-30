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


# ---------------------------------------------------------------------------
# Home location wiring (V2.5 personal context)
# ---------------------------------------------------------------------------


def test_create_coordinator_no_home_when_not_provided():
    """When home=None, no home hint is injected into the instruction."""
    pytest.importorskip("google.adk")

    from agents.coordinator import create_coordinator

    coordinator = create_coordinator()
    instruction = coordinator.instruction
    assert "HARD RULE — home resolution" not in instruction
    assert "The user's home is" not in instruction


def test_create_coordinator_embeds_home_when_provided():
    """When home is passed, the label + coords appear in the instruction."""
    pytest.importorskip("google.adk")

    from agents.coordinator import create_coordinator
    from models.user_profile import HomeLocation

    home = HomeLocation(label="横浜駅", lat=35.4657, lon=139.6223)
    coordinator = create_coordinator(home=home)
    instruction = coordinator.instruction
    assert "The user's home is 横浜駅" in instruction
    assert "lat=35.4657" in instruction
    assert "lon=139.6223" in instruction


def test_create_coordinator_home_hint_mentions_resolution_keywords():
    """Home hint should list the keywords the LLM should resolve to home."""
    pytest.importorskip("google.adk")

    from agents.coordinator import create_coordinator
    from models.user_profile import HomeLocation

    home = HomeLocation(label="横浜駅", lat=35.4657, lon=139.6223)
    coordinator = create_coordinator(home=home)
    instruction = coordinator.instruction
    # Each of these Japanese/English keywords should appear in the hint
    for keyword in ("家", "自宅", "home"):
        assert keyword in instruction, f"home hint missing keyword {keyword!r}"


def test_create_coordinator_home_hint_gives_resolution_examples():
    """Home hint should give concrete examples of how to resolve '家' queries."""
    pytest.importorskip("google.adk")

    from agents.coordinator import create_coordinator
    from models.user_profile import HomeLocation

    home = HomeLocation(label="横浜駅", lat=35.4657, lon=139.6223)
    coordinator = create_coordinator(home=home)
    instruction = coordinator.instruction
    # Routing example: '家から池袋' → origin=横浜駅
    assert "origin='横浜駅'" in instruction
    # Places example: use literal lat/lon
    assert "lat=35.4657" in instruction and "lon=139.6223" in instruction
    assert "places_agent" in instruction


def test_create_coordinator_home_hint_is_imperative():
    """V2.5: the home hint uses MUST / DO NOT to make intent unambiguous."""
    pytest.importorskip("google.adk")

    from agents.coordinator import create_coordinator
    from models.user_profile import HomeLocation

    home = HomeLocation(label="横浜駅", lat=35.4657, lon=139.6223)
    coordinator = create_coordinator(home=home)
    instruction = coordinator.instruction
    assert "MUST" in instruction
    assert "DO NOT" in instruction


def test_create_coordinator_home_and_preferences_combine():
    """home + preferences should both appear in the instruction."""
    pytest.importorskip("google.adk")

    from agents.coordinator import create_coordinator
    from models.user_preferences import UserPreferences
    from models.user_profile import HomeLocation

    home = HomeLocation(label="横浜駅", lat=35.4657, lon=139.6223)
    prefs = UserPreferences(exposure_comfort=2)
    coordinator = create_coordinator(preferences=prefs, home=home)
    instruction = coordinator.instruction
    # Both pieces are present
    assert "The user's home is 横浜駅" in instruction
    assert "exposure_comfort slider = 2" in instruction
    assert "weight_crowding=0.68" in instruction


def test_create_coordinator_sub_agents_unaffected_by_home():
    """home parameter must not change which sub-agents are wired up."""
    pytest.importorskip("google.adk")

    from agents.coordinator import create_coordinator
    from models.user_profile import HomeLocation

    home = HomeLocation(label="横浜駅", lat=35.4657, lon=139.6223)
    coordinator = create_coordinator(home=home)
    sub_agent_names = {a.name for a in coordinator.sub_agents}
    assert sub_agent_names == {"route_agent", "weather_agent", "places_agent"}


# ---------------------------------------------------------------------------
# Crowding routing rule (post-V2.5 patterns test)
# ---------------------------------------------------------------------------


def test_create_coordinator_crowding_rule_lists_keywords():
    """Crowding routing rule should enumerate the keywords that trigger it."""
    pytest.importorskip("google.adk")

    from agents.coordinator import create_coordinator

    coordinator = create_coordinator()
    instruction = coordinator.instruction
    # All four Japanese keywords + two English ones must appear in the rule.
    for keyword in ("混み", "混雑", "人多い", "空いてる", "crowded", "busy"):
        assert keyword in instruction, f"crowding rule missing keyword {keyword!r}"


def test_create_coordinator_crowding_rule_mandates_route_agent():
    """When crowding keywords appear, the LLM MUST delegate to route_agent
    (not answer with general knowledge about how crowded a station is)."""
    pytest.importorskip("google.adk")

    from agents.coordinator import create_coordinator

    coordinator = create_coordinator()
    instruction = coordinator.instruction
    assert "crowding_score" in instruction, (
        "crowding rule should reference crowding_score (the real data field)"
    )
    assert "general knowledge" in instruction.lower(), (
        "crowding rule should explicitly forbid general-knowledge answers"
    )


# ---------------------------------------------------------------------------
# Time-budget routing rule (post-V2.5 patterns test)
# ---------------------------------------------------------------------------


def test_create_coordinator_time_budget_rule_lists_keywords():
    """Time-budget rule should enumerate unit-based keywords (broader than
    digit matching) so the LLM triggers on '時間内' / '分以内' / 'N時間' /
    'within X minutes' etc. — not just on the literal letter N."""
    pytest.importorskip("google.adk")

    from agents.coordinator import create_coordinator

    coordinator = create_coordinator()
    instruction = coordinator.instruction
    # Broader keyword set per Fix 3 refinement: match time UNITS, not digits.
    for keyword in ("時間内", "分以内", "分で", "時間で", "以内", "N時間", "within X minutes"):
        assert keyword in instruction, f"time-budget rule missing keyword {keyword!r}"


def test_create_coordinator_time_budget_rule_has_three_step_recipe():
    """Fix 3 v3: time-budget rule is a concrete 3-step recipe (places_agent
    candidates → route_agent per candidate → filter by budget). This is the
    fix for the 'no destination = nothing to verify' problem."""
    pytest.importorskip("google.adk")

    from agents.coordinator import create_coordinator

    coordinator = create_coordinator()
    instruction = coordinator.instruction
    # Recipe anchor words from ゆう's spec.
    assert "TIME-BUDGET RULE" in instruction
    assert "Step 1" in instruction and "places_agent" in instruction
    assert "Step 2" in instruction and "route_agent" in instruction
    assert "Step 3" in instruction
    # The recipe should mention dropping non-fitting candidates.
    assert "Drop the rest" in instruction or "Drop the rest." in instruction
    # Plus a fallback for "no candidates fit".
    assert "NO candidates" in instruction or "no candidates" in instruction


def test_create_coordinator_default_place_type_for_vague_queries():
    """Pattern 1 regression fix: vague 'おすすめの場所' queries should default
    to place_type='cafe' and delegate immediately, not ask for clarification."""
    pytest.importorskip("google.adk")

    from agents.coordinator import create_coordinator

    coordinator = create_coordinator()
    instruction = coordinator.instruction
    # The FIND A PLACE rule should explicitly handle vague queries.
    assert "おすすめの場所" in instruction, (
        "FIND A PLACE rule should explicitly mention the vague 'おすすめの場所' phrasing"
    )
    # And tell the LLM to default to cafe rather than asking.
    assert "default to 'cafe'" in instruction or "default to cafe" in instruction
    assert "do NOT ask for clarification" in instruction or "do not ask for clarification" in instruction.lower()