# Komorebi — PLAN.md

## MVP Tasks (V1: 能跑的demo)

### Module 1: Project Scaffold
- **Priority**: 1 (first)
- **Purpose**: Set up project structure, dependencies, pydantic schemas
- **Files**: pyproject.toml, uv.lock, models/schemas.py, config/settings.py, agents/__init__.py, tools/__init__.py
- **Dependencies**: None
- **Acceptance**: `uv sync` succeeds, schemas importable

### Module 2: Transit API Client
- **Priority**: 1
- **Purpose**: Wrap transit API (api.transit.ls8h.com) to fetch routes
- **Files**: tools/transit_api.py, tests/test_transit.py
- **Dependencies**: Module 1
- **Acceptance**: Can fetch route from station A to B, returns parsed JSON, tests pass

### Module 3: Weather API Client
- **Priority**: 1
- **Purpose**: Wrap OpenMeteo API for Tokyo weather
- **Files**: tools/weather_api.py, tests/test_weather.py
- **Dependencies**: Module 1
- **Acceptance**: Can fetch current weather for Tokyo coords, returns parsed JSON, tests pass

### Module 4: Route Agent
- **Priority**: 2
- **Purpose**: ADK agent that uses transit tool to find routes
- **Files**: agents/route_agent.py
- **Dependencies**: Module 2
- **Acceptance**: Agent can answer "渋谷から池袋への行き方" with route data

### Module 5: Weather Agent
- **Priority**: 2
- **Purpose**: ADK agent that uses weather tool
- **Files**: agents/weather_agent.py
- **Dependencies**: Module 3
- **Acceptance**: Agent can answer "今日の天気は？" with weather data

### Module 6: Coordinator (MVP)
- **Priority**: 3
- **Purpose**: L1 agent that dispatches to Route + Weather agents
- **Files**: agents/coordinator.py, main.py
- **Dependencies**: Module 4, 5
- **Acceptance**: User can type destination → get route + weather combined response

---

## V2 Tasks (Core Differentiation)

### Module 7: Google Places Client
- **Purpose**: Fetch popular times / crowding data
- **Files**: tools/places_api.py, tests/test_places.py
- **Dependencies**: Module 1

### Module 8: Places Agent
- **Purpose**: L2 agent for quiet spot recommendations
- **Files**: agents/places_agent.py
- **Dependencies**: Module 7

### Module 9: Crowding Score Algorithm
- **Purpose**: Multi-route comparison with crowding scores
- **Files**: tools/crowding.py, tests/test_crowding.py
- **Dependencies**: Module 2

### Module 10: Exposure Tradeoff Slider
- **Purpose**: User preference input → weight adjustment → route ranking
- **Files**: Update coordinator.py, add preference handling
- **Dependencies**: Module 6, 9

### Module 11: Coordinator V2
- **Purpose**: Full orchestration with Places + slider + recharge spots
- **Files**: Update coordinator.py
- **Dependencies**: Module 8, 10

---

## V2.5 Tasks (Personal Context)

### Module 15: UserProfile + Home Resolution + REPL Slash Commands
- **Purpose**: Let the user save their home station once (label + lat/lon)
  and have the agent resolve home keywords (`家`, `自宅`, `home`, `現在地`,
  `出発地`, etc.) automatically across turns. Goal: "家から池袋へ" works
  without the user re-typing their origin.
- **Files**:
  - `models/user_profile.py` — `HomeLocation` (frozen dataclass) +
    `UserProfile` (load/save via atomic JSON write, schema versioning)
  - `agents/route_agent.py` — tool-layer preprocessor that resolves home
    keywords via closure-bound `_home` param (safety net for the
    Coordinator's instruction-based resolution)
  - `agents/coordinator.py` — imperative "HARD RULE" home hint + wires
    `home=home` to all sub-agent factories
  - `agents/places_agent.py` / `agents/weather_agent.py` — accept `home=None`
    for API symmetry (unused for now)
  - `main.py` — first-run home prompt + `/home`, `/forget-home`, `/help`
    slash commands + coordinator rebuild on mid-session home change
  - `data/user_profile.json` — runtime-only, **gitignored** (PII)
  - `tests/test_user_profile.py` (47 tests) + extensions to
    `test_route_agent.py`, `test_coordinator.py`, `test_main.py`
- **Dependencies**: Module 6 (Coordinator MVP), Module 4 (Route Agent)
- **Acceptance**:
  - `uv run pytest` → 249 passing
  - End-to-end: `/home 横浜駅` → `> 家から池袋へ` returns a real route
    from `横浜駅` (not the literal string `家`)
  - Without a saved home, the Coordinator politely asks the user for
    their nearest station instead of crashing
- **Three-layer defense** for keyword resolution (in priority order):
  1. Coordinator instruction tells the LLM to pre-resolve home keywords
     to literal coords BEFORE delegating
  2. Each sub-agent's instruction reiterates the resolution rule for its
     own delegation context
  3. The tool fn itself substitutes keywords at call time via the
     closure-bound `_home` label — catches everything that slips through
- **Status**: Done (2026-06-30). 47 + 19 + 13 + 24 = 103 new tests.

---

## V3 Tasks (Polish)

### Module 12: BigQuery Integration
- **Purpose**: Store route/crowding queries for analytics
- **Files**: tools/bigquery.py

### Module 13: Dashboard
- **Purpose**: Looker or web dashboard for crowding trends
- **Files**: TBD

### Module 14: Cloud Run Deployment
- **Purpose**: Deploy as web service
- **Files**: Dockerfile, cloudbuild.yaml

---

## Task Assignment

| Module | Assignee | Status |
|--------|----------|--------|
| 1 | M3 (WSL) | Done |
| 2 | M3 (WSL) | Done |
| 3 | M3 (WSL) | Done |
| 4 | M3 (WSL) | Done |
| 5 | M3 (WSL) | Done |
| 6 | M3 (WSL) | Done (superseded by 11) |
| 7 | M3 (WSL) | Done |
| 8 | M3 (WSL) | Done |
| 9 | M3 (WSL) | Done |
| 10 | M3 (WSL) | Done |
| 11 | M3 (WSL) | Done |
| 12-14 | TBD | Not scheduled |
| 15 (V2.5) | M3 (WSL) | Done |
