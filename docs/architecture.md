# Komorebi — Architecture

Single-page architecture overview. For deeper references see
`docs/adk-usage.md` (ADK patterns), `docs/transit-api.md` (transit endpoints
+ gotchas), and the per-tool client docstrings.

Last updated 2026-06-27.

---

## 1. System overview

Komorebi (木漏れ日) is a Tokyo outing-planning assistant that minimizes crowd
exposure for users with social anxiety. It is a Python 3.11+ application
managed by `uv`, built on `google-adk 2.3`, and uses Gemini
(`gemini-3.1-flash-lite`) as its LLM. The user-facing shape is a REPL chat
(`python main.py`): the user types a Tokyo outing query in Japanese or
English (e.g. "渋谷から池袋、人混み避けたい" / "Shibuya cafe + weather + route")
and receives a streamed Japanese recommendation. The system fans the query
out to three L2 agents (Route, Weather, Places) — each wrapping a thin
REST client to a real external API — and the L1 Coordinator synthesizes the
combined answer. The transit API does not expose real-time occupancy, so
crowding scores are computed locally by a deterministic heuristic in
`tools/crowding.py`.

---

## 2. Component map

### L1 — Coordinator

| Layer | Component | Purpose | File |
|---|---|---|---|
| L1 | Coordinator Agent | Routes user query to L2 sub-agent(s) via LLM-driven dispatch; synthesizes Japanese answer | `agents/coordinator.py` |
| L1 | Coordinator factory | `create_coordinator(model, preferences)` — builds Agent with `sub_agents=[route, weather, places]` | `agents/coordinator.py` |

### L2 — Sub-agents

| Layer | Component | Purpose | File |
|---|---|---|---|
| L2 | Route Agent | Tokyo transit route planner. Tool fn: `get_transit_routes` | `agents/route_agent.py` |
| L2 | Weather Agent | Tokyo current-weather reporter. Tool fn: `get_current_weather` | `agents/weather_agent.py` |
| L2 | Places Agent | Finds nearby cafes/parks/libraries via Google Places. Tool fn: `search_places` | `agents/places_agent.py` |

### Tools — API clients

| Layer | Component | Purpose | File |
|---|---|---|---|
| Tool | `TransitAPIClient` | REST wrapper for `api.transit.ls8h.com` (6 endpoints, REST not MCP) | `tools/transit_api.py` |
| Tool | `WeatherAPIClient` | REST wrapper for `api.open-meteo.com/v1/forecast` (free, no key) | `tools/weather_api.py` |
| Tool | `PlacesAPIClient` | REST wrapper for `places.googleapis.com/v1/places:searchNearby` | `tools/places_api.py` |
| Tool | `tools.crowding` | Pure-local crowding-score heuristic (time-of-day + line popularity + transfer hubs) | `tools/crowding.py` |

### Models — Pydantic v2 schemas

| Layer | Component | Purpose | File |
|---|---|---|---|
| Model | `RouteResponse` / `RouteRecommendation` | Route + per-leg metadata, `crowding_score` ∈ [0, 1] | `models/schemas.py` |
| Model | `WeatherReport` | Tokyo current weather + `outdoor_suitable` flag | `models/schemas.py` |
| Model | `PlaceSearchResponse` / `PlaceSearchResult` / `LatLng` | Google Places Nearby Search result list | `models/schemas.py` |
| Model | `PlaceRecommendation` / `PlaceResponse` | V1-style recommendation shape (unused by L2 Places agent) | `models/schemas.py` |
| Model | `UserPreferences` | `exposure_comfort` slider 1..5, mapped to `weight_crowding` / `weight_time` | `models/user_preferences.py` |

### Entry points

| Layer | Component | Purpose | File |
|---|---|---|---|
| Entry | `main.py` | Interactive REPL — `InMemoryRunner` + async streaming, `exit`/`quit` to leave | `main.py` |
| Entry | `scripts/demo_headless.py` | No-LLM demo driver — calls tool fns directly to verify the data path | `scripts/demo_headless.py` |

### External APIs

| API | Base | Auth | Notes |
|---|---|---|---|
| Transit planner | `https://api.transit.ls8h.com` | None (public) | 6 REST endpoints; no crowding/occupancy data; MCP variant at `/mcp` |
| Weather (OpenMeteo) | `https://api.open-meteo.com/v1/forecast` | None | Free, no key, Tokyo coords 35.6762 / 139.6503 |
| Google Places (New) | `https://places.googleapis.com/v1` | `X-Goog-Api-Key` header | FieldMask controls per-request cost |

---

## 3. Data flow

