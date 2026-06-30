# Komorebi — Module Status

Canonical source of truth for "what's built, what's not, what's the state of each
module." Last updated 2026-06-30 against `google-adk==2.3.0` (V2.5 personal context shipped).

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
| 15 | UserProfile + Home Resolution (V2.5) | done | `models/user_profile.py`, `agents/route_agent.py`, `agents/coordinator.py`, `main.py` | `tests/test_user_profile.py` (47) + `test_route_agent.py` (19) + `test_coordinator.py` (13) + `test_main.py` (24) | Three-layer home-keyword resolution (Coordinator instruction + sub-agent instruction + closure-bound tool preprocessor). REPL slash commands: `/home`, `/forget-home`, `/help`. `data/user_profile.json` is gitignored (PII). See §8. |

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

**Module 15 — V2.5 Personal Context** (`<pending — see §8>`). Adds
`models/user_profile.py` (frozen `HomeLocation` dataclass + `UserProfile`
JSON persistence with atomic write via `tmp + os.replace`,
`SCHEMA_VERSION = 1`). `agents/route_agent.py` gains a closure-bound
`_home` param on the tool fn and an 11-entry keyword list
(`家`/`自宅`/`home`/`うち`/`現在地`/`出発地`/`出発地点`/`出発`/`自分の場所`/
`私の場所` + English synonyms). `agents/coordinator.py` injects a
"HARD RULE" home hint with literal lat/lon + examples + "DO NOT"
warnings, and threads `home=home` into all sub-agent factories.
`main.py` adds a first-run home prompt and `/home`, `/forget-home`,
`/help` slash commands; the Coordinator is rebuilt on mid-session home
change so the LLM picks up the new hint without a restart.

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
- **Only `home` is persisted (V2.5).** The first cut of `UserProfile`
  only stores `home: HomeLocation | None`. Work (`work: HomeLocation | None`),
  default exposure-comfort slider (`default_slider: int | None`),
  mobility preferences (`avoid_walk: bool | None`), and other
  PII-carrying fields are deliberately NOT in the schema yet — extend
  `UserProfile` + bump `SCHEMA_VERSION` when adding them, and remember
  `data/user_profile.json` is gitignored (real user data must not
  enter the repo).
- **The 527-min Yokohama→Ikebukuro mystery.** In the V2.5 end-to-end
  live test the transit API returned a route time of ~527 min for a
  trip that's normally ~30 min. Likely the ranking picked an outlier
  itinerary (multiple transfers, walking legs). The home-resolution
  feature works correctly; the route-quality issue is a separate
  diagnostic. Suspected cause: the `/plan` endpoint's `via` / mode
  filtering isn't engaged when no constraints are given, so the first
  route can be unusual. Worth a `tools/transit_api.py` audit when we
  revisit route quality.

---

## 8. Personal context (Module 15, V2.5)

The motivation: a Tokyo outing assistant that asks "where are you
starting from?" on every turn is annoying. V2.5 lets the user save
their home once (label + lat/lon) and have the agent resolve home
keywords automatically.

**User flow:**
1. First REPL run → "ご自宅の最寄り駅を「駅名」の形式で入力してください" → user types `横浜駅`
2. `data/user_profile.json` written with `{version: 1, home: {label, lat, lon}}` (gitignored)
3. Subsequent queries containing `家`/`自宅`/`home`/`現在地`/`出発地`/... are
   resolved to the saved label before the transit API call

**Three-layer resolution pipeline** (each layer is a fallback for the
one above; see `docs/architecture.md` §4a for the data-flow diagram):

| Layer | Where | When it fires |
|---|---|---|
| 1. Coordinator instruction | `agents/coordinator.py` `home_hint` | LLM-driven; can be ignored by Gemini |
| 2. Sub-agent instruction | `agents/route_agent.py` `home_agent_hint` | LLM-driven; redundant with layer 1 |
| 3. Tool-fn closure preprocessor | `agents/route_agent.py` `_resolve_home_keyword` | Deterministic — fires on every call |

**Why three layers?** In early V2.5 testing we observed the Coordinator's
LLM picking its own synonyms (`自宅`, `現在地`) instead of the literal
station name the instruction told it to use. Layers 1+2 are best-effort
LLM nudges; only layer 3 fires deterministically. The full keyword
list lives at `agents/route_agent.py:_HOME_KEYWORDS` — extend it
there when adding new home-reference patterns.

**Test coverage** (103 new tests):
- 47 in `tests/test_user_profile.py` — HomeLocation validation,
  UserProfile load/save atomicity, missing file, corrupt JSON, version
  mismatch, `with_home()` / `clear_home()` builders
- 19 in `tests/test_route_agent.py` — keyword substitution, closure
  binding, behavior when `home=None`
- 13 in `tests/test_coordinator.py` — home_hint injection + delegation
  to sub-agents with `home=home`
- 24 in `tests/test_main.py` — `_resolve_station()` suffix stripping,
  `_prompt_home()` / `_handle_slash_command()` dispatch, profile
  load/save in `main.py`

**REPL slash commands:**
- `/home` — set or change the saved home (prompts for station name,
  geocodes via the hardcoded `TOKYO_COORDS` table)
- `/forget-home` — clear the saved home (subsequent queries will ask
  the user for their nearest station instead)
- `/help` — show slash command list
- `/home <station>` — inline form (skips the interactive prompt)

---

## 7. Test counts

- **249 tests** across **13 files** (`tests/test_coordinator.py`,
  `test_crowding.py`, `test_main.py`, `test_places.py`, `test_places_agent.py`,
  `test_route_agent.py`, `test_transit.py`, `test_user_preferences.py`,
  `test_user_profile.py` *(V2.5)*, `test_weather.py`, `test_weather_agent.py`,
  plus `__init__.py`).
- Full-suite runtime is **~2.1s** on a warm cache (collection alone is
  ~0.24s).
- Run with `uv run pytest` from the repo root.
- A pre-commit guard at `scripts/pre_commit_hooks/komorebi_guard.py`
  blocks commits that include personal info (addresses, phone numbers,
  email patterns). Wired via the standard `.pre-commit-config.yaml`
  hook entry.
