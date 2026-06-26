#!/usr/bin/env python3
"""Headless demo driver — exercises Komorebi's data path without an LLM.

The full demo requires GEMINI_API_KEY (for the Coordinator's LLM) and
GOOGLE_PLACES_API_KEY (for V2's Places Agent). This script bypasses the
LLM and routes the 3 MVP demo queries directly to the tool functions, so
the data flow can be verified end-to-end in environments without API
keys.

Run with: `uv run python scripts/demo_headless.py`
"""

from __future__ import annotations

from agents.route_agent import get_transit_routes
from agents.weather_agent import get_current_weather


def hr(title: str) -> None:
    print()
    print("─" * 64)
    print(f"  {title}")
    print("─" * 64)


def show_routes(query: str, origin: str, destination: str) -> None:
    hr(f"Query: {query!r}")
    print(f"  → calling get_transit_routes({origin!r}, {destination!r})")
    try:
        result = get_transit_routes(origin, destination)
    except Exception as exc:
        print(f"  ✗ TransitAPIError: {exc}")
        return

    routes = result.get("routes", [])
    print(f"  → {len(routes)} route(s) returned:")
    for i, r in enumerate(routes, 1):
        print(f"    [{i}] {r['name']}")
        print(f"        duration: {r['duration_min']} min | transfers: {r['transfers']}")
        print(f"        stations: {' → '.join(r['stations'])}")
        print(f"        lines: {', '.join(r['lines'])}")


def show_weather(query: str) -> None:
    hr(f"Query: {query!r}")
    print(f"  → calling get_current_weather() [Tokyo default]")
    try:
        result = get_current_weather()
    except Exception as exc:
        print(f"  ✗ WeatherAPIError: {exc}")
        return

    print(f"  → weather: {result['weather']}")
    print(f"     temp: {result['temp_c']}°C")
    print(f"     rain prob: {result['rain_probability'] * 100:.0f}%")
    print(f"     outdoor suitable: {result['outdoor_suitable']}")


def show_combined(query: str, origin: str, destination: str) -> None:
    """For query 3: dispatch to BOTH route + weather, then synthesize."""
    hr(f"Query: {query!r}")
    print("  → Coordinator dispatches: route_agent + weather_agent (both)")

    # Route leg
    print(f"  → calling get_transit_routes({origin!r}, {destination!r})")
    try:
        route_result = get_transit_routes(origin, destination)
        routes = route_result.get("routes", [])
        print(f"     → {len(routes)} route(s):")
        for i, r in enumerate(routes, 1):
            print(f"        [{i}] {r['name']} — {r['duration_min']} min, {r['transfers']} 乗換")
    except Exception as exc:
        print(f"     ✗ TransitAPIError: {exc}")
        routes = []

    # Weather leg
    print("  → calling get_current_weather() [Tokyo default]")
    try:
        weather_result = get_current_weather()
        print(f"     → {weather_result['weather']}, {weather_result['temp_c']}°C, "
              f"rain {weather_result['rain_probability'] * 100:.0f}%, "
              f"outdoor={weather_result['outdoor_suitable']}")
    except Exception as exc:
        print(f"     ✗ WeatherAPIError: {exc}")
        weather_result = None

    # Synthesis (what the Coordinator would say)
    print()
    print("  → Coordinator synthesis (English summary of what Gemini would output):")
    if routes and weather_result:
        best = routes[0]
        outdoor = "outdoor-friendly" if weather_result["outdoor_suitable"] else "consider indoor backup"
        print(f"     {origin} → {destination} via {best['name']} ({best['duration_min']} min).")
        print(f"     Weather: {weather_result['weather']}, {weather_result['temp_c']}°C — {outdoor}.")
    elif routes:
        print(f"     {origin} → {destination}: {routes[0]['name']} ({routes[0]['duration_min']} min).")
        print("     Weather data unavailable.")
    elif weather_result:
        print(f"     Weather: {weather_result['weather']}, {weather_result['temp_c']}°C.")
        print("     Route data unavailable.")
    else:
        print("     Both route and weather fetches failed.")


def main() -> None:
    print("Komorebi — headless MVP demo driver")
    print("(Bypasses the LLM; exercises transit + weather data paths)")

    show_routes("渋谷から池袋への行き方", "渋谷", "池袋")
    show_weather("今日の天気は？")
    show_combined("新宿から東京駅に行きたい。天気も教えて", "新宿", "東京")

    print()
    print("=" * 64)
    print("Demo complete.")
    print("=" * 64)


if __name__ == "__main__":
    main()