```
User input ("渋谷で静かなカフェ" / "Shibuya cafe + weather + route")
   |
   v
main.py: InMemoryRunner.run_async()  -- streams events
   |
   v
Coordinator (Gemini decides which L2 sub-agent(s) to call)
   |
   +---> places_agent: search_places(lat, lon, place_type, radius_m, max_results)
   |         |
   |         v
   |     PlacesAPIClient.nearby_search()  -- POST /places:searchNearby
   |         |
   |         v
   |     PlaceSearchResponse (pydantic)
   |
   +---> route_agent: get_transit_routes(origin, destination, exposure_comfort, ...)
   |         |
   |         v
   |     TransitAPIClient.get_routes()  -- 2-step: /locations/suggest -> /plan
   |         |
   |         v
   |     tools.crowding.score_route()   -- pure-local heuristic
   |         |
   |         v
   |     rank_routes() by UserPreferences weights  -- RouteResponse (pydantic)
   |
   +---> weather_agent: get_current_weather(lat, lon)
             |
             v
         WeatherAPIClient.get_weather()  -- GET /v1/forecast
             |
             v
         WeatherReport (pydantic)
   |
   v
Coordinator synthesizes combined Japanese answer from sub-agent dicts
   |
   v
Streamed text events back to the REPL via event.content.parts
```

---

## 4. Agent hierarchy

```
coordinator (gemini-3.1-flash-lite)
|-- route_agent
|   `-- tool: get_transit_routes(origin, destination, exposure_comfort, ...)
|         \-- TransitAPIClient.get_routes() -> score_route() -> rank_routes()
|-- weather_agent
|   `-- tool: get_current_weather(lat=None, lon=None)
|         \-- WeatherAPIClient.get_weather()
`-- places_agent
    `-- tool: search_places(lat, lon, place_type, radius_m, max_results)
          \-- PlacesAPIClient.nearby_search()
```

`sub_agents=[route_agent, weather_agent, places_agent]` is wired in
`create_coordinator()`; ADK handles LLM-driven delegation. Each sub-agent
has a single `FunctionTool` whose signature uses **primitive types only**
(ADK schema-gen constraint — see `docs/adk-usage.md`).

---

## 5. Tool to API mapping

| Tool fn | Client method | External API | Endpoints touched |
|---|---|---|---|
| `get_transit_routes` | `TransitAPIClient.get_routes()` → `resolve_station_id()` + `get_routes_by_id()` | api.transit.ls8h.com | `GET /api/v1/locations/suggest`, `GET /api/v1/plan` |
| `get_current_weather` | `WeatherAPIClient.get_weather()` | api.open-meteo.com | `GET /v1/forecast?latitude&longitude&current=...` |
| `search_places` | `PlacesAPIClient.nearby_search()` | places.googleapis.com | `POST /v1/places:searchNearby` |
| (internal) | `TransitAPIClient.suggest_places()` | api.transit.ls8h.com | `GET /api/v1/places/suggest` |
| (internal) | `TransitAPIClient.reverse_geocode()` | api.transit.ls8h.com | `GET /api/v1/places/reverse` |
| (internal) | `TransitAPIClient.get_station_info()` | api.transit.ls8h.com | `GET /api/v1/stations/{id}` |
| (internal) | `TransitAPIClient.get_departures()` | api.transit.ls8h.com | `GET /api/v1/stations/{id}/departures` |
| (pure local) | `tools.crowding.score_route()` | none | no I/O — deterministic, time injected by caller |

The transit `/plan` endpoint supports `via`, `trip_type`, `avoidModes`,
`allowModes`, `avoidWalk`, `maxTransfers`, `date`, `time`, `fromLabel`,
`toLabel`, `viaLabel` — all forwarded from `get_transit_routes` primitive
params. See `docs/transit-api.md` for the full param-by-param spec and
type gotchas (e.g. `avoidModes` is a comma-separated string, not an
array param).

---

## 6. Module dependency graph

```
agents/coordinator.py
  |-- agents/route_agent.py
  |     |-- models/schemas.py           (RouteResponse)
  |     |-- tools/transit_api.py
  |     |     |-- models/schemas.py     (RouteResponse, RouteRecommendation)
  |     |     `-- tools/crowding.py    (pure local, no deps)
  |     `-- models/user_preferences.py (UserPreferences, rank_routes)
  |
  |-- agents/weather_agent.py
  |     `-- tools/weather_api.py
  |           `-- models/schemas.py     (WeatherReport)
  |
  `-- agents/places_agent.py
        `-- tools/places_api.py
              `-- models/schemas.py     (PlaceSearchResponse, PlaceSearchResult, LatLng)

