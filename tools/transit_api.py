"""Transit API client for Komorebi (api.transit.ls8h.com, GTFS/ODPT)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from models.schemas import RouteRecommendation, RouteResponse

_DEFAULT_CROWDING_SCORE = 0.5
_DEFAULT_EXTRA_TIME_MIN = 0


class TransitAPIError(Exception):
    """Raised on HTTP, parse, or empty-response failures from the transit API."""


class TransitAPIClient:
    """Thin wrapper around api.transit.ls8h.com returning Pydantic RouteResponse."""

    def __init__(
        self,
        base_url: str = "https://api.transit.ls8h.com",
        timeout: int = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def get_routes(self, origin: str, destination: str) -> "RouteResponse":
        """Fetch and parse route recommendations between two stations."""
        url = f"{self.base_url}/api/v1/routes"
        params = {"origin": origin, "destination": destination}
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise TransitAPIError(
                f"network error fetching routes {origin!r}->{destination!r}: {exc}"
            ) from exc

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise TransitAPIError(
                f"HTTP {response.status_code} from transit API for "
                f"{origin!r}->{destination!r}: {exc}"
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise TransitAPIError(
                f"malformed JSON from transit API for "
                f"{origin!r}->{destination!r}: {exc}"
            ) from exc

        if not isinstance(payload, dict):
            raise TransitAPIError(
                f"unexpected payload type {type(payload).__name__} from transit API"
            )

        raw_routes = payload.get("routes", [])
        if not isinstance(raw_routes, list):
            raise TransitAPIError(
                "transit API returned 'routes' field that is not a list"
            )

        return _build_route_response(raw_routes)


def _build_route_response(raw_routes: list) -> "RouteResponse":
    """Parse raw route dicts into RouteResponse, filling missing optional fields."""
    from models.schemas import RouteRecommendation, RouteResponse

    recommendations: list[RouteRecommendation] = []
    for raw in raw_routes:
        if not isinstance(raw, dict):
            continue
        recommendations.append(
            RouteRecommendation(
                name=str(raw.get("name", "")),
                duration_min=int(raw.get("duration_min", 0)),
                transfers=int(raw.get("transfers", 0)),
                crowding_score=float(
                    raw.get("crowding_score", _DEFAULT_CROWDING_SCORE)
                ),
                extra_time_min=int(
                    raw.get("extra_time_min", _DEFAULT_EXTRA_TIME_MIN)
                ),
                stations=list(raw.get("stations", []) or []),
                lines=list(raw.get("lines", []) or []),
            )
        )

    return RouteResponse(routes=recommendations)