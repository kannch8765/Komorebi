"""Weather Agent — answers Tokyo weather queries.

Wraps WeatherAPIClient as an ADK tool. The tool function is the testable
surface (no LLM); the Agent definition lives in `create_weather_agent()`
so that `agents/weather_agent` imports cleanly even without `google-adk`
on the import path.

Note: the `client` parameter is NOT exposed on the public tool signature —
ADK introspects the function to build a JSON schema for the LLM, and any
non-primitive type causes PydanticSchemaGenerationError. Tests patch
`agents.weather_agent.WeatherAPIClient` at the module level instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tools.weather_api import TOKYO_LAT, TOKYO_LON, WeatherAPIClient

if TYPE_CHECKING:
    from google.adk.agents import Agent


def get_current_weather(
    lat: float | None = None,
    lon: float | None = None,
) -> dict:
    """Fetch current weather; default to Tokyo coords if lat/lon not given."""
    if lat is None:
        lat = TOKYO_LAT
    if lon is None:
        lon = TOKYO_LON
    client = WeatherAPIClient()
    response = client.get_weather(lat, lon)
    return response.model_dump()


def create_weather_agent(
    model: str = "gemini-3.1-flash-lite",
    home=None,  # accepted for API symmetry with create_route_agent; unused
) -> "Agent":
    """Build the Weather Agent. Requires google-adk + a valid Gemini API key.

    Args:
        model: LLM model name.
        home:  Accepted for symmetry with `create_route_agent`. Currently
               unused — weather is always reported for Tokyo coords.
    """
    from google.adk.agents import Agent
    from google.adk.tools import FunctionTool

    return Agent(
        name="weather_agent",
        model=model,
        description="Tokyo weather reporter. Returns current weather + outdoor suitability.",
        instruction=(
            "You are a Tokyo weather reporter. When the user asks about the weather "
            "(in Japanese or English), call get_current_weather. Summarize the "
            "conditions in Japanese, mentioning temperature (in °C), sky "
            "conditions, rain probability, and whether it's suitable for outdoor "
            "activities. Default coordinates are Tokyo — only override if the "
            "user specifies a different location."
        ),
        tools=[FunctionTool(get_current_weather)],
    )