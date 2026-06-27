"""Transit API client for Komorebi (api.transit.ls8h.com).

Komorebi talks to the GTFS/ODPT-backed public-transit planner at
https://api.transit.ls8h.com. The same backend also exposes a JSON-RPC
MCP server at /mcp (see docs/transit-api.md for the comparison); we use
the REST surface here so we keep one dep (`requests`) and no extra
protocol layer.

Endpoints used:
  GET /api/v1/locations/suggest     → resolve_station_id()
  GET /api/v1/plan                   → get_routes() / get_routes_by_id()
  GET /api/v1/places/suggest         → suggest_places()
  GET /api/v1/places/reverse         → reverse_geocode()
  GET /api/v1/stations/{id}          → get_station_info()
  GET /api/v1/stations/{id}/departures → get_departures()

See https://api.transit.ls8h.com/api/openapi.json for the full schema.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from models.schemas import RouteResponse

DEFAULT_BASE_URL = "https://api.transit.ls8h.com"
DEFAULT_TIMEOUT = 30

# Defaults for fields the API doesn't provide.
_DEFAULT_EXTRA_TIME_MIN = 0

# Valid values for the `type` query param on /api/v1/plan.
# departure = now-ish, arrival = arrive by, first = first train, last = last train.
_VALID_TRIP_TYPES = ("departure", "arrival", "first", "last")

# Default max results for `suggest_*` calls.
_DEFAULT_SUGGEST_LIMIT = 5


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

    # ─── Station name resolution ──────────────────────────────────────────

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

    def suggest_places(
        self,
        q: str,
        limit: int = _DEFAULT_SUGGEST_LIMIT,
    ) -> list[dict]:
        """Broader-than-stations search: stations, stops, facilities, addresses.

        Returns the raw `places` list from the API. Each entry has
        `id`, `name`, `kind` ("station"/"facility"/"address"), and
        sometimes `lat`/`lon`. Use this when the user mentioned a
        facility name (e.g. "代官山蔦屋書店") that isn't a station.

        Mirrors the MCP `suggest_places` tool on /mcp.
        """
        url = f"{self.base_url}/api/v1/places/suggest"
        params = {"q": q, "limit": limit}
        response = self._get(url, params=params, context=f"place suggest for {q!r}")
        if not isinstance(response, dict):
            raise TransitAPIError(
                f"unexpected payload type from place suggest: {type(response).__name__}"
            )
        places = response.get("places", [])
        if not isinstance(places, list):
            raise TransitAPIError(
                f"places suggest returned non-list 'places': {type(places).__name__}"
            )
        return places

    def reverse_geocode(
        self,
        lat: float,
        lon: float,
        radius_meters: int = 80,
        limit: int = 3,
    ) -> list[dict]:
        """List stations/places near a (lat, lon) point.

        Useful for "what station should I board at given this cafe's
        coordinates?" — feeds directly into `plan_journey` via the
        `geo:<lat>,<lon>` shorthand in the `from`/`to` param.

        Mirrors the MCP `reverse_geocode` tool on /mcp.
        """
        url = f"{self.base_url}/api/v1/places/reverse"
        params = {
            "lat": lat,
            "lon": lon,
            "limit": limit,
            "radiusMeters": radius_meters,
        }
        response = self._get(url, params=params, context=f"reverse geocode {lat},{lon}")
        if not isinstance(response, dict):
            raise TransitAPIError(
                f"unexpected payload type from reverse geocode: {type(response).__name__}"
            )
        results = response.get("places", response.get("stations", []))
        if not isinstance(results, list):
            raise TransitAPIError(
                f"reverse geocode returned non-list results: {type(results).__name__}"
            )
        return results

    # ─── Station detail + departure board ─────────────────────────────────

    def get_station_info(self, station_id: str) -> dict:
        """Station detail: platforms + serving routes.

        Returns the raw dict. Look for `platforms[]` and `routes[]` (line
        names). Useful for "渋谷の何番ホームから乗る？" queries.

        Mirrors the MCP `get_station` tool on /mcp.
        """
        url = f"{self.base_url}/api/v1/stations/{station_id}"
        response = self._get(url, params={}, context=f"station info for {station_id!r}")
        if not isinstance(response, dict):
            raise TransitAPIError(
                f"unexpected payload type from station info: {type(response).__name__}"
            )
        return response

    def get_departures(
        self,
        station_id: str,
        date: str | None = None,  # YYYYMMDD
        time: str | None = None,  # HH:MM or HH:MM:SS
        limit: int = 20,
    ) -> list[dict]:
        """Real-time (or scheduled) departure board for a station.

        Returns a list of upcoming departures. Each entry typically has
        `routeName`, `destination`, `departureSecs`/`arrivalSecs`, and
        `track` (platform number). Coverage depends on the feed's
        license — not all stations publish this.

        Mirrors the MCP `station_departures` tool on /mcp.
        """
        url = f"{self.base_url}/api/v1/stations/{station_id}/departures"
        params: dict[str, str | int] = {"limit": limit}
        if date is not None:
            params["date"] = date
        if time is not None:
            params["time"] = time
        response = self._get(url, params=params, context=f"departures for {station_id!r}")
        # The endpoint may return either `departures` (list) or the
        # whole thing as a list — tolerate both.
        if isinstance(response, list):
            return response
        if not isinstance(response, dict):
            raise TransitAPIError(
                f"unexpected payload type from departures: {type(response).__name__}"
            )
        departures = response.get("departures", [])
        if not isinstance(departures, list):
            raise TransitAPIError(
                f"departures returned non-list field: {type(departures).__name__}"
            )
        return departures

    # ─── Route planning ───────────────────────────────────────────────────

    def get_routes(
        self,
        origin: str,
        destination: str,
        num_itineraries: int = 3,
        current_time: datetime | None = None,
        via: list[str] | None = None,
        trip_type: str = "departure",
        avoid_modes: list[str] | None = None,
        allow_modes: list[str] | None = None,
        avoid_walk: bool = False,
        max_transfers: int | None = None,
        date: str | None = None,  # YYYYMMDD
        time: str | None = None,  # HH:MM
        from_label: str | None = None,
        to_label: str | None = None,
        via_label: list[str] | None = None,
    ) -> "RouteResponse":
        """Fetch journey options between two station names. Returns RouteResponse.

        All new params are optional and have safe defaults. See
        `get_routes_by_id` for the param-by-param meaning — same params,
        just resolves names to IDs first.
        """
        from_id = self.resolve_station_id(origin)
        to_id = self.resolve_station_id(destination)
        return self.get_routes_by_id(
            from_id=from_id,
            to_id=to_id,
            num_itineraries=num_itineraries,
            current_time=current_time,
            via=via,
            trip_type=trip_type,
            avoid_modes=avoid_modes,
            allow_modes=allow_modes,
            avoid_walk=avoid_walk,
            max_transfers=max_transfers,
            date=date,
            time=time,
            from_label=from_label,
            to_label=to_label,
            via_label=via_label,
        )

    def get_routes_by_id(
        self,
        from_id: str,
        to_id: str,
        num_itineraries: int = 3,
        current_time: datetime | None = None,
        via: list[str] | None = None,
        trip_type: str = "departure",
        avoid_modes: list[str] | None = None,
        allow_modes: list[str] | None = None,
        avoid_walk: bool = False,
        max_transfers: int | None = None,
        date: str | None = None,  # YYYYMMDD
        time: str | None = None,  # HH:MM
        from_label: str | None = None,
        to_label: str | None = None,
        via_label: list[str] | None = None,
    ) -> "RouteResponse":
        """Fetch journeys between two station IDs. Returns RouteResponse.

        New params (all optional, all default to API defaults):
          via           — up to 3 waypoints (station IDs) the route must pass through
          trip_type     — "departure" (default) | "arrival" | "first" | "last"
                          Use "arrival" + time= to find routes arriving by a given time
                          Use "last" to find the 終電
          avoid_modes   — list of modes to exclude (e.g. ["bus", "air"])
          allow_modes   — list of allowed modes (e.g. ["rail", "subway"])
                          Pre-scan filter; the planner may still return mixed
          avoid_walk    — True to exclude any itinerary with a walking leg
          max_transfers — int 0..8 (default API default 3)
          date          — YYYYMMDD service date (default: today in result tz)
          time          — HH:MM or HH:MM:SS (default: now)
          from_label / to_label / via_label — display names to surface in
                          the result instead of the raw feedId:stopId
        """
        if trip_type not in _VALID_TRIP_TYPES:
            raise TransitAPIError(
                f"invalid trip_type {trip_type!r}; must be one of {_VALID_TRIP_TYPES}"
            )
        if via is not None and len(via) > 3:
            raise TransitAPIError(f"via accepts at most 3 waypoints, got {len(via)}")
        if max_transfers is not None and not (0 <= max_transfers <= 8):
            raise TransitAPIError(
                f"max_transfers must be in 0..8, got {max_transfers}"
            )

        url = f"{self.base_url}/api/v1/plan"
        params: dict[str, str | int | list[str]] = {
            "from": from_id,
            "to": to_id,
            "numItineraries": num_itineraries,
            "type": trip_type,
            "avoidWalk": "true" if avoid_walk else "false",
        }
        if via is not None:
            params["via"] = via
        if via_label is not None:
            params["viaLabel"] = via_label
        if from_label is not None:
            params["fromLabel"] = from_label
        if to_label is not None:
            params["toLabel"] = to_label
        if date is not None:
            params["date"] = date
        if time is not None:
            params["time"] = time
        if avoid_modes is not None:
            # API wants a comma-separated string, not an array param.
            params["avoidModes"] = ",".join(avoid_modes)
        if allow_modes is not None:
            params["allowModes"] = ",".join(allow_modes)
        if max_transfers is not None:
            params["maxTransfers"] = max_transfers

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

        if current_time is None:
            current_time = datetime.now()
        return _build_route_response(journeys, current_time=current_time)

    # ─── HTTP helper ──────────────────────────────────────────────────────

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


def _build_route_response(
    journeys: list,
    current_time: datetime,
) -> "RouteResponse":
    """Parse raw journey dicts into RouteResponse, filling missing optional fields.

    `current_time` is used by tools.crowding to compute a per-journey
    crowding score based on time-of-day, line popularity, and transfer hub
    congestion. The API itself does not expose occupancy data.
    """
    from models.schemas import RouteRecommendation, RouteResponse
    from tools.crowding import CrowdingFactors, score_route

    recommendations: list[RouteRecommendation] = []
    for i, raw in enumerate(journeys):
        if not isinstance(raw, dict):
            continue

        duration_min = max(1, round(int(raw.get("durationSecs", 0)) / 60))
        transfers = int(raw.get("transferCount", 0))

        legs = raw.get("legs", [])
        stations: list[str] = []
        lines: list[str] = []
        for leg_i, leg in enumerate(legs):
            if not isinstance(leg, dict):
                continue
            leg_from = leg.get("from")
            leg_to = leg.get("to")
            # First leg contributes its `from`; each leg contributes its `to`.
            # This avoids duplicating transfer stations (leg N's to == leg N+1's from).
            if leg_i == 0 and isinstance(leg_from, dict) and "name" in leg_from:
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

        # Compute crowding score from time-of-day + lines + transfer hubs.
        # Transfer stations are all stations except origin + destination.
        transfer_stations = tuple(stations[1:-1]) if len(stations) > 2 else ()
        crowding_score = score_route(
            CrowdingFactors(
                time_of_day=current_time,
                lines=tuple(lines),
                transfer_stations=transfer_stations,
            )
        )

        recommendations.append(
            RouteRecommendation(
                name=name,
                duration_min=duration_min,
                transfers=transfers,
                crowding_score=crowding_score,
                extra_time_min=_DEFAULT_EXTRA_TIME_MIN,
                stations=stations,
                lines=lines,
            )
        )

    return RouteResponse(routes=recommendations)
