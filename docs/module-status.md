# Komorebi — Module Status

Canonical source of truth for "what's built, what's not, what's the state of each
module." Last updated 2026-06-27 against `google-adk==2.3.0` on commit `9accb82`.

If something here disagrees with the actual code or with `PLAN.md`, the code
wins — please update this file in the same PR that changes the state.

---

## 1. Status legend

| Icon | Meaning |
|------|---------|
| done  | Module is implemented, committed, and covered by tests. |
| partial | Some sub-pieces are in but the module is not feature-complete. |
| not started | Planned in `PLAN.md`, no code yet. |
| blocked | Cannot progress without external dependency or decision. |

---

## 2. Module table

| # | Module | Status | Files | Tests | Notes |
|---|--------|--------|-------|-------|-------|
| 1 | Project Scaffold | done | `pyproject.toml`, `uv.lock`, `models/schemas.py`, `models/user_preferences.py`, `config/settings.py`, `agents/__init__.py`, `tools/__init__.py` | — | pydantic v2 schemas + ADK floor pin (`google-adk>=2.3`). |
| 2 | Transit API Client | done | `tools/transit_api.py` | `tests/test_transit.py` (32) | Wraps `api.transit.ls8h.com`. Extended by commit `9accb82` (see §4). |
| 3 | Weather API Client | done | `tools/weather_api.py` | `tests/test_weather.py` (12) | OpenMeteo, no key. Adds `outdoor_suitable` decision. |
| 4 | Route Agent | done | `agents/route_agent.py` | `tests/test_route_agent.py` (10) | Exposes `exposure_comfort` slider as a primitive int param. |
| 5 | Weather Agent | done | `agents/weather_agent.py` | `tests/test_weather_agent.py` (7) | Defaults to Tokyo coords. |
| 6 | Coordinator (MVP) | done | `agents/coordinator.py`, `main.py` | `tests/test_coordinator.py` (6) | L1 router, Route + Weather only. Superseded by Module 11. |
| 7 | Google Places Client | done | `tools/places_api.py` | `tests/test_places.py` (17) | Nearby Search via `X-Goog-FieldMask` for cost control. |
| 8 | Places Agent | done | `agents/places_agent.py` | `tests/test_places_agent.py` (8) | Uses hardcoded `TOKYO_COORDS` table to resolve district mentions. |
| 9 | Crowding Score Algorithm | done | `tools/crowding.py` | `tests/test_crowding.py` (18) | Pure-local heuristic (no API crowding field exists). |
| 10 | Exposure Tradeoff Slider | done | `models/user_preferences.py` | `tests/test_user_preferences.py` (20) | 1..5 slider; linear map to `weight_crowding`. |
| 11 | Coordinator V2 | done | `agents/coordinator.py` (updated) | `tests/test_coordinator.py` (6) | Adds Places sub-agent + slider injection. |
| 12 | BigQuery Integration | not started | `tools/bigquery.py` (planned) | — | Analytics on route/crowding queries. |
| 13 | Dashboard | not started | TBD (planned) | — | Looker or web dashboard for crowding trends. |
| 14 | Cloud Run Deployment | not started | `Dockerfile`, `cloudbuild.yaml` (planned) | — | Container + Cloud Build pipeline. |

---

## 3. Done modules

**Module 1 — Project Scaffold** (`5a20b72`). Sets up `pyproject.toml` / `uv.lock`,
Pydantic v2 schemas in `models/schemas.py`, the social-anxiety preference
dataclass, and a personal-info pre-commit guard so private data never lands in
the repo.

**Module 2 — Transit API Client** (`e530f88`). Thin wrapper around
`https://api.transit.ls8h.com` returning a Pydantic `RouteResponse`. Hermetic
tests use `responses` to mock HTTP. The original client was rewritten against
the real spec in `250fd62` and then significantly extended — see §4.

**Module 3 — Weather API Client** (`720b3a0`). Hits the free OpenMeteo forecast
endpoint for Tokyo, decodes the WMO weather code to a Japanese label, and adds
an `outdoor_suitable` decision from rain probability + temperature thresholds.

**Module 4 — Route Agent** (`2c2e7ce`). ADK `Agent` that wraps
`TransitAPIClient` as a single `get_transit_routes` tool. Primitive-only
signature (the `client` object is hidden behind the tool surface so ADK's
Pydantic schema generation does not crash).

**Module 5 — Weather Agent** (`489f904`). ADK `Agent` wrapping
`WeatherAPIClient`. Defaults to Tokyo coords when the user doesn't specify
lat/lon. Same primitive-signature pattern as Module 4.

**Module 6 — Coordinator MVP** (`d0ff3cd`). L1 router that dispatches to Route
+ Weather sub-agents. Also adds `main.py` as a headless demo entry point. The
MVP coordinator was later superseded by Module 11 — the file is the same
`agents/coordinator.py`, the factory just got richer.

**Module 7 — Google Places Client** (`1bcdcff`). Implements Nearby Search
against `places.googleapis.com/v1/places:searchNearby` with `X-Goog-FieldMask`
for cost control. The `f81ae62` fix added `includedPrimaryTypes` so a cafe
search doesn't return hotels that happen to have cafes inside.

