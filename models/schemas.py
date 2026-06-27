from pydantic import BaseModel, Field


class RouteRecommendation(BaseModel):
    name: str
    duration_min: int = Field(..., ge=0)
    transfers: int = Field(..., ge=0)
    crowding_score: float = Field(..., ge=0.0, le=1.0)
    extra_time_min: int = Field(default=0, ge=0)
    stations: list[str]
    lines: list[str]


class RouteResponse(BaseModel):
    routes: list[RouteRecommendation]


class WeatherReport(BaseModel):
    weather: str
    temp_c: float
    rain_probability: float = Field(..., ge=0.0, le=1.0)
    outdoor_suitable: bool


class PlaceRecommendation(BaseModel):
    name: str
    type: str
    crowding_now: float = Field(..., ge=0.0, le=1.0)
    quiet_hours: list[str]
    recharge_suitable: bool


class PlaceResponse(BaseModel):
    recommendations: list[PlaceRecommendation]


# ---------------------------------------------------------------------------
# Google Places API (New) — raw search result shapes
# ---------------------------------------------------------------------------


class LatLng(BaseModel):
    """Latitude / longitude pair returned by the Places API."""

    lat: float = Field(..., ge=-90.0, le=90.0)
    lon: float = Field(..., ge=-180.0, le=180.0)


class PlaceSearchResult(BaseModel):
    """A single place returned by Places API (New) Nearby Search.

    Field names mirror the API's wire format. Pydantic will tolerate
    extra fields the API returns beyond the FieldMask — useful when we
    later add `currentOpeningHours.periods` for richer hours info.

    open_now is Optional because not every place type populates
    currentOpeningHours (e.g. parks may not have business hours).
    """

    place_id: str
    name: str
    address: str
    location: LatLng
    types: list[str]
    primary_type: str | None = None
    open_now: bool | None = None


class PlaceSearchResponse(BaseModel):
    """Wrapper for a Nearby Search result list."""

    results: list[PlaceSearchResult]
