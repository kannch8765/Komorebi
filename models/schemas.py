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
