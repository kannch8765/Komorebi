"""Transit API client for Komorebi (api.transit.ls8h.com).

Two-step flow:
  1. /api/v1/locations/suggest — resolve station display name → canonical ID
  2. /api/v1/plan — fetch journeys between two station IDs

See https://api.transit.ls8h.com/api/openapi.json for the full schema.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from models.schemas import RouteResponse

DEFAULT_BASE_URL = "https://api.transit.ls8h.com"
DEFAULT_TIMEOUT = 30

# Defaults for fields the API doesn't provide.
_DEFAULT_CROWDING_SCORE = 0.5
_DEFAULT_EXTRA_TIME_MIN = 0


class TransitAPIError(Exception):
    """Raised on HTTP, parse, or station-not-found failures from the transit API."""


class TransitAPIClient:
    """Thin wrapper around api.transit.ls8h.com returning Pydantic RouteResponse."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def resolve_station_id(self, name: str, limit: int = 5) -> str:
        """Resolve a station display name (e.g. '渋谷') to its canonical ID.

        Returns the highest-weighted match across operators.
        """
        url = f"{self.base_url}/api/v1/locations/suggest"
        params = {"q": name, "limit": limit}
        response = self._get(url, params=params, context=f"station suggest for {name!r}")
        if not isinstance(response, dict):
            raise TransitAPIError(
                f"unexpected payload type from station suggest: {type(response).__name__}"
            )

        stations = response.get("stations", [])
        if not stations:
            raise TransitAPIError(f"station not found: {name!r}")

        # Prefer score=3 (rail/subway) over score=2 (bus stops), then highest weight.
        # This avoids picking a long bus route when a JR/Metro line is available.
        stations.sort(key=lambda s: (s.get("score", 0), s.get("weight", 0)), reverse=True)
        first = stations[0]
        if not isinstance(first, dict) or "id" not in first:
            raise TransitAPIError(f"station suggest response missing 'id' for {name!r}")
        return first["id"]

    def get_routes(
        self,
        origin: str,
        destination: str,
        num_itineraries: int = 3,
    ) -> "RouteResponse":
        """Fetch journey options between two station names. Returns RouteResponse."""
        from_id = self.resolve_station_id(origin)
        to_id = self.resolve_station_id(destination)
        return self.get_routes_by_id(
            from_id=from_id,
            to_id=to_id,
            num_itineraries=num_itineraries,
        )

    def get_routes_by_id(
        self,
        from_id: str,
        to_id: str,
        num_itineraries: int = 3,
    ) -> "RouteResponse":
        """Fetch journeys between two station IDs. Returns RouteResponse."""
        url = f"{self.base_url}/api/v1/plan"
        params = {
            "from": from_id,
            "to": to_id,
            "numItineraries": num_itineraries,
        }
        response = self._get(
            url,
            params=params,
            context=f"plan for {from_id}->{to_id}",
        )
        if not isinstance(response, dict):
            raise TransitAPIError(
                f"unexpected payload type from plan: {type(response).__name__}"
            )

        journeys = response.get("journeys", [])
        if not isinstance(journeys, list):
            raise TransitAPIError("plan API returned 'journeys' field that is not a list")

        return _build_route_response(journeys)

    def _get(self, url: str, *, params: dict, context: str) -> object:
        """Shared HTTP GET with consistent error handling."""
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise TransitAPIError(f"network error fetching {context}: {exc}") from exc

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise TransitAPIError(
                f"HTTP {response.status_code} from {context}: {exc}"
            ) from exc

        try:
            return response.json()
        except ValueError as exc:
            raise TransitAPIError(f"malformed JSON from {context}: {exc}") from exc


def _build_route_response(journeys: list) -> "RouteResponse":
    """Parse raw journey dicts into RouteResponse, filling missing optional fields."""
    from models.schemas import RouteRecommendation, RouteResponse

    recommendations: list[RouteRecommendation] = []
    for i, raw in enumerate(journeys):
        if not isinstance(raw, dict):
            continue

        duration_min = max(1, round(int(raw.get("durationSecs", 0)) / 60))
        transfers = int(raw.get("transferCount", 0))

        legs = raw.get("legs", [])
        stations: list[str] = []
        lines: list[str] = []
        for i, leg in enumerate(legs):
            if not isinstance(leg, dict):
                continue
            leg_from = leg.get("from")
            leg_to = leg.get("to")
            # First leg contributes its `from`; each leg contributes its `to`.
            # This avoids duplicating transfer stations (leg N's to == leg N+1's from).
            if i == 0 and isinstance(leg_from, dict) and "name" in leg_from:
                stations.append(leg_from["name"])
            if isinstance(leg_to, dict) and "name" in leg_to:
                stations.append(leg_to["name"])
            route_name = leg.get("routeName")
            if isinstance(route_name, str) and route_name not in lines:
                lines.append(route_name)

        # Synthesize a human-readable name.
        if lines:
            if transfers == 0:
                name = lines[0]
            elif transfers == 1:
                name = f"{lines[0]} で 1 回乗換"
            else:
                name = f"{lines[0]} で {transfers} 回乗換"
        else:
            name = f"ルート {i + 1}"

        recommendations.append(
            RouteRecommendation(
                name=name,
                duration_min=duration_min,
                transfers=transfers,
                crowding_score=_DEFAULT_CROWDING_SCORE,
                extra_time_min=_DEFAULT_EXTRA_TIME_MIN,
                stations=stations,
                lines=lines,
            )
        )

    return RouteResponse(routes=recommendations)