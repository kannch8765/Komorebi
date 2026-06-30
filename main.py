"""Komorebi — interactive entry point.

Run with `uv run python main.py` (requires GOOGLE_PLACES_API_KEY +
GOOGLE_API_KEY env vars; see CLAUDE.md).

Slash commands:
  /home              Show current home
  /home <station>    Set/update home (station must be in TOKYO_COORDS)
  /forget-home       Clear the saved home
  /help              Show available slash commands

Type 'exit', 'quit', 'q', or hit Ctrl-D to leave the REPL.

First-run: if no home is saved, you'll be prompted to pick a station.
The profile is stored locally at data/user_profile.json (gitignored).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models.user_profile import HomeLocation, UserProfile


# Profile lives next to main.py in data/user_profile.json (gitignored).
PROFILE_PATH = Path(__file__).parent / "data" / "user_profile.json"


# ---------------------------------------------------------------------------
# Startup helpers
# ---------------------------------------------------------------------------


def _print_banner(home_label: str | None) -> None:
    """Welcome banner. Shows saved home if any, plus command hints."""
    print("Komorebi へようこそ — 木漏れ日 ☀️")
    if home_label:
        print(f"自宅: {home_label}")
    print("東京でのお出かけをお手伝いします。'exit' で終了。")
    print("コマンド一覧: /home /forget-home /help")


def _resolve_station(station: str) -> tuple[float, float]:
    """Validate `station` is in TOKYO_COORDS; return (lat, lon).

    Normalizes trailing "駅" so users can type "横浜駅" or "横浜" and
    both resolve. Raises ValueError with examples if not found.
    """
    from agents.places_agent import TOKYO_COORDS

    # Strip trailing "駅" so "横浜駅" and "横浜" both match.
    normalized = station[:-1] if station.endswith("駅") else station
    if normalized in TOKYO_COORDS:
        return TOKYO_COORDS[normalized]

    sample = "、".join(sorted(TOKYO_COORDS.keys())[:10]) + "、…"
    raise ValueError(
        f"'{station}' は登録されていない駅です。\n"
        f"登録済みの例: {sample}\n"
        f"（対応外の場所は geocoding 実装後に追加予定）"
    )


def _prompt_home() -> "HomeLocation | None":
    """Ask user for their home station. Returns None if they skip.

    Loops until they provide a valid station, or skip, or exit.
    """
    from models.user_profile import HomeLocation

    print("初回設定: ご自宅の最寄り駅を教えてください。")
    print("（スキップ: 空 Enter / 終了: exit / 後で設定: /home <駅名>）")
    while True:
        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            raise SystemExit(0)
        if raw.lower() in {"exit", "quit", "q"}:
            raise SystemExit(0)
        if not raw:
            return None
        try:
            lat, lon = _resolve_station(raw)
        except ValueError as exc:
            print(exc)
            continue
        return HomeLocation(label=raw, lat=lat, lon=lon)


# ---------------------------------------------------------------------------
# REPL slash commands
# ---------------------------------------------------------------------------


def _handle_slash_command(
    cmd: str,
    profile: "UserProfile",
) -> tuple["UserProfile", bool]:
    """Process a slash command. Returns (new_profile, home_changed)."""
    from models.user_profile import UserProfile

    parts = cmd.strip().split(maxsplit=1)
    name = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if name in {"/help", "/h"}:
        print("コマンド:")
        print("  /home              現在の自宅を表示")
        print("  /home <駅名>       自宅を設定（例: /home 横浜駅）")
        print("  /forget-home       自宅をクリア")
        print("  /help              このヘルプを表示")
        return profile, False

    if name == "/home":
        if not arg:
            if profile.home:
                h = profile.home
                print(f"自宅: {h.label} ({h.lat}, {h.lon})")
            else:
                print("自宅はまだ設定されていません。'/home <駅名>' で設定してください。")
            return profile, False
        # Try to set/update
        try:
            lat, lon = _resolve_station(arg)
        except ValueError as exc:
            print(exc)
            return profile, False
        from models.user_profile import HomeLocation

        new_home = HomeLocation(label=arg, lat=lat, lon=lon)
        new_profile = profile.with_home(new_home)
        try:
            new_profile.save(PROFILE_PATH)
        except OSError as exc:
            print(f"⚠ プロファイルの保存に失敗しました: {exc}")
            return profile, False
        print(f"✓ 自宅を '{arg}' に設定しました。")
        return new_profile, True  # home changed → rebuild coordinator

    if name in {"/forget-home", "/clear-home"}:
        if profile.home is None:
            print("自宅は設定されていません。")
            return profile, False
        new_profile = profile.clear_home()
        try:
            new_profile.save(PROFILE_PATH)
        except OSError as exc:
            print(f"⚠ プロファイルの保存に失敗しました: {exc}")
            return profile, False
        print("✓ 自宅をクリアしました。")
        return new_profile, True  # home changed → rebuild coordinator

    print(f"不明なコマンド: {name}。'/help' で一覧を表示します。")
    return profile, False


# ---------------------------------------------------------------------------
# Agent turn
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


async def _main_async() -> None:
    """Async entry: load profile, create session, loop over user input."""
    from dotenv import load_dotenv

    load_dotenv()

    from google.adk.runners import InMemoryRunner

    from agents.coordinator import create_coordinator
    from models.user_profile import UserProfile

    # Load profile (missing file → default, no error)
    try:
        profile = UserProfile.load(PROFILE_PATH)
    except ValueError as exc:
        print(f"⚠ プロファイルが壊れているため新規作成します: {exc}")
        profile = UserProfile.default()

    # First-run prompt if home is not set
    if profile.home is None:
        prompted = _prompt_home()
        if prompted is not None:
            profile = profile.with_home(prompted)
            try:
                profile.save(PROFILE_PATH)
                print(f"✓ 保存しました: {profile.home.label}")
            except OSError as exc:
                print(
                    f"⚠ 保存に失敗しましたが、このセッション中は使います: {exc}"
                )

    _print_banner(profile.home.label if profile.home else None)
    print()

    runner, session = await _build_runner(profile.home)

    user_id = "local_user"

    while True:
        try:
            user_input = await asyncio.to_thread(input, "> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        s = user_input.strip()
        if not s:
            continue
        if s.lower() in {"exit", "quit", "q"}:
            break
        if s.startswith("/"):
            new_profile, home_changed = _handle_slash_command(s, profile)
            profile = new_profile
            if home_changed:
                runner, session = await _build_runner(profile.home)
                print("(コーディネーターを新しい自宅設定で再起動しました)\n")
            continue

        await _run_turn(runner, user_id, session.id, s)


async def _build_runner(home: "HomeLocation | None") -> tuple:
    """Build Coordinator + InMemoryRunner + session. Returns (runner, session)."""
    from google.adk.runners import InMemoryRunner

    from agents.coordinator import create_coordinator

    coordinator = create_coordinator(home=home)
    runner = InMemoryRunner(agent=coordinator, app_name="komorebi")
    session = await runner.session_service.create_session(
        app_name="komorebi", user_id="local_user"
    )
    return runner, session


def main() -> None:
    """Run the Coordinator agent via ADK's InMemoryRunner in an interactive REPL."""
    asyncio.run(_main_async())


if __name__ == "__main__":
    main()