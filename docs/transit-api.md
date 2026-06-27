# Transit API Reference

What we wrap, what we call, and the gotchas — for the `api.transit.ls8h.com` REST service that backs `tools/transit_api.py`.

Base URL: `https://api.transit.ls8h.com` (CORS-enabled, read-only, no auth). Canonical schema lives at `/api/openapi.json` — probe it directly when in doubt.

---

## 1. Overview

`TransitAPIClient` in `tools/transit_api.py` is a thin wrapper. It does two things:

1. **Resolve station names** — Japanese / English display strings (e.g. `渋谷`, `新宿`) → canonical `feedId:stopId` IDs. Required because `/api/v1/plan` and `/api/v1/stations/{id}/departures` only accept IDs (or `geo:<lat>,<lon>`).
2. **Fetch journeys** — between two station IDs, returning ranked itineraries we hand to `models.schemas.RouteResponse`.

The API has no API key, no rate limit headers worth budgeting around, and no SDK — `requests.Session.get` is the whole transport. We layer `TransitAPIError` on top for HTTP / parse / not-found failures.

### Endpoints we use

| Endpoint | Used for |
|---|---|
| `/api/v1/locations/suggest` | Name → station ID resolution |
| `/api/v1/plan` | Journey search (the main call) |
| `/api/v1/stations/{id}` | Station detail (platforms, serving routes) |
| `/api/v1/stations/{id}/departures` | Departure board for a single station |
| `/api/v1/places/suggest` | Place autocomplete (stations + facilities + addresses) |
| `/api/v1/places/reverse` | Reverse-geocode a map point to nearby places |

The live API also exposes `/api/v1/guidance/plan` (guide-UI contract with map geometry and decision factors) and `/api/v1/feeds`, `/api/v1/operators`, `/api/health`. We don't call any of those — they exist for the web app and are listed here only so you don't go hunting in the schema for them.

---

## 2. Endpoint reference

| Method | URL | Purpose | Komorebi method |
|---|---|---|---|
| GET | `/api/v1/locations/suggest` | Station autocomplete (multilingual prefix) | `TransitAPIClient.resolve_station_id` |
| GET | `/api/v1/plan` | Journey search (出発 / 到着 / 始発 / 終電) | `TransitAPIClient.get_routes`, `get_routes_by_id` |
| GET | `/api/v1/stations/{id}` | Station detail: platforms and serving routes | `TransitAPIClient.get_station_info` |
| GET | `/api/v1/stations/{id}/departures` | Departure board for a station | `TransitAPIClient.get_departures` |
| GET | `/api/v1/places/suggest` | Place autocomplete: stations + facilities + addresses | `TransitAPIClient.suggest_places` |
| GET | `/api/v1/places/reverse` | Nearby places for a picked map point | `TransitAPIClient.reverse_geocode` |

---

## 3. `/api/v1/plan` parameters

| Name | Type | Required | Default | What it does |
|---|---|---|---|---|
| `from` | string | yes | — | Origin. A station id (`feedId:stopId`) or `geo:<lat>,<lon>`. |
| `to` | string | yes | — | Destination. Same shape as `from`. |
| `fromLabel` | string | no | — | Optional display name for the origin (≤ 120 chars). |
| `toLabel` | string | no | — | Optional display name for the destination. |
| `viaLabel` | string | no | — | Optional display label, positionally matched to `via[]`. (The OpenAPI schema declares this as a single string in the `/plan` path; use the array form only on `/guidance/plan`.) |
| `date` | string | no | today (in result tz) | Service date `YYYYMMDD`. |
| `time` | string | no | now | `HH:MM` or `HH:MM:SS`. |
| `type` | enum | no | `departure` | One of `departure` / `arrival` / `first` / `last` (出発 / 到着 / 始発 / 終電). |
| `allowModes` | string | no | — | **Comma-separated** transit modes to allow, e.g. `rail,bus`. Pre-scan filter. |
| `avoidModes` | string | no | — | **Comma-separated** transit modes to avoid, e.g. `bus,air,ferry`. Pre-scan filter. |
| `avoidWalk` | string | no | `false` | **`"true"` or `"false"`** (string, not bool). Exclude any itinerary with a walking segment. |
| `maxTransfers` | int | no | `3` | 0–8. |
| `numItineraries` | int | no | `3` | 1–6. |
| `via` | string[] | no | — | Up to **3** waypoints, each `feedId:stopId` or `geo:<lat>,<lon>`. Departure/arrival searches only. |

### Type gotchas (the ones that bit us)

- `allowModes` / `avoidModes` are **comma-separated strings**, not arrays. `requests` will not auto-serialize a Python list — pass `"rail,bus"` literally.
- `avoidWalk` is the string `"true"` / `"false"`, not a Python bool. `requests` would otherwise turn `True` into `True` in the query string and the server would reject it.
- `type` enum is a **string** but only accepts `departure` / `arrival` / `first` / `last`. There's no `now` value — `first` is "earliest train after the time" and `last` is "latest train before the time".
- `via` is a **repeated query param** (`?via=A&via=B&via=C`), not a JSON array. In `requests`, pass a Python list — it serializes correctly.
- `from` / `to` accept either a `feedId:stopId` ID (preferred — exact, deterministic) **or** `geo:<lat>,<lon>` (snaps to the nearest station in the planner). Mixing the two is fine.
- `date` is `YYYYMMDD`, not ISO. `time` is `HH:MM` (or `HH:MM:SS`), not 24-hour `HHMM` and not seconds-since-midnight.

---

## 4. When to use which parameter

A few rules of thumb for the route_agent:

