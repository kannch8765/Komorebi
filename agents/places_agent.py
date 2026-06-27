"""Places Agent — finds quiet / interesting spots in Tokyo.

Wraps PlacesAPIClient as an ADK tool. The tool function is the testable
surface (no LLM); the Agent definition lives in `create_places_agent()`
so that `agents/places_agent` imports cleanly even without `google-adk`.

Following the same rule documented in `agents/route_agent.py` and
`docs/adk-usage.md`: the tool signature uses PRIMITIVE types only
(str/int/float/bool/None). ADK introspects the function with Pydantic
to build the JSON schema for the LLM — any non-primitive type causes
PydanticSchemaGenerationError.

Why a hardcoded Tokyo coord table in the instruction:
The LLM has to map user intent like "near Shibuya" or "around Shinjuku"
to lat/lon. We don't have a geocoding tool yet (Module 12+). The
hardcoded table lets the LLM resolve common Tokyo districts/stations
deterministically without external API calls.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from google.adk.agents import Agent


# Well-known Tokyo coords used by the agent's instruction to resolve
# district/station mentions in user queries. Keep this table small —
# only the most common destinations. Users can always pass lat/lon
# directly for arbitrary locations.
TOKYO_COORDS: dict[str, tuple[float, float]] = {
    "渋谷": (35.6580, 139.7016),
    "原宿": (35.6705, 139.7026),
    "表参道": (35.6655, 139.7126),
    "恵比寿": (35.6464, 139.7100),
    "代官山": (35.6486, 139.7036),
    "中目黒": (35.6442, 139.6988),
    "新宿": (35.6896, 139.7006),
    "池袋": (35.7295, 139.7109),
    "東京": (35.6812, 139.7671),
    "大手町": (35.6864, 139.7670),
    "銀座": (35.6717, 139.7649),
    "有楽町": (35.6749, 139.7640),
    "秋葉原": (35.6984, 139.7731),
    "上野": (35.7141, 139.7774),
    "品川": (35.6285, 139.7387),
    "新橋": (35.6655, 139.7596),
    "六本木": (35.6628, 139.7307),
    "麻布": (35.6536, 139.7360),
    "広尾": (35.6507, 139.7166),
    "白金": (35.6456, 139.7259),
    "目黒": (35.6335, 139.7159),
    "五反田": (35.6259, 139.7232),
    "代々木": (35.6831, 139.7020),
    "下北沢": (35.6614, 139.6686),
    "吉祥寺": (35.7022, 139.5801),
    "三軒茶屋": (35.6439, 139.6710),
    "二子玉川": (35.6111, 139.6261),
    "横浜": (35.4657, 139.6223),
    "大宮": (35.9060, 139.6244),
}


def search_places(
    lat: float,
    lon: float,
    place_type: str,
    radius_m: int = 500,
    max_results: int = 5,
) -> dict:
    """Search for places of a given type near (lat, lon) via Google Places API.

    Args:
        lat:         Center latitude (-90..90).
        lon:         Center longitude (-180..180).
        place_type:  Google place type — e.g. "cafe", "park", "library",
                     "museum", "restaurant", "bar", "book_store",
                     "tourist_attraction", "art_gallery", "spa", "tea_house".
                     See Google Places API type table for the full list.
        radius_m:    Search radius in meters (default 500, max 50000).
        max_results: Max results to return (default 5, max 20 per call).

    Returns:
        Dict with a `results` key whose value is a list of place records:
            {place_id, name, address, location, types, primary_type, open_now}
        Empty list if no matches.
    """
    from tools.places_api import PlacesAPIClient

    client = PlacesAPIClient()
    response = client.nearby_search(
        lat=lat,
        lon=lon,
        place_type=place_type,
        radius_m=radius_m,
        max_results=max_results,
    )
    return response.model_dump()


def create_places_agent(model: str = "gemini-3.1-flash-lite") -> "Agent":
    """Build the Places Agent. Requires google-adk + a valid GOOGLE_PLACES_API_KEY."""
    from google.adk.agents import Agent
    from google.adk.tools import FunctionTool

    # Format the Tokyo coord table for inclusion in the instruction.
    coord_table = "\n".join(
        f"  - {name}: lat={lat}, lon={lon}"
        for name, (lat, lon) in TOKYO_COORDS.items()
    )

    return Agent(
        name="places_agent",
        model=model,
        description=(
            "Tokyo places finder. Returns nearby cafes, parks, libraries, "
            "museums, and other spots with name, address, and open-now status."
        ),
        instruction=(
            "You are Komorebi's Tokyo places finder. When the user asks for "
            "a recommendation of a type of place near a specific area (e.g. "
            "'渋谷の静かなカフェ' / 'quiet cafe near Shibuya', '新宿近くの公園' / "
            "'park near Shinjuku', '池袋の図書館' / 'library in Ikebukuro'), call "
            "search_places with the appropriate lat/lon and place_type.\n\n"
            "Coordinate table for common Tokyo districts / stations "
            "(use these for lat/lon; otherwise ask the user for coordinates):\n"
            f"{coord_table}\n\n"
            "Place type suggestions (Google Places API categories):\n"
            "  - 'cafe' — カフェ (most common social-anxiety-friendly request)\n"
            "  - 'park' — 公園 (Yoyogi, Shinjuku Gyoen, etc.)\n"
            "  - 'library' — 図書館 (very quiet)\n"
            "  - 'museum' — 博物館 / 美術館\n"
            "  - 'book_store' — 本屋 (often has quiet reading space)\n"
            "  - 'art_gallery' — ギャラリー\n"
            "  - 'tourist_attraction' — 観光地\n"
            "  - 'restaurant' — レストラン\n"
            "  - 'spa' — 温泉 / スパ\n\n"
            "Summarize the results in Japanese. For each place, mention:\n"
            "  1. 名前 (name)\n"
            "  2. 住所 (address) — short, just district + neighborhood\n"
            "  3. 開いているか (open now: yes/no/unknown)\n"
            "  4. 種類 (primary type)\n\n"
            "If no places match, ask the user to broaden the search area or "
            "try a different type."
        ),
        tools=[FunctionTool(search_places)],
    )