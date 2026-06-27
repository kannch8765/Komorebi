"""Tests for the Google Places API client.

All HTTP responses are mocked, but the mock payloads match the REAL
response shape observed via curl on 2026-06-27 (see tools/places_api.py
docstring for the captured shape).

We use the `responses` library to mock requests.Session calls so we can
inspect headers (X-Goog-FieldMask, X-Goog-Api-Key) in addition to URL.
"""

from __future__ import annotations

import pytest
import responses as responses_lib

from tools.places_api import (
    DEFAULT_FIELD_MASK,
    PlacesAPIClient,
    PlacesAPIError,
)


# ---------------------------------------------------------------------------
# Fixture payloads — exact shapes observed from the real API
# ---------------------------------------------------------------------------


def _place_payload(
    place_id: str = "ChIJ_TEST_ID",
    name: str = "Test Cafe",
    address: str = "1-2-3 Chiyoda, Tokyo 100-0001, Japan",
    lat: float = 35.6812,
    lon: float = 139.7671,
    types: list[str] | None = None,
    primary_type: str | None = "cafe",
    open_now: bool | None = True,
) -> dict:
    """Single place in the REAL API response shape."""
    return {
        "id": place_id,
        "displayName": {"text": name, "languageCode": "en"},
        "formattedAddress": address,
        "location": {"latitude": lat, "longitude": lon},
        "types": types if types is not None else ["cafe", "food", "establishment"],
        "primaryType": primary_type,
        "currentOpeningHours": {"openNow": open_now},
    }


def _nearby_response_payload(places: list[dict] | None = None) -> dict:
    """Top-level Nearby Search response in the REAL shape."""
    if places is None:
        places = [
            _place_payload(name="Cafe A", place_id="id_A", lat=35.6815, lon=139.7673),
            _place_payload(name="Cafe B", place_id="id_B", lat=35.6809, lon=139.7669),
        ]
    return {"places": places}


def _make_client(api_key: str = "test-key", **kwargs) -> PlacesAPIClient:
    return PlacesAPIClient(api_key=api_key, **kwargs)


# ---------------------------------------------------------------------------
# Construction + key handling
# ---------------------------------------------------------------------------


def test_constructor_uses_explicit_api_key():
    """Constructor with explicit key should not require env var."""
    client = _make_client(api_key="explicit-key")
    assert client.api_key == "explicit-key"


def test_constructor_falls_back_to_env_var(monkeypatch):
    """Constructor with no key reads GOOGLE_PLACES_API_KEY from env."""
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "env-key")
    client = PlacesAPIClient()
    assert client.api_key == "env-key"


def test_constructor_raises_when_no_key(monkeypatch):
    """Constructor with no key and no env var raises PlacesAPIError."""
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    with pytest.raises(PlacesAPIError, match="GOOGLE_PLACES_API_KEY is not set"):
        PlacesAPIClient()


# ---------------------------------------------------------------------------
# Successful Nearby Search
# ---------------------------------------------------------------------------


@responses_lib.activate
def test_nearby_search_returns_parsed_results():
    """A 200 with 2 places returns 2 PlaceSearchResult objects."""
    responses_lib.add(
        responses_lib.POST,
        "https://places.googleapis.com/v1/places:searchNearby",
        json=_nearby_response_payload(),
        status=200,
    )

    client = _make_client()
    response = client.nearby_search(lat=35.6812, lon=139.7671, place_type="cafe")

    assert len(response.results) == 2
    a, b = response.results
    assert a.name == "Cafe A"
    assert b.name == "Cafe B"
    assert a.place_id == "id_A"
    assert a.address.startswith("1-2-3 Chiyoda")
    assert a.location.lat == pytest.approx(35.6815)
    assert a.location.lon == pytest.approx(139.7673)
    assert a.primary_type == "cafe"
    assert a.open_now is True


@responses_lib.activate
def test_nearby_search_sends_correct_request_body():
    """The request body must include includedTypes + locationRestriction."""
    captured: dict = {}

    def _callback(request):
        import json
        captured["body"] = json.loads(request.body)
        captured["url"] = request.url
        captured["headers"] = dict(request.headers)
        return (200, {}, json.dumps(_nearby_response_payload()))

    responses_lib.add_callback(
        responses_lib.POST,
        "https://places.googleapis.com/v1/places:searchNearby",
        callback=_callback,
    )

    client = _make_client()
    client.nearby_search(
        lat=35.6812, lon=139.7671, place_type="park",
        radius_m=750, max_results=8,
    )

    assert captured["body"]["includedTypes"] == ["park"]
    assert captured["body"]["maxResultCount"] == 8
    assert captured["body"]["locationRestriction"]["circle"]["radius"] == 750
    center = captured["body"]["locationRestriction"]["circle"]["center"]
    assert center["latitude"] == 35.6812
    assert center["longitude"] == 139.7671


@responses_lib.activate
def test_nearby_search_sends_field_mask_header():
    """The default FieldMask should be sent in X-Goog-FieldMask header."""
    captured: dict = {}

    def _callback(request):
        import json
        captured["headers"] = dict(request.headers)
        return (200, {}, json.dumps(_nearby_response_payload()))

    responses_lib.add_callback(
        responses_lib.POST,
        "https://places.googleapis.com/v1/places:searchNearby",
        callback=_callback,
    )

    client = _make_client()
    client.nearby_search(lat=35.6812, lon=139.7671, place_type="cafe")

    assert captured["headers"].get("X-Goog-FieldMask") == DEFAULT_FIELD_MASK
    assert captured["headers"].get("X-Goog-Api-Key") == "test-key"


