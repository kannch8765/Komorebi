# Komorebi — PLAN.md

## MVP Tasks (V1: 能跑的demo)

### Module 1: Project Scaffold
- **Priority**: 1 (first)
- **Purpose**: Set up project structure, dependencies, pydantic schemas
- **Files**: requirements.txt, models/schemas.py, config/settings.py, agents/__init__.py, tools/__init__.py
- **Dependencies**: None
- **Acceptance**: `pip install -r requirements.txt` succeeds, schemas importable

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
| 1 | M3 (WSL) | Not started |
| 2 | M3 (WSL) | Not started |
| 3 | M3 (WSL) | Not started |
| 4 | M3 (WSL) | Not started |
| 5 | M3 (WSL) | Not started |
| 6 | M3 (WSL) | Not started |
| 7-14 | TBD | Not started |
