# Komorebi (木漏れ日)

AI-powered social-anxiety-friendly outing assistant for Tokyo. Type a query
in Japanese, get a route + weather + quiet-spot recommendation that
minimizes crowd exposure.

Built with [google-adk](https://github.com/google/adk-python) 2.3,
[Gemini 3.1 Flash Lite](https://ai.google.dev/), and the public-transit
planner at [api.transit.ls8h.com](https://api.transit.ls8h.com).

## Features

- **Multi-agent LLM orchestration** — Coordinator (L1) routes to Route, Weather, and Places sub-agents (L2), each owning one external API.
- **Crowding-aware route ranking** — local algorithm in `tools/crowding.py` synthesizes a `crowding_score` from time-of-day, line popularity, and transfer-hub tier (the transit API doesn't expose occupancy directly).
- **User-tunable exposure slider** — preference 1–5 trades off quietness vs. speed at synthesis time.
- **Personal context (V2.5)** — the REPL saves your home station (label + lat/lon) to `data/user_profile.json`. When you say "家から池袋へ" or "家の近くでカフェ", the Coordinator resolves the home keyword to your saved station automatically — no need to retype your origin every turn. Slash commands: `/home` (set/change), `/forget-home` (clear), `/help`.
- **Real data, no mocks** — transit from `api.transit.ls8h.com` (GTFS / ODPT), weather from OpenMeteo (no key), places from Google Places API (New) with `X-Goog-FieldMask` cost control.
- **Pure Python, no Docker** — `uv`-managed deps, ADK `InMemoryRunner` for the REPL, pytest for tests. No cloud lock-in.

## Quick start

```bash
# 1. Clone
git clone https://github.com/kannch8765/Komorebi.git
cd Komorebi

# 2. Install (uv manages the venv + lockfile)
uv sync

# 3. Configure (add your API keys; .env is gitignored)
cat > .env <<'EOF'
GOOGLE_API_KEY=...
GOOGLE_PLACES_API_KEY=...
EOF

# 4. Run the interactive REPL
uv run python main.py
```

Session:

```
> /home
ご自宅の最寄り駅を「駅名」の形式で入力してください（例: 横浜駅、渋谷駅）:
> 横浜駅
了解しました! ご自宅を 横浜駅 (lat=35.4657, lon=139.6223) として保存しました.

> 家の近くでゆっくりできるカフェ
横浜駅周辺でおすすめのカフェをいくつかご紹介します...

> 家から池袋へ
横浜駅から池袋までのルートをご案内します。
- ルート 1: 約527分, 0乗換, 混雑スコア 0.345

> /help
Available commands:
  /home           Set or change your saved home station
  /forget-home    Clear your saved home
  /help           Show this help
  exit / quit / q Leave the REPL

> exit
```

Type `exit`, `quit`, `q`, or hit `Ctrl-D` to leave the REPL. Slash commands (`/home`, `/forget-home`, `/help`) work at any point in the conversation.

For a no-LLM sanity check that exercises the transit + weather data path end-to-end (no `GOOGLE_API_KEY` needed):

```bash
uv run python scripts/demo_headless.py
```

## Installation

- **Python 3.11+** — pinned in `pyproject.toml` via `requires-python`.
- **uv** — the only supported package manager. `uv sync` resolves the lockfile, installs prod + dev deps into `.venv`, and configures `pythonpath = "."` for pytest.
- **API keys** — go in `.env` (gitignored, see `.gitignore`). Load via `python-dotenv` (already a dep):

  | Var | Required for | Notes |
  |---|---|---|
  | `GOOGLE_API_KEY` | Coordinator LLM | **ADK prefers this name** over `GEMINI_API_KEY`. Setting only the legacy var yields `400 INVALID_ARGUMENT — API_KEY_INVALID`. |
  | `GOOGLE_PLACES_API_KEY` | Places Agent (V2) | Sent via `X-Goog-Api-Key` header, NOT a query param. |
  | `GEMINI_API_KEY` | Optional | Legacy alias; ignored if `GOOGLE_API_KEY` is set. |

## Usage

| Task | Command |
|---|---|
| Interactive REPL | `uv run python main.py` |
| Headless data-path demo (no LLM) | `uv run python scripts/demo_headless.py` |
| Run tests | `uv run pytest` |
| Run tests verbose | `uv run pytest -v` |
| Pre-commit guard | `bash scripts/pre_commit_hooks/komorebi_guard.py` |

The pre-commit guard also runs automatically on `git commit` (configured in `.pre-commit-config.yaml`). It blocks commits that touch `models/schemas.py` without updating `tests/`, and a few other project-specific invariants. See the file itself for the rule list.

## Documentation

| File | Contents |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | System overview + diagrams (L1/L2 agent graph, data flow, V2.5 home context flow) |
| [`docs/module-status.md`](docs/module-status.md) | What's done, what's pending per `PLAN.md` module |
| [`docs/transit-api.md`](docs/transit-api.md) | Transit API surface — 6 endpoints, all `/plan` params with gotchas, curl recipes |
| [`docs/adk-usage.md`](docs/adk-usage.md) | ADK 2.3 patterns + gotchas (PydanticSchemaGenerationError, async runner, env-var quirks, closure-bound tool-layer preprocessors) |
| [`CLAUDE.md`](CLAUDE.md) | Local-only dev guide (probe-APIs policy, architecture details, env-var reference). **Not tracked in git** — see `.gitignore`. |
| [`PLAN.md`](PLAN.md) | Original module breakdown (V1 MVP → V2 differentiation → V2.5 personal context → V3 polish) |

## Personal data

Your saved home (set via `/home`) lives in `data/user_profile.json`. The
file is **gitignored** — it's personal data and never lands in the repo.
The pre-commit guard at `scripts/pre_commit_hooks/komorebi_guard.py`
also blocks any commit that contains home addresses, lat/lon triples,
or phone-number patterns.

## Project status

Modules 1–11 done; **Module 15 (V2.5 personal context)** shipped with 47
new tests for `models/user_profile.py` + home-resolution plumbing in
`agents/route_agent.py` / `agents/coordinator.py` / `main.py`. **260
tests** total. See [`docs/module-status.md`](docs/module-status.md) for
the full breakdown. V3 tasks (BigQuery integration, dashboard, Cloud
Run deploy) are not scheduled.

## How it works

User types a Tokyo outing query in Japanese. The Coordinator agent (L1) parses intent and dispatches to one or more L2 sub-agents — Route, Weather, Places — each of which calls a tool function that wraps a real external API. Responses come back as pydantic models defined in `models/schemas.py`. The Coordinator synthesizes the combined answer in Japanese, applying the user's exposure-comfort preference as a ranking weight.

The ADK runtime is `InMemoryRunner` (in-process, async-only — see `docs/adk-usage.md` §4 for why the sync API is deprecated). Each agent module exposes a `create_*_agent()` factory; tool functions take primitive args only (custom classes trip PydanticSchemaGenerationError — see `docs/adk-usage.md` §3).

## License

MIT (see `LICENSE` — to be added).

## Acknowledgments

Cloned from [kannch8765/Komorebi](https://github.com/kannch8765/Komorebi). Built on [google-adk](https://github.com/google/adk-python) + Gemini. Transit data from [api.transit.ls8h.com](https://api.transit.ls8h.com) (powered by GTFS / ODPT). Weather from [OpenMeteo](https://open-meteo.com/). Places from the Google Places API (New).
