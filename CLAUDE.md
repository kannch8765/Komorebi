# Komorebi — Developer Guide

## What is this?

Komorebi (木漏れ日) is an AI-powered social anxiety-friendly outing assistant for Tokyo.
It helps users plan outings that minimize crowd exposure while maximizing enjoyment.

## ⚠️ Probe Real APIs Before Implementing

**Before writing any client / tool / wrapper code for an external API, probe the real endpoint first.** The endpoint shapes, params, and response fields in `## API References` below may be hallucinated, outdated, or wrong — they were in past incidents (CLAUDE.md once described a fictional `GET /api/v1/routes?origin=&destination=` that didn't exist; the real API requires station IDs via `/locations/suggest` → `/plan`).

**How to probe:**

```bash
# 1. Find the OpenAPI / Swagger spec (most modern APIs expose one)
curl <base_url>/openapi.json
curl <base_url>/api/openapi.json

# 2. If no OpenAPI, fetch the landing page and look for doc links
curl <base_url>

# 3. Then curl a real endpoint to confirm the response shape
curl "<endpoint>?<params>"
```

**Then** write the client + tests against the actual response shape. Update `## API References` below if the spec was wrong.

**Red flags for fictional specs** — if you see any of these in `CLAUDE.md` or `PLAN.md`, the spec is probably hallucinated:
- API host that's a creative permutation of common words
- Endpoint paths that follow REST conventions but the actual API uses different verbs/paths
- Response fields that don't match any real schema (GTFS/ODPT/OpenAPI/Google Places/etc.)
- Endpoint that requires nothing (no IDs, no auth) — most real APIs need at least one identifier

See `docs/adk-usage.md` for other ADK gotchas (PydanticSchemaGenerationError, async runner, etc.).

## Architecture

```
L1: Coordinator Agent (router + synthesis)
├── L2: Route Agent      → Transit API
├── L2: Weather Agent    → OpenMeteo API
└── L2: Places Agent     → Google Places API
```

User flow:
1. User says what they want to do (or where to go)
2. If no destination → Places Agent suggests quiet spots
3. Route Agent + Weather Agent fetch data in parallel
4. Coordinator synthesizes and recommends routes ranked by comfort score
5. User can adjust exposure tradeoff slider (time vs quietness)

## Tech Stack

- **Agent framework**: Google ADK
- **LLM**: Gemini
- **Route data**: Transit API (`api.transit.ls8h.com`)
- **Weather**: OpenMeteo (free, no key needed)
- **Places/crowding**: Google Places API
- **Data warehouse**: BigQuery
- **Deployment**: Cloud Run
- **Language**: Python 3.11+

## Project Structure

```
komorebi/
├── agents/
│   ├── __init__.py
│   ├── coordinator.py      # L1 orchestrator
│   ├── route_agent.py      # L2 transit
│   ├── weather_agent.py    # L2 weather
│   └── places_agent.py     # L2 places
├── tools/
│   ├── __init__.py
│   ├── transit_api.py      # Transit API client
│   ├── weather_api.py      # OpenMeteo client
│   └── places_api.py       # Google Places client
├── models/
│   ├── __init__.py
│   └── schemas.py          # Pydantic models for inter-agent JSON
├── config/
│   ├── __init__.py
│   └── settings.py         # Settings via env vars
├── tests/
│   ├── __init__.py
│   ├── test_transit.py
│   ├── test_weather.py
│   └── test_places.py
├── main.py                 # Entry point
├── requirements.txt
├── CLAUDE.md
├── PLAN.md
└── README.md
```

## Coding Standards

- Type hints on all function signatures
- Pydantic models for all inter-agent data (defined in `models/schemas.py`)
- No hardcoded API keys — use environment variables via `config/settings.py`
- Tests in `tests/` using pytest
- Docstrings: one line max, only when the function name isn't self-explanatory
- Commit messages: `feat:` / `fix:` / `docs:` / `test:` prefix

## Inter-Agent JSON Schemas

### Route Agent Output
```json
{
  "routes": [
    {
      "name": "最短ルート",
      "duration_min": 30,
      "transfers": 2,
      "crowding_score": 0.8,
      "extra_time_min": 0,
      "stations": ["渋谷", "新宿", "池袋"],
      "lines": ["JR山手線", "丸ノ内線"]
    }
  ]
}
```

### Weather Agent Output
```json
{
  "weather": "晴れ",
  "temp_c": 26,
  "rain_probability": 0.1,
  "outdoor_suitable": true
}
```

### Places Agent Output
```json
{
  "recommendations": [
    {
      "name": "代々木公園",
      "type": "park",
      "crowding_now": 0.2,
      "quiet_hours": ["10:00-12:00", "14:00-16:00"],
      "recharge_suitable": true
    }
  ]
}
```

## API References

### Transit API
- Base URL: `https://api.transit.ls8h.com`
- OpenAPI spec: `https://api.transit.ls8h.com/api/openapi.json`
- **Two-step flow** for journey search:
  1. `GET /api/v1/locations/suggest?q={name}&limit=5` → list of `{id, name, score, weight}`; pick by `score DESC, weight DESC` (prefer rail score=3 over bus score=2)
  2. `GET /api/v1/plan?from={from_id}&to={to_id}&numItineraries=3` → `{journeys: [{durationSecs, transferCount, legs: [{from, to, routeName}]}]}`
- No crowding / occupancy / realtime data — crowding is computed locally by `tools/crowding.py`
- GTFS / ODPT based

### OpenMeteo
- Base URL: `https://api.open-meteo.com/v1/forecast`
- No API key needed
- Tokyo coords: lat=35.6762, lon=139.6503

### Google Places API
- Requires API key (set as `GOOGLE_PLACES_API_KEY` env var)
- Use Place Details for popular times / crowding data

## Environment Variables

```bash
GOOGLE_PLACES_API_KEY=   # Google Places API key
GEMINI_API_KEY=          # Gemini API key for ADK
```

## Development Workflow

0. **First-time setup**: `uv sync` (installs deps + dev group from `pyproject.toml` into `.venv`)
1. Read the current task from PLAN.md
2. **If the task touches an external API, [probe the real endpoint first](#️-probe-real-apis-before-implementing)** — see the callout above. Don't trust the spec in `## API References`.
3. Implement the module (or update the spec if it was wrong)
4. Write tests
5. Run `pytest -v` and ensure all pass
6. Commit with proper prefix: `git commit -m "feat: add transit API client"`
7. Push: `git push origin main`

## Current Status

See PLAN.md for task list and progress.
