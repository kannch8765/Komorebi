"""Route Agent — answers Tokyo transit route queries.

Wraps TransitAPIClient as an ADK tool. The tool function is the testable
surface (no LLM); the Agent definition lives in `create_route_agent()` so
that `agents.route_agent` imports cleanly even without `google-adk` on the
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

V2.5 personal context — home keyword resolution:
The factory `create_route_agent(home=...)` accepts the user's saved home
location. When set, the resulting tool closure resolves home keywords
('家' / '自宅' / 'home' / 'うち') in origin/destination/via to the home
label BEFORE calling the transit API. This is the safety net for the
Coordinator's home hint — if the LLM passes a keyword instead of the
actual station, we substitute the configured home label.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from models.schemas import RouteRecommendation, RouteResponse
from tools.transit_api import TransitAPIClient

if TYPE_CHECKING:
    from google.adk.agents import Agent

    from models.user_profile import HomeLocation


# Keywords that the user (or an LLM delegation) might use to refer to
# their home in a query. Resolved by `_resolve_home_keyword` if home is set.
# Kept as a stopgap safety net — the primary resolution happens at the
# Coordinator level (which instructs its LLM to pre-resolve "家"-references
# to literal coords before delegating to sub-agents). This list catches the
# cases where the Coordinator's LLM ignores the instruction and passes a
# home-synonym down to route_agent instead.
_HOME_KEYWORDS: tuple[str, ...] = (
    "家", "自宅", "home", "うち",                 # primary: "home"
    "現在地", "出発地", "出発地点", "出発",      # "current location" / "departure"
    "自分の場所", "私の場所",                     # "my place"
    "current location", "departure", "from here",  # English synonyms
)


def filter_outlier_routes(
    routes: list[RouteRecommendation],
    factor: float = 3.0,
) -> list[RouteRecommendation]:
    """Drop routes whose duration is > factor * fastest duration.

    V2.5: the transit API can occasionally return an outlier itinerary
    (e.g. a 527-min 横浜→池袋 route alongside realistic ~30-min options).
    The ranker would happily promote such a route if its crowding score
    is favorable, so we filter before ranking.

    Args:
        routes: candidate routes from the API.
        factor: multiplier for the fastest duration. Routes with
                duration_min > factor * fastest are dropped. Default 3.0.

    Returns:
        New list of routes with outliers removed. Original list untouched.
        Empty list in → empty list out.
    """
    if not routes:
        return []

    fastest = min(r.duration_min for r in routes)
    threshold = factor * fastest
    return [r for r in routes if r.duration_min <= threshold]


def _resolve_home_keyword(text: str, home_label: str) -> str:
    """Replace home keyword with the configured home label.

    Replaces each keyword directly. Acceptable false-positive risk: the
    keyword may appear inside unrelated compound words (e.g. '家族' →
    '横浜駅族', 'homecoming' → '横浜駅coming'). In a Tokyo station-name
    context this is essentially never a problem; if it ever is, add a
    blocklist here.

    Args:
        text:        input string (station name, via, etc.). May be empty.
        home_label:  the user's saved home label (e.g. '横浜駅').

    Returns:
        `text` with home keywords replaced by `home_label`.
    """
    if not text:
        return text
    for kw in _HOME_KEYWORDS:
        text = text.replace(kw, home_label)
    return text


def _get_transit_routes_impl(
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
    _home: str | None = None,
) -> dict:
    """Internal impl — see `get_transit_routes` for the public docstring.

    `_home` is the user's saved home label, set by `create_route_agent(home=...)`.
    When non-None, home keywords in origin/destination/via are resolved to
    `_home` before calling the transit API.
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

    # V2.5: resolve home keywords → home label (tool-layer safety net)
    if _home is not None:
        origin = _resolve_home_keyword(origin, _home)
        destination = _resolve_home_keyword(destination, _home)
        if via:
            via = [_resolve_home_keyword(v, _home) for v in via]

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
    # Drop outliers BEFORE ranking so the ranker doesn't waste cycles on
    # clearly broken itineraries (e.g. a 527-min 横浜→池袋 route).
    candidates = filter_outlier_routes(response.routes)
    ranked = rank_routes(
        candidates, UserPreferences(exposure_comfort=exposure_comfort)
    )
    return RouteResponse(routes=ranked).model_dump()


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
    _home: str | None = None,
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
        _home:             INTERNAL — user's saved home label. Set by
                           `create_route_agent(home=...)`. The LLM should
                           never pass this directly.

    Returns:
        Dict with a `routes` key whose list is sorted by the user's
        preference (best fit first).
    """
    return _get_transit_routes_impl(
        origin=origin,
        destination=destination,
        exposure_comfort=exposure_comfort,
        via=via,
        trip_type=trip_type,
        avoid_modes=avoid_modes,
        allow_modes=allow_modes,
        avoid_walk=avoid_walk,
        max_transfers=max_transfers,
        time=time,
        _home=_home,
    )


def create_route_agent(
    model: str = "gemini-3.1-flash-lite",
    home: "HomeLocation | None" = None,
) -> "Agent":
    """Build the Route Agent. Requires google-adk + a valid Gemini API key.

    Args:
        model:  LLM model name.
        home:   User's saved home (label, lat, lon). When provided, the
                resulting tool closure resolves '家'/'自宅'/'home'/'うち'
                in origin/destination/via to home.label before calling
                the transit API. When None, no resolution happens.
    """
    from google.adk.agents import Agent
    from google.adk.tools import FunctionTool

    home_label = home.label if home is not None else None

    # If home is configured, append a hint to the route_agent's instruction
    # so its LLM also knows to pre-resolve home references in origin/via.
    if home is not None:
        home_agent_hint = (
            f"\n\nNote: the user's home is {home.label}. If the delegated "
            f"query contains '家' / '自宅' / 'home' / '現在地' / '出発地' "
            f"or similar home-references, substitute them with '{home.label}' "
            f"BEFORE calling get_transit_routes. (The tool also has a safety "
            f"net, but you should pre-resolve.)"
        )
    else:
        home_agent_hint = ""

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
        """Closure that binds _home for the ADK tool.

        Signature matches `get_transit_routes` minus the internal `_home` param.
        """
        return _get_transit_routes_impl(
            origin=origin,
            destination=destination,
            exposure_comfort=exposure_comfort,
            via=via,
            trip_type=trip_type,
            avoid_modes=avoid_modes,
            allow_modes=allow_modes,
            avoid_walk=avoid_walk,
            max_transfers=max_transfers,
            time=time,
            _home=home_label,
        )

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
            + home_agent_hint
        ),
        tools=[FunctionTool(get_transit_routes)],
    )