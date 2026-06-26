"""Komorebi — interactive entry point.

Run with `uv run python main.py` (requires GOOGLE_PLACES_API_KEY +
GEMINI_API_KEY env vars; see CLAUDE.md). Type 'exit' to quit.
"""

from __future__ import annotations


def main() -> None:
    """Run the Coordinator agent via ADK's InMemoryRunner in an interactive REPL."""
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    from agents.coordinator import create_coordinator

    coordinator = create_coordinator()
    runner = InMemoryRunner(agent=coordinator, app_name="komorebi")

    print("Komorebi へようこそ — 木漏れ日 ☀️")
    print("東京でのお出かけをお手伝いします。'exit' で終了。\n")

    user_id = "local_user"
    session = runner.session_service.create_session_sync(app_name="komorebi", user_id=user_id)

    while True:
        try:
            user_input = input("> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if user_input.strip().lower() in {"exit", "quit", "q", ""}:
            if not user_input.strip():
                continue
            break

        content = types.Content(role="user", parts=[types.Part(text=user_input)])
        for event in runner.run(user_id=user_id, session_id=session.id, new_message=content):
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        print(part.text)


if __name__ == "__main__":
    main()