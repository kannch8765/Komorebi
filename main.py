"""Komorebi — interactive entry point.

Run with `uv run python main.py` (requires GOOGLE_PLACES_API_KEY +
GEMINI_API_KEY env vars; see CLAUDE.md). Type 'exit' to quit.
"""

from __future__ import annotations

import asyncio


async def _run_turn(runner, user_id: str, session_id: str, text: str) -> None:
    """One async turn: send the user message, print text events as they stream."""
    from google.genai import types

    content = types.Content(role="user", parts=[types.Part(text=text)])
    async for event in runner.run_async(
        user_id=user_id, session_id=session_id, new_message=content
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    print(part.text)


async def _main_async() -> None:
    """Async entry: create session, then loop over user input via asyncio.to_thread."""
    from google.adk.runners import InMemoryRunner

    from agents.coordinator import create_coordinator

    coordinator = create_coordinator()
    runner = InMemoryRunner(agent=coordinator, app_name="komorebi")

    print("Komorebi へようこそ — 木漏れ日 ☀️")
    print("東京でのお出かけをお手伝いします。'exit' で終了。\n")

    user_id = "local_user"
    session = await runner.session_service.create_session(
        app_name="komorebi", user_id=user_id
    )

    while True:
        try:
            user_input = await asyncio.to_thread(input, "> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if user_input.strip().lower() in {"exit", "quit", "q", ""}:
            if not user_input.strip():
                continue
            break

        await _run_turn(runner, user_id, session.id, user_input)


def main() -> None:
    """Run the Coordinator agent via ADK's InMemoryRunner in an interactive REPL."""
    asyncio.run(_main_async())


if __name__ == "__main__":
    main()