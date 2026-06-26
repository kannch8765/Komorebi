# Komorebi — Developer Guide

## What is this?

Komorebi (木漏れ日) is an AI-powered social anxiety-friendly outing assistant for Tokyo.
It helps users plan outings that minimize crowd exposure while maximizing enjoyment.

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
- Docs: check `/api/v1/feeds` and `/api/v1/operators` for data sources
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
2. Implement the module
3. Write tests
4. Run `pytest -v` and ensure all pass
5. Commit with proper prefix: `git commit -m "feat: add transit API client"`
6. Push: `git push origin main`

## Current Status

See PLAN.md for task list and progress.
