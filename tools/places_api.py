"""Google Places API (New) client for Komorebi.

Implements Nearby Search by location + place type. Returns a list of
PlaceSearchResult objects with name, address, lat/lon, types, and
open_now boolean.

Endpoint:   POST https://places.googleapis.com/v1/places:searchNearby
Auth:       X-Goog-Api-Key header (NOT a query param)
Field mask: X-Goog-FieldMask header — controls which fields are billed.
            The mask we ship covers the cheapest mix of Essentials +
            Pro-tier fields that still satisfies the spec. See
            CLAUDE.md "Google Places API" for the SKU breakdown.

Probed shape (curl with the API key in .env on 2026-06-27):
    request:
      {
        "includedPrimaryTypes": ["cafe"],
        "maxResultCount": 3,
        "locationRestriction": {
          "circle": {
            "center": {"latitude": 35.6812, "longitude": 139.7671},
            "radius": 500
          }
        }
      }
    response:
      {
        "places": [
          {
            "id": "ChIJ2TZSCfmLGGAR26O97vWyYcE",
            "displayName": {"text": "MARUZEN Marunouchi", "languageCode": "en"},
            "formattedAddress": "Japan, 〒100-8203 Tokyo, ...",
            "location": {"latitude": 35.6835155, "longitude": 139.7666676},
            "types": ["book_store", "cafe", ...],
            "primaryType": "book_store",
            "currentOpeningHours": {"openNow": true}
          }
        ]
      }

API key is loaded from $GOOGLE_PLACES_API_KEY. Callers can override via
the constructor arg (useful for tests). If neither is set, we raise
PlacesAPIError at construction time — fail fast.

This module does NOT use the googlemaps SDK — direct REST via requests
matches our transit_api.py pattern and gives us full control over the
FieldMask header (which is the only way to keep the per-request cost
within the free tier).

Usage tracking: each successful HTTP POST increments a counter persisted
to `data/places_api_usage.json` (gitignored). The file is
best-effort observability — if the write fails (permission, disk full,
read-only test runner), the call still succeeds. Use
`PlacesAPIClient.get_usage()` to read the current state, or run
`scripts/check_api_usage.sh` for a quick console summary.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from models.schemas import PlaceSearchResponse


BASE_URL = "https://places.googleapis.com/v1"
NEARBY_SEARCH_PATH = "/places:searchNearby"

# Default field mask. Tuned for the cheapest mix of Essentials + Pro
# fields that still meets the "return name, address, location, opening
# hours" spec. Removing displayName or currentOpeningHours here would
# save ~$0.003/request but break the spec.
DEFAULT_FIELD_MASK = (
    "places.id,"
    "places.displayName,"
    "places.formattedAddress,"
    "places.location,"
    "places.types,"
    "places.primaryType,"
    "places.currentOpeningHours.openNow"
)

DEFAULT_RADIUS_M = 500
DEFAULT_MAX_RESULTS = 5

# Default path for the usage counter file. Gitignored via `data/` in
# .gitignore. Overridable per-client via the constructor.
DEFAULT_USAGE_PATH = Path("data/places_api_usage.json")


class PlacesAPIError(Exception):
    """Raised on missing key, HTTP error, parse failure, or empty payload."""


class PlacesAPIClient:
    """Thin wrapper around Google Places API (New) — Nearby Search only."""

    def __init__(
        self,
        api_key: str | None = None,
        timeout: int = 30,
        usage_path: Path | None = None,
        record_usage: bool = True,
    ) -> None:
        self.api_key = api_key or os.environ.get("GOOGLE_PLACES_API_KEY")
        if not self.api_key:
            raise PlacesAPIError(
                "GOOGLE_PLACES_API_KEY is not set. Add it to your .env file "
                "(gitignored) or pass api_key=... explicitly."
            )
        self.timeout = timeout
        self.session = requests.Session()
        self._usage_path = usage_path or DEFAULT_USAGE_PATH
        self._record_usage_enabled = record_usage

    @classmethod
    def get_usage(cls, usage_path: Path | None = None) -> dict:
        """Read the current Places API usage counter from disk.

        Returns a dict with keys `total_calls`, `last_call`, `daily`
        (date → count). Returns an empty default if the file is
        missing — call sites don't have to guard for first-run.

        Args:
            usage_path: Override the default data/places_api_usage.json
                        path (useful for tests with tmp_path).
        """
        path = usage_path or DEFAULT_USAGE_PATH
        if not path.exists():
            return {"total_calls": 0, "last_call": None, "daily": {}}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # Corrupt file — return empty rather than crash the caller.
            return {"total_calls": 0, "last_call": None, "daily": {}}

    def _record_call(self) -> None:
        """Increment the usage counter; persist to data/places_api_usage.json.

        Best-effort: if the file can't be read, written, or the parent
        dir can't be created, we silently continue. The counter is
        observability, not a gate — failing to record must never
        break a Places API call.
        """
        if not self._record_usage_enabled:
            return
        try:
            path = self._usage_path
            data = self.get_usage(path)
            now = datetime.now(timezone.utc)
            data["total_calls"] = int(data.get("total_calls", 0)) + 1
            today = now.strftime("%Y-%m-%d")
            daily = dict(data.get("daily") or {})
            daily[today] = int(daily.get(today, 0)) + 1
            data["daily"] = daily
            data["last_call"] = now.isoformat()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            # Disk full, read-only filesystem, permission denied, etc.
            # Counter is observability; never break the call.
            pass

    def nearby_search(
        self,
        lat: float,
        lon: float,
        place_type: str,
        radius_m: int = DEFAULT_RADIUS_M,
        max_results: int = DEFAULT_MAX_RESULTS,
        field_mask: str = DEFAULT_FIELD_MASK,
    ) -> "PlaceSearchResponse":
        """Search for places of `place_type` near (lat, lon).

        Args:
            lat:        Center latitude (-90..90).
            lon:        Center longitude (-180..180).
            place_type: Google place type — e.g. "cafe", "park", "library",
                        "museum", "restaurant". See the Places API type
                        table for the full list.
            radius_m:   Search radius in meters (default 500).
            max_results: Max results to return (default 5, max 20 per call).
            field_mask: Override the default field mask if you need
                        additional fields (and accept the SKU bump).

        Returns:
            PlaceSearchResponse with the `results` list. Empty list if no
            places match.
        """
        from models.schemas import PlaceSearchResponse, PlaceSearchResult, LatLng

        url = f"{BASE_URL}{NEARBY_SEARCH_PATH}"
        body = {
            # includedPrimaryTypes (NOT includedTypes) so we only match
            # places whose PRIMARY type is `place_type`. includedTypes
            # matches anywhere in the `types` array — a hotel that has
            # a cafe inside would match "cafe" too, which is wrong for
            # the user query "find cafes near me".
            "includedPrimaryTypes": [place_type],
            "maxResultCount": max_results,
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": lat, "longitude": lon},
                    "radius": radius_m,
                }
            },
        }
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": field_mask,
        }

        try:
            resp = self.session.post(url, json=body, headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise PlacesAPIError(f"network error on Places API: {exc}") from exc

        # Count the HTTP attempt regardless of the response status —
        # failed requests still count against our daily budget. Counter
        # is best-effort: if the disk write fails, the call still works.
        self._record_call()

        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            raise PlacesAPIError(
                f"HTTP {resp.status_code} from Places API: {exc}"
            ) from exc

        try:
            payload = resp.json()
        except ValueError as exc:
            raise PlacesAPIError(f"malformed JSON from Places API: {exc}") from exc

        if not isinstance(payload, dict):
            raise PlacesAPIError(
                f"unexpected payload type from Places API: {type(payload).__name__}"
            )

        raw_places = payload.get("places", [])
        if not isinstance(raw_places, list):
            raise PlacesAPIError(
                f"Places API returned non-list 'places' field: {type(raw_places).__name__}"
            )

        results: list[PlaceSearchResult] = []
        for raw in raw_places:
            if not isinstance(raw, dict):
                continue
            parsed = _to_place_search_result(raw)
            if parsed is None:
                # Entry was too malformed to be useful (missing id or name).
                continue
            results.append(parsed)
        return PlaceSearchResponse(results=results)


def _to_place_search_result(raw: dict) -> "PlaceSearchResult | None":
    """Map a raw API place dict to a PlaceSearchResult model.

    Returns None if the entry is too malformed to be useful — e.g.
    missing `id` or `displayName.text`. Other fields default to safe
    empty values when absent (the API may omit currentOpeningHours
    for parks, primaryType for some entries, etc.).

    Tolerates missing fields by defaulting to safe empty values. The
    API always returns `id` and `displayName.text` when those fields
    are in the FieldMask; other fields can be absent.
    """
    from models.schemas import PlaceSearchResult, LatLng

    place_id = raw.get("id", "")
    if not place_id:
        return None  # unusable without an ID

    display_name = raw.get("displayName", {})
    name = display_name.get("text", "") if isinstance(display_name, dict) else ""
    if not name:
        return None  # unusable without a name

    address = raw.get("formattedAddress", "")
    loc_raw = raw.get("location", {})
    lat = loc_raw.get("latitude", 0.0) if isinstance(loc_raw, dict) else 0.0
    lon = loc_raw.get("longitude", 0.0) if isinstance(loc_raw, dict) else 0.0
    types = raw.get("types", []) or []
    primary_type = raw.get("primaryType")
    hours = raw.get("currentOpeningHours", {})
    open_now = hours.get("openNow") if isinstance(hours, dict) else None

    return PlaceSearchResult(
        place_id=place_id,
        name=name,
        address=address,
        location=LatLng(lat=lat, lon=lon),
        types=types,
        primary_type=primary_type,
        open_now=open_now,
    )