main.py
  `-- agents/coordinator.py  (create_coordinator, InMemoryRunner)

scripts/demo_headless.py
  |-- agents.route_agent.get_transit_routes
  `-- agents.weather_agent.get_current_weather
```

`google.adk` is imported **lazily inside the factory functions**
(`create_*_agent`), so the tool fns and the API clients import cleanly
without `google-adk` on the path. This is what makes the test suite fast
and lets `tools/` and `models/` be unit-tested in isolation.

---

## 7. Key design decisions

- **Primitive-only tool fn signatures.** ADK introspects tool fns with
  Pydantic to build the LLM schema. Any non-primitive type (custom client
  classes, Pydantic models with non-JSON fields) raises
  `PydanticSchemaGenerationError`. Tool fns accept only `str / int /
  float / bool / list / dict / None` and instantiate the API client
  internally. See `docs/adk-usage.md` for the full rule.
- **Crowding is computed locally.** `api.transit.ls8h.com` does not
  expose passenger-occupancy / load / crowding fields (we probed the
  OpenAPI spec). `tools/crowding.py` derives a deterministic score from
  three signals: time-of-day rush-hour peaks, line popularity (substring
  match on `routeName`), and transfer-hub congestion. The function is
  pure (no `datetime.now()`, no I/O) so it is unit-testable; callers
  inject the journey's start time explicitly via `CrowdingFactors`.
- **Station resolution is 2-step.** `get_routes()` first calls
  `resolve_station_id()` (hit `/locations/suggest`), then `get_routes_by_id()`
  (hit `/plan`). The station sort prefers `score=3` (rail/subway) over
  `score=2` (bus stops) so a JR/Metro line is picked when both exist.
- **Places agent uses a hardcoded Tokyo coord table.** There is no
  geocoding tool yet (planned for Module 12+). The instruction embeds a
  curated table of ~30 well-known Tokyo districts / stations (渋谷,
  新宿, 池袋, 銀座, ...) so the LLM can resolve district mentions to
  lat/lon deterministically. Users can pass lat/lon directly for
  arbitrary locations.
- **Pydantic v2 models for all API responses.** `models/schemas.py` is
  the single source of truth for inter-agent JSON shapes. Clients parse
  raw dicts into pydantic models, raise on schema violations, and the
  tool fns return `model.model_dump()` so ADK can stream them as plain
  JSON to the LLM.
- **Direct REST, no SDKs.** The transit and places clients use `requests`
  directly (no `googlemaps` SDK, no JSON-RPC client for the transit MCP
  variant). Reasons: full control over the `X-Goog-FieldMask` header
  (the only way to control Places cost), no extra protocol layer for
  transit (REST and MCP are equally well-documented, REST is one dep
  shorter).
- **Factory functions, not module-level instances.** Each agent lives
  in its own module as `create_*_agent(model)`. Importing the module
  does NOT pull in `google.adk` (lazy import inside the factory), so
  tool-fn tests don't need a working LLM endpoint. The tool fn itself
  is the testable surface; the `Agent` is wire-up.
- **REPL is streaming, async.** `main.py` uses `InMemoryRunner.run_async()`
  and prints `event.content.parts[*].text` as events arrive, so the user
  sees Japanese tokens appear incrementally rather than waiting for the
  full response.

---

## 8. Files layout

```
komorebi/
|-- main.py                       # REPL entry point
|-- pyproject.toml                # uv-managed deps (google-adk>=2.3, pydantic, requests)
|-- uv.lock
|-- CLAUDE.md                     # developer guide (probes, env, refs)
|-- PLAN.md                       # module task list
|-- .env                          # gitignored — GOOGLE_PLACES_API_KEY, GOOGLE_API_KEY
|
|-- agents/                       # ADK Agent definitions + tool fns
|   |-- coordinator.py
|   |-- route_agent.py
|   |-- weather_agent.py
|   `-- places_agent.py
|
|-- tools/                        # REST clients + pure-local helpers
|   |-- transit_api.py
|   |-- weather_api.py
|   |-- places_api.py
|   `-- crowding.py               # pure local, no I/O
|
|-- models/                       # Pydantic v2 schemas
|   |-- schemas.py                # Route, Weather, Place inter-agent shapes
|   `-- user_preferences.py       # exposure_comfort slider
|
|-- config/
|   `-- settings.py
|
|-- scripts/
|   |-- demo_headless.py          # no-LLM smoke test
|   `-- pre_commit_hooks/
|
|-- tests/                        # pytest (per-tool + per-agent + integration)
|
`-- docs/
    |-- architecture.md           # this file
    |-- adk-usage.md              # ADK gotchas + patterns
    `-- transit-api.md            # full transit REST reference
```
