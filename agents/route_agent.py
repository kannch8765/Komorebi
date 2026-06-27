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

Advanced routing options (via, trip_type, avoid_modes, etc.) are exposed
as optional primitive params (str / list[str] / bool / int) so the LLM can
forward user preferences like "no bus" or "arrive by 18:00" to the API.
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
    via: list[str] | None = None,
    trip_type: str = "departure",
    avoid_modes: list[str] | None = None,
    allow_modes: list[str] | None = None,
    avoid_walk: bool = False,
    max_transfers: int | None = None,
    time: str | None = None,
) -> dict:
    """Fetch transit routes between two stations; rank by user preference.

    Args:
        origin:            Starting station name (Japanese or English).
        destination:       Ending station name.
        exposure_comfort:  Slider 1..5. 1 = avoid crowds (slower OK),
                           5 = time-only (ignore crowds). Default 3 (balanced).
        via:               Up to 3 waypoint station names the route must pass
                           through. Use when the user says e.g. "恵比寿経由
                           で代官山から渋谷".
        trip_type:         "departure" (default) | "arrival" | "first" | "last".
                           Use "arrival" + time= when user says "○時に着き
                           たい". Use "last" for 終電 searches.
        avoid_modes:       Transit modes to exclude. Each item is one of
                           "rail", "subway", "bus", "air", "ferry", "walk".
                           Use when user says "バスは嫌" / "no bus".
        allow_modes:       Only allow these modes. Use for "鉄道だけで".
        avoid_walk:        True to exclude any itinerary with a walking leg.
                           Use for mobility-concern users.
        max_transfers:     0..8. Use to cap transfers (e.g. "乗り換えたくな
                           い" → 0).
        time:              HH:MM (24h). Combine with trip_type="arrival"
                           for arrive-by queries. Combine with trip_type
                           ="first"/"last" to scope the time window.

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
    response = client.get_routes(
        origin=origin,
        destination=destination,
        via=via,
        trip_type=trip_type,
        avoid_modes=avoid_modes,
        allow_modes=allow_modes,
        avoid_walk=avoid_walk,
        max_transfers=max_transfers,
        time=time,
    )
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
            "and destination station names.\n\n"
            "Two preference dimensions to forward:\n"
            "1. **exposure_comfort slider** (int 1..5; default 3)\n"
            "   - 1 = strongly avoid crowds (accept slower routes)\n"
            "   - 5 = time-only (ignore crowding)\n"
            "   - 3 = balanced. Set from user keywords: '人混み避けたい' / "
            "'quiet' → 1; '急いでる' / 'hurry' / 'fastest' → 5; otherwise 3.\n\n"
            "2. **Advanced routing options** — only when the user's query "
            "implies a constraint beyond 'fastest/cheapest':\n"
            "   - '経由して' / 'via' / 'stop at X' → via=['X'] (up to 3)\n"
            "   - '○時に着きたい' / 'arrive by HH:MM' → trip_type='arrival', "
            "time='HH:MM'\n"
            "   - '終電' / 'last train' → trip_type='last'\n"
            "   - '始発' / 'first train' → trip_type='first'\n"
            "   - 'バスは嫌' / 'no bus' / 'avoid bus' → avoid_modes=['bus']\n"
            "   - '鉄道だけで' / 'rail only' → allow_modes=['rail', 'subway']\n"
            "   - '歩きたくない' / 'no walking' / 'mobility concern' → "
            "avoid_walk=True\n"
            "   - '乗り換えたくない' / 'no transfers' → max_transfers=0\n\n"
            "If the user does not mention any advanced option, do NOT pass "
            "those args (use defaults).\n\n"
            "Summarize the returned routes in Japanese, noting duration, "
            "transfers, and crowding — and explicitly state which route was "
            "chosen because of the slider. If no routes are returned, ask "
            "the user to confirm the station names."
        ),
        tools=[FunctionTool(get_transit_routes)],
    )
