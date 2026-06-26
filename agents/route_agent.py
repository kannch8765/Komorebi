"""Route Agent — answers Tokyo transit route queries.

Wraps TransitAPIClient as an ADK tool. The tool function is the testable
surface (no LLM); the Agent definition lives in `create_route_agent()` so
that `agents/route_agent` imports cleanly even without `google-adk` on the
import path (it's only resolved at factory call time).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tools.transit_api import TransitAPIClient

if TYPE_CHECKING:
    from google.adk.agents import Agent


def get_transit_routes(
    origin: str,
    destination: str,
    client: TransitAPIClient | None = None,
) -> dict:
    """Fetch transit routes between two stations; return ADK-tool-friendly dict.

    `client` is injectable so tests can pass a mock without patching imports.
    """
    if client is None:
        client = TransitAPIClient()
    response = client.get_routes(origin, destination)
    return response.model_dump()


def create_route_agent(model: str = "gemini-2.0-flash") -> "Agent":
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
            "and destination station names. Summarize the returned routes in "
            "Japanese, noting duration, transfers, and crowding. Prefer routes "
            "with lower crowding scores if the user mentions social-anxiety "
            "comfort. If no routes are returned, ask the user to confirm the "
            "station names."
        ),
        tools=[FunctionTool(get_transit_routes)],
    )