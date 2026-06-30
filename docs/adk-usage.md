# ADK Usage Reference

Everything we learned (and tripped over) using Google ADK to build Komorebi.
Last updated 2026-06-30 against `google-adk==2.3.0` (added §8 closure-bound preprocessor pattern).

---

## 1. Setup

**Pinned in `pyproject.toml`** — keep `google-adk` as a major-version floor, not a hard pin, so we get patch fixes:

```toml
dependencies = [
    "google-adk>=2.3",
    ...
]
```

**API key env var: `GOOGLE_API_KEY`, NOT `GEMINI_API_KEY`.** The ADK GenAI client reads `GOOGLE_API_KEY` first; if you only set `GEMINI_API_KEY` you get `400 INVALID_ARGUMENT — API_KEY_INVALID` even though the SDK "should" have picked it up. We store the real key in `.env` (gitignored, never committed).

---

## 2. Agent factory pattern

Each agent lives in its own module as a **factory function**, not a module-level instance:

```python
# agents/weather_agent.py
def get_current_weather(lat: float | None = None, lon: float | None = None) -> dict:
    """Fetch current weather; default to Tokyo coords."""
    ...

def create_weather_agent(model: str = "gemini-3.1-flash-lite") -> "Agent":
    from google.adk.agents import Agent
    from google.adk.tools import FunctionTool
    return Agent(
        name="weather_agent",
        model=model,
        description="...",
        instruction="...",
        tools=[FunctionTool(get_current_weather)],
    )
```

