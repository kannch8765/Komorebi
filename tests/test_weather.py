"""Hermetic tests for WeatherAPIClient (mocked HTTP, no network)."""

from __future__ import annotations

import pytest
import requests

from tools.weather_api import (
    DEFAULT_BASE_URL,
    TOKYO_LAT,
    TOKYO_LON,
    WeatherAPIClient,
    WeatherAPIError,
)


def _mock_response(
    mocker,
    *,
    json_payload=None,
    json_error: Exception | None = None,
    status_error: Exception | None = None,
    status_code: int = 200,
):
    """Build a mock Response with the given JSON / status behavior."""
    mock_response = mocker.Mock()
    mock_response.status_code = status_code
    if json_error is not None:
        mock_response.json.side_effect = json_error
    else:
        mock_response.json.return_value = json_payload
    if status_error is not None:
        mock_response.raise_for_status.side_effect = status_error
    else:
        mock_response.raise_for_status.return_value = None
    return mock_response


def _patch_get(
    mocker,
    json_payload=None,
    json_error=None,
    status_error=None,
    side_effect=None,
    status_code: int = 200,
):
    kwargs: dict = {}
    if side_effect is not None:
        kwargs["side_effect"] = side_effect
    else:
        kwargs["return_value"] = _mock_response(
            mocker,
            json_payload=json_payload,
            json_error=json_error,
            status_error=status_error,
            status_code=status_code,
        )
    return mocker.patch("requests.Session.get", **kwargs)


def test_clear_day_is_outdoor_suitable(mocker):
    payload = {
        "current": {
            "temperature_2m": 26.0,
            "weather_code": 0,
            "precipitation_probability": 5,
        }
    }
    _patch_get(mocker, json_payload=payload)

    client = WeatherAPIClient()
    report = client.get_weather(TOKYO_LAT, TOKYO_LON)

    assert report.weather == "晴れ"
    assert report.temp_c == 26.0
    assert report.rain_probability == pytest.approx(0.05)
    assert report.outdoor_suitable is True


def test_rainy_day_marks_outdoor_unsuitable(mocker):
    payload = {
        "current": {
            "temperature_2m": 22.0,
            "weather_code": 63,
            "precipitation_probability": 80,
        }
    }
    _patch_get(mocker, json_payload=payload)

    client = WeatherAPIClient()
    report = client.get_weather(TOKYO_LAT, TOKYO_LON)

    assert report.weather == "雨"
    assert report.rain_probability == pytest.approx(0.80)
    assert report.outdoor_suitable is False


def test_extreme_cold_marks_outdoor_unsuitable(mocker):
    payload = {
        "current": {
            "temperature_2m": -2.0,
            "weather_code": 0,
            "precipitation_probability": 0,
        }
    }
    _patch_get(mocker, json_payload=payload)

    client = WeatherAPIClient()
    report = client.get_weather(35.0, 135.0)

    assert report.temp_c == -2.0
    assert report.outdoor_suitable is False


def test_extreme_heat_marks_outdoor_unsuitable(mocker):
    payload = {
        "current": {
            "temperature_2m": 38.0,
            "weather_code": 0,
            "precipitation_probability": 0,
        }
    }
    _patch_get(mocker, json_payload=payload)

    client = WeatherAPIClient()
    report = client.get_weather(35.0, 135.0)

    assert report.temp_c == 38.0
    assert report.outdoor_suitable is False


def test_unknown_weather_code_falls_back_to_unknown(mocker):
    payload = {
        "current": {
            "temperature_2m": 20.0,
            "weather_code": 999,
            "precipitation_probability": 10,
        }
    }
    _patch_get(mocker, json_payload=payload)

    client = WeatherAPIClient()
    report = client.get_weather(35.0, 135.0)

    assert report.weather == "不明"
    assert report.outdoor_suitable is True


def test_rain_probability_normalized_from_percent(mocker):
    """OpenMeteo returns 0-100; we expose 0-1 per the schema."""
    payload = {
        "current": {
            "temperature_2m": 20.0,
            "weather_code": 1,
            "precipitation_probability": 42,
        }
    }
    _patch_get(mocker, json_payload=payload)

    client = WeatherAPIClient()
    report = client.get_weather(TOKYO_LAT, TOKYO_LON)

    assert report.rain_probability == pytest.approx(0.42)


def test_http_error_raises(mocker):
    err = requests.HTTPError("500 Server Error")
    _patch_get(mocker, json_payload={}, status_error=err, status_code=500)

    client = WeatherAPIClient()
    with pytest.raises(WeatherAPIError, match="HTTP 500"):
        client.get_weather(TOKYO_LAT, TOKYO_LON)


def test_network_error_raises(mocker):
    _patch_get(mocker, side_effect=requests.ConnectionError("connection refused"))

    client = WeatherAPIClient()
    with pytest.raises(WeatherAPIError, match="network error"):
        client.get_weather(TOKYO_LAT, TOKYO_LON)


def test_timeout_raises(mocker):
    _patch_get(mocker, side_effect=requests.Timeout("timed out"))

    client = WeatherAPIClient()
    with pytest.raises(WeatherAPIError, match="network error"):
        client.get_weather(TOKYO_LAT, TOKYO_LON)


def test_malformed_json_raises(mocker):
    _patch_get(mocker, json_error=ValueError("not json"))

    client = WeatherAPIClient()
    with pytest.raises(WeatherAPIError, match="malformed JSON"):
        client.get_weather(TOKYO_LAT, TOKYO_LON)


def test_missing_current_block_raises(mocker):
    _patch_get(mocker, json_payload={"latitude": 35.7, "longitude": 139.65})

    client = WeatherAPIClient()
    with pytest.raises(WeatherAPIError, match="'current'"):
        client.get_weather(TOKYO_LAT, TOKYO_LON)


def test_query_params_include_lat_lon_timezone(mocker):
    payload = {
        "current": {
            "temperature_2m": 20.0,
            "weather_code": 1,
            "precipitation_probability": 0,
        }
    }
    mock_get = _patch_get(mocker, json_payload=payload)

    client = WeatherAPIClient()
    client.get_weather(35.6762, 139.6503)

    called_args, called_kwargs = mock_get.call_args
    params = called_kwargs["params"]
    assert params["latitude"] == 35.6762
    assert params["longitude"] == 139.6503
    assert params["timezone"] == "Asia/Tokyo"
    assert "temperature_2m" in params["current"]
    assert "weather_code" in params["current"]
    assert "precipitation_probability" in params["current"]