**Module 8 — Places Agent** (`33fd194`). ADK `Agent` wrapping
`PlacesAPIClient`. Resolves Tokyo district mentions via a hardcoded
`TOKYO_COORDS` table (~29 stations) since we have no geocoding tool yet.

**Module 9 — Crowding Score Algorithm** (`fc35ba8`). Pure-local deterministic
heuristic combining time-of-day, line popularity, and transfer-hub congestion
to produce a `[0.0, 1.0]` crowding score. The transit API has no occupancy
field, so this is an approximation — not real-time data.

**Module 10 — Exposure Tradeoff Slider** (`8f59703`). `UserPreferences`
dataclass with `exposure_comfort: 1..5` mapping linearly to `weight_crowding`
in `[0.85, 0.15]`. Routes are ranked by
`w_crowding * normalized_crowding + w_time * normalized_duration`.

**Module 11 — Coordinator V2** (`33fd194`). Updates `coordinator.py` to wire
the Places sub-agent in and inject the `exposure_comfort` slider into the
delegation instruction. Also rebuilt the runner for async ADK 2.3 and
swapped to `gemini-3.1-flash-lite` (`648f473`).

---

## 4. Transit client extension (commit `9accb82`)

A second pass on Module 2 — not a new module, but worth its own section
because it nearly doubled the client surface.

**Added `/plan` query parameters:**
- `via` (str) — through-station hint
- `trip_type` (str) — `departure | arrival | first | last`
- `avoid_modes` / `allow_modes` (list[str]) — mode filters
- `avoid_walk` (bool), `max_transfers` (int)
- `date` / `time` (str) — explicit journey time
- `from_label` / `to_label` / `via_label` (str) — display labels

**New methods on `TransitAPIClient`:**
- `suggest_places(query, near=None, limit=5)` — name-based place search
- `reverse_geocode(lat, lon)` — coords → nearest station
- `get_station_info(station_id)` — static station metadata
- `get_departures(station_id, line_ids=None, limit=20)` — live departure board

**Docs:** full request/response shapes and a `/mcp` vs REST comparison live
at `docs/transit-api.md`.

**Tests:** +20 new cases in `tests/test_transit.py` (32 total in that file),
pushing the suite from 127 → 147.

---

## 5. Not started (Modules 12–14)

**Module 12 — BigQuery Integration.** A `tools/bigquery.py` client that writes
each route / weather / places query (and the chosen plan) to BigQuery for
later analysis. Deprioritize until we have real users; in the meantime
`tools/crowding.py` is enough signal for evaluation.

**Module 13 — Dashboard.** Looker or a simple web dashboard over the
BigQuery tables from Module 12. Pure-stretch goal; no point building the
analytics pipeline before the data layer exists.

**Module 14 — Cloud Run Deployment.** `Dockerfile` + `cloudbuild.yaml` to ship
Komorebi as a web service. Defer until the UX surface settles — running it
locally via `main.py` is fine for development.

---

## 6. Known issues / limitations

- **No real crowding data.** The transit API has no occupancy / load field,
  so `tools/crowding.py` is a pure-local heuristic (time of day + line
  popularity + transfer hubs). See its module docstring for the full
  rationale.
- **Hardcoded `TOKYO_COORDS` table.** The Places Agent ships with a ~29-row
  table of common Tokyo stations because we have no geocoding tool.
  Module 12+ candidate: replace it with `transit_api.reverse_geocode()`.
- **No free-text geocoding.** Users must name a station or district; we
  cannot turn "near my office in Setagaya" into lat/lon yet.
- **ODPT license restrictions.** Some stations return `403` on
  `/api/v1/stations/{id}/departures` because the underlying ODPT feed
  restricts that endpoint by license scope. Falling back to `/plan` is
  the workaround.
- **Coordinator can pick a 終電 plan, but UI doesn't surface "first / last"
  timing structurally.** `trip_type=last` is supported end-to-end, but the
  final user-facing answer still needs a clear "this is the last train"
  affordance.
- **ADK 2.3 experimental-feature warning.** On import you may see
  `UserWarning: [EXPERIMENTAL] feature FeatureName.JSON_SCHEMA_FOR_FUNC_DECL`.
  This is informational, not blocking — ADK is using an experimental
  Pydantic codepath to build tool schemas. See `docs/adk-usage.md` §2.

---

## 7. Test counts

- **147 tests** across **12 files** (`tests/test_coordinator.py`,
  `test_crowding.py`, `test_main.py`, `test_places.py`, `test_places_agent.py`,
  `test_route_agent.py`, `test_transit.py`, `test_user_preferences.py`,
  `test_weather.py`, `test_weather_agent.py`, plus `__init__.py`).
- Full-suite runtime is **~2.1s** on a warm cache (collection alone is
  ~0.24s).
- Run with `uv run pytest` from the repo root.
- A pre-commit guard at `scripts/pre_commit_hooks/komorebi_guard.py`
  blocks commits that include personal info (addresses, phone numbers,
  email patterns). Wired via the standard `.pre-commit-config.yaml`
  hook entry.
