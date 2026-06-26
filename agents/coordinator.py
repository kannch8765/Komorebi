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


def create_coordinator(model: str = "gemini-2.0-flash") -> "Agent":
    """Build the L1 Coordinator with Route + Weather sub-agents."""
    from google.adk.agents import Agent

    from agents.route_agent import create_route_agent
    from agents.weather_agent import create_weather_agent

    route_agent = create_route_agent(model=model)
    weather_agent = create_weather_agent(model=model)

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
        ),
        sub_agents=[route_agent, weather_agent],
    )