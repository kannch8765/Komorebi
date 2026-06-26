# ADK Usage Reference

Everything we learned (and tripped over) using Google ADK to build Komorebi.
Last updated 2026-06-27 against `google-adk==2.3.0`.

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