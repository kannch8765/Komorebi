"""Coordinator Agent — L1 router that dispatches to Route + Weather + Places.

Coordinator V2 (Module 11) adds the Places Agent as a third sub-agent so
the user can ask "find a quiet cafe near Shibuya" in addition to route /
weather queries. The full multi-agent flow:

  1. User asks about a Tokyo outing
  2. Coordinator picks the right sub-agent(s) via LLM-driven routing
  3. Route Agent ranks options by exposure_comfort slider (Module 10)
  4. Weather Agent reports outdoor suitability (Module 5)
  5. Places Agent finds quiet / interesting spots nearby (Module 8)
  6. Coordinator synthesizes the combined answer in Japanese

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
    """Build Coordinator V2 with Route + Weather + Places sub-agents.

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

    from agents.places_agent import create_places_agent
    from agents.route_agent import create_route_agent
    from agents.weather_agent import create_weather_agent
    from models.user_preferences import UserPreferences

    if preferences is None:
        preferences = UserPreferences.default()

    route_agent = create_route_agent(model=model)
    weather_agent = create_weather_agent(model=model)
    places_agent = create_places_agent(model=model)

    slider = preferences.exposure_comfort
    slider_hint = (
        f"\n\nCurrent user preference: exposure_comfort slider = {slider} "
        f"(weight_crowding={preferences.weight_crowding:.2f}, "
        f"weight_time={preferences.weight_time:.2f}). "
        "Pass this exact value as the `exposure_comfort` parameter when "
        "delegating to route_agent. If the user mentions their own slider "
        "preference in the query (e.g. '人混み避けたい' = slider 1, '急いでる' = "
        "slider 5), use that value instead of the default."
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
            "- FIND A PLACE (e.g. '渋谷の静かなカフェ', '新宿近くの図書館') → delegate to places_agent\n"
            "- MULTI (e.g. '渋谷に行って今日の天気は？' / 'Shibuya cafe + weather + route') → "
            "call all relevant sub-agents, then synthesize a combined answer\n"
            "- Out of scope (general chitchat, non-Tokyo planning) → politely decline and ask for a Tokyo outing query\n\n"
            "Slider hints (Japanese / English keywords → exposure_comfort value):\n"
            "  - '人混み避けたい' / 'quiet' / 'avoid crowds' / '空いてる' → slider = 1\n"
            "  - 'ゆっくり行きたい' / 'no rush' → slider = 2\n"
            "  - (default / not mentioned) → slider = 3\n"
            "  - 'そこそこ急いでる' / 'somewhat fast' → slider = 4\n"
            "  - '急いでる' / '急いで' / 'hurry' / 'asap' / 'fastest' → slider = 5\n\n"
            "Respond in Japanese. Be concise and friendly."
            + slider_hint
        ),
        sub_agents=[route_agent, weather_agent, places_agent],
    )