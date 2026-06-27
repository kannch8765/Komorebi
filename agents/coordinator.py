"""Coordinator Agent — L1 router that dispatches to Route + Weather sub-agents.

The Coordinator owns both sub-agents and decides which one(s) to delegate a
user query to. ADK handles the actual LLM-driven routing via the
`sub_agents` field — Gemini picks the right sub-agent based on the
coordinator's instruction.

The factory function is the testable surface (no LLM); importing
`agents.coordinator` does not require `google-adk`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from google.adk.agents import Agent

    from models.user_preferences import UserPreferences


def create_coordinator(
    model: str = "gemini-3.1-flash-lite",
    preferences: "UserPreferences | None" = None,
) -> "Agent":
    """Build the L1 Coordinator with Route + Weather sub-agents.

    Args:
        model:       LLM model name (default gemini-3.1-flash-lite).
        preferences: User's social-anxiety comfort preferences. If provided,
                     the slider value is embedded into the delegation
                     instruction so the LLM passes the correct
                     `exposure_comfort` to get_transit_routes. If None,
                     defaults to balanced (slider=3) and the LLM will ask
                     the user if they want to set it.
    """
    from google.adk.agents import Agent

    from agents.route_agent import create_route_agent
    from agents.weather_agent import create_weather_agent
    from models.user_preferences import UserPreferences

    if preferences is None:
        preferences = UserPreferences.default()

    route_agent = create_route_agent(model=model)
    weather_agent = create_weather_agent(model=model)

    slider = preferences.exposure_comfort
    slider_hint = (
        f"\n\nCurrent user preference: exposure_comfort slider = {slider} "
        f"(weight_crowding={preferences.weight_crowding:.2f}, "
        f"weight_time={preferences.weight_time:.2f}). "
        "Pass this exact value as the `exposure_comfort` parameter when "
        "delegating to route_agent. If the user mentions their own slider "
        "preference in the query, use that instead."
    )

    return Agent(
        name="coordinator",
        model=model,
        description="Komorebi L1 coordinator. Plans social-anxiety-friendly outings in Tokyo.",
        instruction=(
            "You are Komorebi's coordinator. You help users plan outings in "
            "Tokyo that minimize crowd exposure while maximizing enjoyment.\n\n"
            "Routing rules:\n"
            "- HOW TO GET somewhere (e.g. '渋谷から池袋への行き方は？') → delegate to route_agent\n"
            "- WEATHER questions (e.g. '今日の天気は？') → delegate to weather_agent\n"
            "- BOTH (e.g. '渋谷に行って今日の天気は？') → call both, then synthesize a combined answer\n"
            "- Out of scope (general chitchat, non-Tokyo planning) → politely decline and ask for a Tokyo outing query\n\n"
            "Respond in Japanese. Be concise and friendly."
            + slider_hint
        ),
        sub_agents=[route_agent, weather_agent],
    )