**Why this shape:**
- `import agents.weather_agent` does NOT pull in `google.adk` (it's behind `TYPE_CHECKING` and a lazy factory import). Tests for the tool fn stay fast and don't need ADK installed.
- Tests can `patch("agents.weather_agent.WeatherAPIClient")` at the module level instead of instantiating an `Agent` (which requires a working LLM endpoint).
- The factory takes `model=` so callers can override the default per-deployment (e.g. swap to `gemini-3.1-flash-lite-preview` for tests).

---

## 3. Tool fn signature rules — primitive types only

ADK introspects tool fn signatures with **Pydantic** to build a JSON schema for the LLM. If your signature contains any non-Pydantic-friendly type, you get `PydanticSchemaGenerationError`.

**Safe types:** `str`, `int`, `float`, `bool`, `list`, `dict`, `None`, `Optional[X]` where `X` is one of the above.

**UNSAFE types** (cause schema gen to fail):
- Custom classes, even `MyClient | None = None`
- Pydantic models with non-JSON-serializable fields
- Anything ADK can't reduce to JSON Schema

**DO NOT:**
```python
def get_transit_routes(origin: str, destination: str, client: TransitAPIClient | None = None):
    ...
```

**DO:**
```python
def get_transit_routes(origin: str, destination: str) -> dict:
    client = TransitAPIClient()  # construct internally
    return client.get_routes(origin, destination).model_dump()
```

Tests then patch the imported class name:
```python
with patch("agents.route_agent.TransitAPIClient") as MockClient:
    instance = MockClient.return_value
    instance.get_routes.return_value = MagicMock(model_dump=lambda: {"routes": []})
    get_transit_routes("渋谷", "池袋")
    MockClient.assert_called_once()
```

---

## 4. InMemoryRunner — async only

All ADK runner APIs have BOTH a sync and an async variant. **The sync variants are deprecated.** The deprecation warning reads `Deprecated. Please migrate to the async method.` and is emitted on every call.

| Sync (DON'T USE) | Async (USE THIS) |
|---|---|
| `runner.run(...)` | `runner.run_async(...)` |
| `runner.session_service.create_session_sync(...)` | `await runner.session_service.create_session(...)` |
| `runner.session_service.get_session_sync(...)` | `await runner.session_service.get_session(...)` |

**Canonical REPL pattern:**

```python
import asyncio
from google.adk.runners import InMemoryRunner
from google.genai import types

async def _run_turn(runner, user_id, session_id, text):
    content = types.Content(role="user", parts=[types.Part(text=text)])
    async for event in runner.run_async(
        user_id=user_id, session_id=session_id, new_message=content
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    print(part.text)

async def _main_async():
    runner = InMemoryRunner(agent=coordinator, app_name="komorebi")
    session = await runner.session_service.create_session(
        app_name="komorebi", user_id="local_user"
    )
    while True:
        user_input = await asyncio.to_thread(input, "> ")
        if user_input.strip().lower() in {"exit", "quit", "q"}:
            break
        await _run_turn(runner, "local_user", session.id, user_input)

def main():
    asyncio.run(_main_async())
```

**Why `asyncio.to_thread` for `input()`:** `input()` is blocking. If you `await asyncio.sleep(...)` instead, the event loop still won't release the GIL for blocking C-level reads — you need to push it to a thread so other coroutines can progress.

**Why the sync `run()` is especially bad:** it shoves the async loop into a background daemon thread. Unhandled exceptions inside the loop escape as `Exception in thread Thread-5 (or N) (_asyncio_thread_main)` instead of bubbling up through your code. Makes debugging miserable.

---

## 5. Deprecations to avoid

| Deprecated | Use instead | Source of warning |
|---|---|---|
| `runner.run()` | `runner.run_async()` | `google/adk/runners.py` |
| `runner.session_service.create_session_sync()` | `await runner.session_service.create_session()` | `google/adk/sessions/in_memory_session_service.py:101` |
| `runner.session_service.get_session_sync()` | `await runner.session_service.get_session()` | `:178` |
| `runner.session_service.list_sessions_sync()` | `await runner.session_service.list_sessions()` | `:257` |
| `runner.session_service.delete_session_sync()` | `await runner.session_service.delete_session()` | `:297` |
| `runner.session_service.append_event_sync()` | `await runner.session_service.append_event()` | (next in file) |

Grep `Deprecated. Please migrate` in `google/adk/` for the canonical list — it gets longer every minor release.

---

## 6. Diagnosing issues

**`UserWarning: [EXPERIMENTAL] feature FeatureName.JSON_SCHEMA_FOR_FUNC_DECL`**
From `google/adk/tools/function_tool.py:95`. ADK 2.3 hasn't fully stabilized Pydantic-based tool schema generation. **Informational, not blocking** — the schema is still emitted. Don't try to suppress it unless you're on ADK 3.x+.

**`PydanticSchemaGenerationError`**
You put a non-primitive type in a tool fn signature. Fix: remove the param, construct the dep internally. See section 3.

**`Deprecated. Please migrate to the async method.`**
You're calling a `*_sync()` API or `runner.run()`. Fix: use the async equivalent. See sections 4 and 5.

**`Exception in thread Thread-N (_asyncio_thread_main)`**
You used `runner.run()`. The async loop is in a daemon thread; unhandled exceptions leak there instead of propagating through your code. Fix: use `run_async()` with `asyncio.run` or your own event loop. See section 4.

**API key errors on a real key (`400 INVALID_ARGUMENT — API_KEY_INVALID`)**
Make sure the env var is `GOOGLE_API_KEY`, not `GEMINI_API_KEY`. See section 1.

---

## 8. Closure-bound tool-layer preprocessors (V2.5)

**The pattern.** When a tool fn needs per-user context (home label,
account ID, tenant key) but ADK's schema-gen rule (§3) forbids
non-primitive params, bind the context at factory time via a closure:

```python
# agents/route_agent.py
def _get_transit_routes_impl(
    origin: str, destination: str,
    exposure_comfort: int = 3,
    _home: str | None = None,    # <-- internal, NOT in the public signature
) -> dict:
    # Layer 3 of home resolution — deterministic keyword substitution
    if _home is not None:
        origin = _resolve_home_keyword(origin, _home)
        destination = _resolve_home_keyword(destination, _home)
    client = TransitAPIClient()
    return client.get_routes(origin=origin, destination=destination, ...).model_dump()


def create_route_agent(
    model: str = "gemini-3.1-flash-lite",
    home: "HomeLocation | None" = None,
) -> "Agent":
    from google.adk.agents import Agent
    from google.adk.tools import FunctionTool

    home_label = home.label if home is not None else None

    def get_transit_routes(
        origin: str, destination: str, exposure_comfort: int = 3,
        via: list[str] | None = None,
        # ... no _home param here
    ) -> dict:
        """Closure — same public signature, _home bound at factory time."""
        return _get_transit_routes_impl(
            origin=origin, destination=destination,
            exposure_comfort=exposure_comfort, via=via,
            _home=home_label,
        )

    return Agent(
        name="route_agent", model=model,
        instruction=("..." + home_agent_hint),
        tools=[FunctionTool(get_transit_routes)],
    )
```

**Why a closure, not a module-level global:**

| Approach | Pros | Cons |
|---|---|---|
| `home_label` as module-level global set by `create_route_agent` | Simple | Tests can't run in parallel; ordering bugs; not thread-safe |
| Pass `home` to the tool fn as a primitive param | Most explicit | LLM has to pass it on every call (error-prone), AND it appears in the tool schema (leaks user context to the LLM, which can echo it back) |
| **Closure binding (this pattern)** ✅ | Hidden from the LLM, deterministic, testable | Requires a factory wrapper per tool fn |

**Why the internal `_home` lives in `_get_transit_routes_impl` and not
the closure:** keeps the impl testable as a plain function. Tests pass
`_home='横浜駅'` directly to the impl; production callers go through
the closure which has `_home=home_label` pre-bound.

**When to reach for this pattern:**
- Tool fn needs user/account/tenant context
- The context is stable for the lifetime of one Agent (not per-call)
- The context is sensitive enough that you don't want it in the LLM-visible schema
- You have a deterministic pre-processing step that should fire even if
  the LLM "forgets" to call the tool correctly

**Our home-resolution pipeline** uses three layers (Coordinator
instruction + sub-agent instruction + this closure preprocessor).
Layers 1 + 2 are LLM-mediated and best-effort; layer 3 is the only
deterministic fallback. See `docs/architecture.md` §4a and
`docs/module-status.md` §8 for the full picture.

---

## Appendix — model selection

We use `gemini-3.1-flash-lite` (stable) for all three agents by default. The full Gemini model list for our key is at:

```
GET https://generativelanguage.googleapis.com/v1beta/models?key=$GOOGLE_API_KEY
```

Notable aliases:
- `gemini-3.1-flash-lite` — pinned stable (preferred)
- `gemini-3.1-flash-lite-preview` — latest preview features
- `gemini-flash-lite-latest` — auto-rolling to newest stable (not reproducible)

Don't use the `-latest` aliases in committed code; pin a specific version.

---

## 7. Transit API — REST vs MCP (2026-06-27)

The same backend (`api.transit.ls8h.com`) exposes both:

- **REST**: `https://api.transit.ls8h.com/api/v1/...` (what we use)
- **MCP**: `https://api.transit.ls8h.com/mcp` (JSON-RPC 2.0, same backend)

**We chose to stay on REST** because:
1. No new dependency — `requests` already handles the JSON shape
2. Same wire data — the MCP `plan_journey` response is byte-identical to `/api/v1/plan`
3. ADK tool fns already prefer plain Python; the MCP transport would be a `requests.post(json={...})` with extra envelope wrapping

The MCP server IS useful for **probing the schema** — `curl -X POST https://api.transit.ls8h.com/mcp -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' -H 'Content-Type: application/json'` gives you a clean tool inventory when the OpenAPI doc is too dense.

For the full surface (all 6 endpoints, the `/plan` param gotchas, curl recipes) see `docs/transit-api.md`. The TL;DR gotchas:

- `allowModes` / `avoidModes` are **comma-separated strings**, not array params
- `avoidWalk` is the **string `"true"`/`"false"`**, not a Python bool
- `via` is a **repeated query param** (`?via=A&via=B`), pass a Python list
- `from` / `to` accept either `feedId:stopId` OR `geo:<lat>,<lon>` (lets `places_agent` skip name resolution)