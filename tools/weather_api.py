"""Weather API client for Komorebi (OpenMeteo, free, no key needed)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from models.schemas import WeatherReport

DEFAULT_BASE_URL = "https://api.open-meteo.com/v1/forecast"
DEFAULT_TIMEOUT = 30

# Tokyo reference coords (per CLAUDE.md).
TOKYO_LAT = 35.6762
TOKYO_LON = 139.6503

# outdoor_suitable decision thresholds.
_RAIN_PROBABILITY_OUTDOOR_LIMIT = 0.30
_TEMP_MIN_OUTDOOR_C = 5.0
_TEMP_MAX_OUTDOOR_C = 35.0

# WMO weather code → Japanese label. Subset of codes OpenMeteo emits.
# Codes outside this map fall back to "不明".
_WMO_CODE_TO_JA: dict[int, str] = {
    0: "晴れ",
    1: "晴れ時々曇り",
    2: "曇り時々晴れ",
    3: "曇り",
    45: "霧",
    48: "霧氷",
    51: "小雨",
    53: "霧雨",
    55: "強い霧雨",
    61: "小雨",
    63: "雨",
    65: "強い雨",
    71: "小雪",
    73: "雪",
    75: "強い雪",
    80: "にわか雨",
    81: "強いにわか雨",
    82: "激しいにわか雨",
    95: "雷雨",
    96: "雷雨(雹あり)",
    99: "激しい雷雨",
}


class WeatherAPIError(Exception):
    """Raised on HTTP, parse, or missing-field failures from the weather API."""


class WeatherAPIClient:
    """Thin wrapper around OpenMeteo returning Pydantic WeatherReport."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def get_weather(self, lat: float, lon: float) -> "WeatherReport":
        """Fetch current weather for the given lat/lon and return WeatherReport."""
        params = {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,precipitation_probability,weather_code",
            "timezone": "Asia/Tokyo",
        }
        try:
            response = self.session.get(self.base_url, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise WeatherAPIError(
                f"network error fetching weather for ({lat}, {lon}): {exc}"
            ) from exc

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise WeatherAPIError(
                f"HTTP {response.status_code} from weather API for ({lat}, {lon}): {exc}"
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise WeatherAPIError(
                f"malformed JSON from weather API for ({lat}, {lon}): {exc}"
            ) from exc

        if not isinstance(payload, dict):
            raise WeatherAPIError(
                f"unexpected payload type {type(payload).__name__} from weather API"
            )

        current = payload.get("current")
        if not isinstance(current, dict):
            raise WeatherAPIError("weather API response missing 'current' object")

        return _build_weather_report(current)


def _build_weather_report(current: dict) -> "WeatherReport":
    """Build WeatherReport from OpenMeteo's `current` block."""
    from models.schemas import WeatherReport

    weather = _weather_label(current.get("weather_code"))
    temp_c = _to_float(current.get("temperature_2m"), default=0.0)
    # OpenMeteo returns precipitation_probability as 0-100; normalize to 0-1.
    rain_probability = _to_float(current.get("precipitation_probability"), default=0.0) / 100.0

    outdoor_suitable = (
        rain_probability <= _RAIN_PROBABILITY_OUTDOOR_LIMIT
        and _TEMP_MIN_OUTDOOR_C <= temp_c <= _TEMP_MAX_OUTDOOR_C
    )

    return WeatherReport(
        weather=weather,
        temp_c=temp_c,
        rain_probability=rain_probability,
        outdoor_suitable=outdoor_suitable,
    )


def _weather_label(raw_code: object) -> str:
    try:
        code = int(raw_code)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "不明"
    return _WMO_CODE_TO_JA.get(code, "不明")


def _to_float(raw: object, default: float) -> float:
    try:
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default