@responses_lib.activate
def test_nearby_search_accepts_custom_field_mask():
    """Caller can override the field mask (and accepts the SKU cost)."""
    captured: dict = {}

    def _callback(request):
        import json
        captured["headers"] = dict(request.headers)
        return (200, {}, json.dumps(_nearby_response_payload()))

    responses_lib.add_callback(
        responses_lib.POST,
        "https://places.googleapis.com/v1/places:searchNearby",
        callback=_callback,
    )

    client = _make_client()
    client.nearby_search(
        lat=35.6812, lon=139.7671, place_type="cafe",
        field_mask="places.id,places.displayName",
    )

    assert captured["headers"].get("X-Goog-FieldMask") == "places.id,places.displayName"


# ---------------------------------------------------------------------------
# Edge cases — empty, missing fields, errors
# ---------------------------------------------------------------------------


@responses_lib.activate
def test_nearby_search_empty_places_list():
    """API returns {places: []} → empty results, not an error."""
    responses_lib.add(
        responses_lib.POST,
        "https://places.googleapis.com/v1/places:searchNearby",
        json={"places": []},
        status=200,
    )

    client = _make_client()
    response = client.nearby_search(lat=35.6812, lon=139.7671, place_type="cafe")

    assert response.results == []


@responses_lib.activate
def test_nearby_search_skips_malformed_entries():
    """A malformed entry in the places list is skipped, not fatal."""
    responses_lib.add(
        responses_lib.POST,
        "https://places.googleapis.com/v1/places:searchNearby",
        json={
            "places": [
                _place_payload(name="Good Cafe", place_id="ok"),
                {"id": "bad", "displayName": "string-not-dict"},  # malformed
                _place_payload(name="Another Good", place_id="ok2"),
            ]
        },
        status=200,
    )

    client = _make_client()
    response = client.nearby_search(lat=35.6812, lon=139.7671, place_type="cafe")

    # The malformed entry is skipped; the two good ones come through.
    assert len(response.results) == 2
    assert {r.name for r in response.results} == {"Good Cafe", "Another Good"}


@responses_lib.activate
def test_nearby_search_handles_missing_open_now():
    """Places without currentOpeningHours get open_now=None."""
    place = _place_payload(name="Park")
    place.pop("currentOpeningHours")
    responses_lib.add(
        responses_lib.POST,
        "https://places.googleapis.com/v1/places:searchNearby",
        json={"places": [place]},
        status=200,
    )

    client = _make_client()
    response = client.nearby_search(lat=35.6812, lon=139.7671, place_type="park")

    assert len(response.results) == 1
    assert response.results[0].open_now is None


@responses_lib.activate
def test_nearby_search_handles_missing_primary_type():
    """primaryType is optional — None when absent."""
    place = _place_payload(name="Cafe")
    place.pop("primaryType")
    responses_lib.add(
        responses_lib.POST,
        "https://places.googleapis.com/v1/places:searchNearby",
        json={"places": [place]},
        status=200,
    )

    client = _make_client()
    response = client.nearby_search(lat=35.6812, lon=139.7671, place_type="cafe")

    assert response.results[0].primary_type is None


@responses_lib.activate
def test_nearby_search_http_error_raises():
    """A 4xx/5xx response raises PlacesAPIError matching the status code."""
    responses_lib.add(
        responses_lib.POST,
        "https://places.googleapis.com/v1/places:searchNearby",
        json={"error": {"code": 403, "message": "API key invalid"}},
        status=403,
    )

    client = _make_client(api_key="bad-key")
    with pytest.raises(PlacesAPIError, match="HTTP 403"):
        client.nearby_search(lat=35.6812, lon=139.7671, place_type="cafe")


@responses_lib.activate
def test_nearby_search_malformed_json_raises():
    """Non-JSON response body raises PlacesAPIError."""
    responses_lib.add(
        responses_lib.POST,
        "https://places.googleapis.com/v1/places:searchNearby",
        body="not json{",
        status=200,
    )

    client = _make_client()
    with pytest.raises(PlacesAPIError, match="malformed JSON"):
        client.nearby_search(lat=35.6812, lon=139.7671, place_type="cafe")


@responses_lib.activate
def test_nearby_search_network_error_raises(mocker):
    """Connection failure raises PlacesAPIError with 'network error' message.

    We patch requests.Session.post directly because the `responses`
    library simulates HTTP responses but doesn't model low-level socket
    failures cleanly — patching post() to raise is more explicit.
    Note: requests raises requests.exceptions.ConnectionError (a
    RequestException subclass), NOT the built-in ConnectionError.
    """
    import requests as _requests

    mocker.patch(
        "requests.Session.post",
        side_effect=_requests.exceptions.ConnectionError("dns resolution failed"),
    )

    client = _make_client()
    with pytest.raises(PlacesAPIError, match="network error"):
        client.nearby_search(lat=35.6812, lon=139.7671, place_type="cafe")


@responses_lib.activate
def test_nearby_search_unexpected_payload_type_raises():
    """A non-dict top-level payload raises PlacesAPIError."""
    responses_lib.add(
        responses_lib.POST,
        "https://places.googleapis.com/v1/places:searchNearby",
        json=["not", "a", "dict"],
        status=200,
    )

    client = _make_client()
    with pytest.raises(PlacesAPIError, match="unexpected payload type"):
        client.nearby_search(lat=35.6812, lon=139.7671, place_type="cafe")


# ---------------------------------------------------------------------------
# Field mask contents
# ---------------------------------------------------------------------------


def test_default_field_mask_covers_required_fields():
    """The default field mask must include the spec's required fields."""
    required_substrings = [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.location",
        "places.types",
        "places.primaryType",
        "places.currentOpeningHours.openNow",
    ]
    for sub in required_substrings:
        assert sub in DEFAULT_FIELD_MASK, f"field mask missing: {sub}"