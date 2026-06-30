"""FastAPI wrapper around the Komorebi Coordinator agent.

Module 14 (Cloud Run / web deployment). The REPL (`main.py`) is the
developer surface; this module is the production surface — accepts a
JSON POST and returns the Coordinator's synthesized answer.

Routes:
    GET  /health         liveness check (always 200; no LLM call)
    POST /query          run Coordinator on a single user query, return JSON

POST /query body:
    {
        "query": "池袋の天気",
        "exposure_comfort": 3   # optional, default 3 (balanced)
    }

POST /query response:
    {
        "response": "...",     # Coordinator's synthesized Japanese text
        "query": "...",        # echo
        "exposure_comfort": 3
    }

Environment variables (all read at startup; missing keys log a warning
but don't crash — useful for /health checks on a misconfigured pod):
    PORT                  uvicorn bind port (default 8080)
    GOOGLE_API_KEY        Gemini key for ADK (required for /query)
    GOOGLE_PLACES_API_KEY Google Places key for places_agent
    GEMINI_API_KEY        Legacy alias for GOOGLE_API_KEY (read if GOOGLE absent)

The Coordinator is instantiated **once** at module load and reused across
requests. This is fine for the hackathon demo (low QPS) — for production
multi-tenant use you'd want per-session isolation, but ADK's InMemoryRunner
already manages session state internally.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# Load .env if present (local dev). In production, env vars come from
# the platform (Cloud Run --set-env-vars, Railway dashboard, etc.).
load_dotenv()

logger = logging.getLogger("komorebi.server")
logging.basicConfig(level=logging.INFO)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class QueryRequest(BaseModel):
    """POST /query body."""

    query: str = Field(..., min_length=1, max_length=2000, description="User query in Japanese or English")
    exposure_comfort: int | None = Field(
        default=None,
        ge=1,
        le=5,
        description="Optional 1..5 slider override (1=avoid crowds, 5=fastest)",
    )


class QueryResponse(BaseModel):
    """POST /query response."""

    response: str = Field(..., description="Coordinator's synthesized Japanese text")
    query: str
    exposure_comfort: int


# ---------------------------------------------------------------------------
# Coordinator bootstrap
# ---------------------------------------------------------------------------


def _read_api_keys() -> dict[str, str | None]:
    """Read API keys from env. ADK prefers GOOGLE_API_KEY; GEMINI_API_KEY is the legacy alias."""
    google_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    places_key = os.getenv("GOOGLE_PLACES_API_KEY")
    if not google_key:
        logger.warning(
            "GOOGLE_API_KEY (or GEMINI_API_KEY) is not set — /query will return 503"
        )
    if not places_key:
        logger.warning("GOOGLE_PLACES_API_KEY is not set — places_agent will fail")
    return {"google": google_key, "places": places_key}


def _build_coordinator(exposure_comfort: int | None = None):
    """Instantiate the Coordinator. Lazy import so the module loads without
    google-adk installed (matches the pattern in agents/*_agent.py)."""
    from agents.coordinator import create_coordinator
    from models.user_preferences import UserPreferences

    prefs = (
        UserPreferences(exposure_comfort=exposure_comfort)
        if exposure_comfort is not None
        else None
    )
    return create_coordinator(preferences=prefs)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Komorebi API",
    version="0.1.0",
    description="Tokyo outing planner that minimizes crowd exposure.",
)

# Read keys + build coordinator once at startup.
_KEYS = _read_api_keys()
_COORDINATOR = _build_coordinator()


@app.get("/health")
async def health() -> dict[str, Any]:
    """Liveness probe. Returns 200 with key-availability flags (does NOT
    call the LLM — keep this cheap for Cloud Run / k8s liveness probes)."""
    return {
        "status": "ok",
        "google_api_key_set": bool(_KEYS["google"]),
        "places_api_key_set": bool(_KEYS["places"]),
    }


@app.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest) -> QueryResponse:
    """Run the Coordinator on a single user query and return the answer.

    Note: this endpoint calls the LLM (Gemini) and can take 3-10 seconds.
    For the hackathon demo this is fine; production would want timeouts
    and a queue.
    """
    if not _KEYS["google"]:
        raise HTTPException(
            status_code=503,
            detail="GOOGLE_API_KEY is not configured on this server",
        )

    # If the request overrides exposure_comfort, build a fresh Coordinator
    # so the new slider value is embedded in the instruction. ADK doesn't
    # expose a "patch instruction" API, so we rebuild.
    if req.exposure_comfort is not None and req.exposure_comfort != 3:
        coordinator = _build_coordinator(exposure_comfort=req.exposure_comfort)
        slider_used = req.exposure_comfort
    else:
        coordinator = _COORDINATOR
        slider_used = 3

    try:
        from google.adk.runners import InMemoryRunner
        from google.genai import types

        runner = InMemoryRunner(agent=coordinator, app_name="komorebi_server")
        session = await runner.session_service.create_session(
            app_name="komorebi_server", user_id="http_user"
        )
        content = types.Content(role="user", parts=[types.Part(text=req.query)])

        text_parts: list[str] = []
        async for event in runner.run_async(
            user_id="http_user", session_id=session.id, new_message=content
        ):
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        text_parts.append(part.text)

        synthesized = "".join(text_parts).strip()
        if not synthesized:
            # The agent returned no text — likely a tool-only response.
            synthesized = "(エージェントからの応答テキストがありませんでした)"

        return QueryResponse(
            response=synthesized,
            query=req.query,
            exposure_comfort=slider_used,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Coordinator failed for query %r", req.query)
        raise HTTPException(
            status_code=500,
            detail=f"Coordinator error: {type(exc).__name__}: {exc}",
        )


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("server:app", host="0.0.0.0", port=port, log_level="info")