| User signal | What to set |
|---|---|
| "急いでて 18:00 に着きたい" | `type='arrival'`, `time='18:00'`, `date` defaulted or set explicitly |
| "21:00 始発で帰りたい" | `type='first'`, `time='21:00'` |
| "終電で帰って" | `type='last'`, `time='23:59'` (or omit) |
| "バスは嫌" | `avoid_modes=['bus']` |
| "電車だけで" | `allow_modes=['rail']` (or `['rail', 'subway']` depending on operator taxonomy) |
| "歩きたくない" | `avoid_walk=True` (Python bool — the tool fn / ADK schema uses boolean; the client converts to API string internally) |
| "新宿で買い物してから帰る" | `via=[<Shinjuku id>]` (max 3 waypoints) |
| "乗換 0 回がいい" | `max_transfers=0` |

The route_agent's instructions should prefer **name → ID resolution** (`locations/suggest`) over `geo:<lat>,<lon>` whenever the user names a place. Geo mode is for "from my current location" inputs where we already have a coordinate from the map picker.

---

## 5. Curl recipes

All three verified against the live API on 2026-06-27.

**Resolve a station name:**

```bash
curl -sS "https://api.transit.ls8h.com/api/v1/locations/suggest?q=%E6%B8%8B%E8%B0%B7&limit=2"
```

```json
{
  "stations": [
    {
      "id": "scrape-jreast-saikyo:odpt.Station:JR-East.SaikyoKawagoe.Shibuya",
      "name": "渋谷",
      "nameKana": "しぶや",
      "feedId": "scrape-jreast-saikyo",
      "feedName": "埼京線",
      "score": 3,
      "weight": 29,
      "lat": 35.6585367,
      "lon": 139.6991599,
      "kind": "station"
    }
  ]
}
```

**Plan a journey (arrive by 18:00, geo origins, no bus, no walking):**

```bash
curl -sS "https://api.transit.ls8h.com/api/v1/plan?from=geo:35.6580,139.7016&to=geo:35.7295,139.7109&type=arrival&time=18:00&avoidModes=bus&avoidWalk=true&numItineraries=2"
```

```json
{
  "date": "20260627",
  "type": "arrival",
  "timezone": "Asia/Tokyo",
  "from": { "id": "geo:35.6580,139.7016", "name": "地点(35.6580, 139.7016)" },
  "to":   { "id": "geo:35.7295,139.7109", "name": "地点(35.7295, 139.7109)" },
  "journeys": [
    {
      "departureSecs": 64800,
      "arrivalSecs":   71759,
      "durationSecs":  6959,
      "transferCount": 0,
      "legs": [
        {
          "kind": "transit",
          "routeName": "湘南新宿ライン（北行（大宮・高崎・宇都宮方面））",
          "mode": "rail",
          "color": "e85514",
          "headsign": "快速 籠原",
          "tripId": "scrape-jreast-shonan-shinjuku:shonan-shinjuku-saturdayHoliday-secondary-2844Y-61380",
          "from": { "id": "scrape-jreast-shonan-shinjuku:odpt.Station:JR-East.ShonanShinjuku.Shibuya", "name": "渋谷" },
          "to":   { "id": "scrape-jreast-shonan-shinjuku:odpt.Station:JR-East.ShonanShinjuku.Ikebukuro", "name": "池袋" }
        }
      ]
    }
  ]
}
```

**Multi-stop via waypoint:**

```bash
curl -sS "https://api.transit.ls8h.com/api/v1/plan?from=scrape-jreast-saikyo:odpt.Station:JR-East.SaikyoKawagoe.Shibuya&to=scrape-jreast-saikyo:odpt.Station:JR-East.SaikyoKawagoe.Ikebukuro&via=scrape-jreast-yamanote:odpt.Station:JR-East.Yamanote.Shinjuku&type=departure&time=15:00"
```

---

## 6. Caveats

- **No crowding / occupancy field.** The `/plan` response carries `transferCount`, `durationSecs`, `departureSecs`, `arrivalSecs`, and per-leg `mode` / `routeName` / `headsign` / `tripId`, but nothing about how full the train is. We synthesize a `crowding_score` in `tools/crowding.py` from time-of-day, line popularity, and transfer-hub tier — see the docstring there for the factors.
- **`feedId:stopId` IDs are operator-specific.** A station name like `渋谷` resolves to multiple IDs across feeds (JR Saikyo, JR Yamanote, Tokyu, Tokyo Metro Fukutoshin, etc.). The client picks the highest `score` first (rail = 3, bus = 2), then highest `weight` within a tier — see `resolve_station_id`. If a user asks specifically for the Tokyu platform, you need to re-resolve with operator filtering or a different `locations/suggest` payload.
- **Times are seconds from service-date midnight.** Per the API's own description, `departureSecs` / `arrivalSecs` may exceed 86400 (after-midnight service continuing past midnight) or be negative (yesterday's service still running at the user's local time). Format for display client-side — do not blindly do `secs / 3600` and call it hours.
- **ODPT terms gate departure boards.** `/api/v1/stations/{id}/departures` returns 403 for feeds whose terms don't allow departure-board presentation. The API description explicitly notes "ODPT-published timetable data is used for journey planning, but the API does not expose ODPT's published station/train timetable information as a departure-board dataset." Expect sparse / 403-heavy results.
- **`via` is unsupported on `first` / `last` searches** — the schema says "Departure/arrival searches only" and you'll get a 422 otherwise.
- **No retry on 5xx by default.** `_get` raises `TransitAPIError` on the first failure. If the orchestrator wants retry-with-backoff, wrap the call at the agent layer, not the client.
