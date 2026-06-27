"""Route Agent — answers Tokyo transit route queries.

Wraps TransitAPIClient as an ADK tool. The tool function is the testable
surface (no LLM); the Agent definition lives in `create_route_agent()` so
that `agents/route_agent` imports cleanly even without `google-adk` on the
import path (it's only resolved at factory call time).

Note: the `client` parameter is NOT exposed on the public tool signature —
ADK introspects the function to build a JSON schema for the LLM, and any
non-primitive type causes PydanticSchemaGenerationError. Tests patch
`agents.route_agent.TransitAPIClient` at the module level instead.

User preference (exposure_comfort slider 1..5) IS exposed as a primitive
int param so the LLM can pass it directly. See models/user_preferences.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from models.schemas import RouteResponse
from tools.transit_api import TransitAPIClient

if TYPE_CHECKING:
    from google.adk.agents import Agent


def get_transit_routes(
    origin: str,
    destination: str,
    exposure_comfort: int = 3,
) -> dict:
    """Fetch transit routes between two stations; rank by user preference.

    Args:
        origin:            Starting station name (Japanese or English).
        destination:       Ending station name.
        exposure_comfort:  Slider 1..5. 1 = avoid crowds (slower OK),
                           5 = time-only (ignore crowds). Default 3 (balanced).

    Returns:
        Dict with a `routes` key whose list is sorted by the user's
        preference (best fit first).
    """
    from models.user_preferences import (
        SLIDER_MAX,
        SLIDER_MIN,
        UserPreferences,
        rank_routes,
    )

    if not (SLIDER_MIN <= exposure_comfort <= SLIDER_MAX):
        raise ValueError(
            f"exposure_comfort must be {SLIDER_MIN}..{SLIDER_MAX}, "
            f"got {exposure_comfort}"
        )

    client = TransitAPIClient()
    response = client.get_routes(origin, destination)
    ranked = rank_routes(response.routes, UserPreferences(exposure_comfort=exposure_comfort))
    return RouteResponse(routes=ranked).model_dump()


def create_route_agent(model: str = "gemini-3.1-flash-lite") -> "Agent":
    """Build the Route Agent. Requires google-adk + a valid Gemini API key."""
    from google.adk.agents import Agent
    from google.adk.tools import FunctionTool

    return Agent(
        name="route_agent",
        model=model,
        description="Tokyo transit route planner. Returns routes with duration, transfers, and crowding scores.",
        instruction=(
            "You are a Tokyo transit route planner. When the user asks how to get "
            "from one place to another, call get_transit_routes with the origin "
            "and destination station names, plus an exposure_comfort value "
            "(integer 1..5; default 3). The slider is the user's social-anxiety "
            "comfort: 1 = strongly avoid crowds (accept slower), 5 = time-only "
            "(ignore crowds), 3 = balanced. If the user does not mention the "
            "slider, use 3. Summarize the returned routes in Japanese, noting "
            "duration, transfers, and crowding — and explicitly state which "
            "route was chosen because of the slider. If no routes are returned, "
            "ask the user to confirm the station names."
        ),
        tools=[FunctionTool(get_transit_routes)],
    )