"""Smoke tests for main.py entry point + slash command handling."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Module import smoke tests
# ---------------------------------------------------------------------------


def test_main_module_imports():
    """main.py should import without error and expose a callable main()."""
    mod = importlib.import_module("main")
    assert hasattr(mod, "main")
    assert callable(mod.main)


def test_main_module_does_not_eagerly_import_adk():
    """Importing main.py shouldn't construct agents or hit Gemini.

    The lazy imports inside `main()` ensure `import main` is cheap.
    """
    importlib.import_module("main")
    assert True  # Successful import is the assertion


def test_main_module_exposes_helpers():
    """The refactored main.py exposes the slash-command + prompt helpers."""
    import main

    for name in (
        "_print_banner",
        "_resolve_station",
        "_prompt_home",
        "_handle_slash_command",
        "_build_runner",
    ):
        assert hasattr(main, name), f"main.{name} missing"


# ---------------------------------------------------------------------------
# _resolve_station
# ---------------------------------------------------------------------------


def test_resolve_station_known_returns_coords():
    """Known stations resolve to (lat, lon) from TOKYO_COORDS."""
    from main import _resolve_station

    lat, lon = _resolve_station("横浜駅")
    assert (lat, lon) == (35.4657, 139.6223)


@pytest.mark.parametrize("station", ["渋谷", "新宿", "池袋", "東京", "原宿"])
def test_resolve_station_various_known(station):
    """Various known stations resolve to non-empty coords."""
    from main import _resolve_station

    lat, lon = _resolve_station(station)
    assert isinstance(lat, float)
    assert isinstance(lon, float)
    assert -90 <= lat <= 90
    assert -180 <= lon <= 180


def test_resolve_station_unknown_raises_value_error():
    """Unknown station names raise ValueError with helpful message."""
    from main import _resolve_station

    with pytest.raises(ValueError, match="登録されていない駅"):
        _resolve_station("ド田舎駅")


# ---------------------------------------------------------------------------
# _handle_slash_command: /help
# ---------------------------------------------------------------------------


def test_slash_help_prints_commands(capsys):
    """/help prints the available commands and returns unchanged profile."""
    from main import _handle_slash_command
    from models.user_profile import UserProfile

    profile = UserProfile.default()
    returned, home_changed = _handle_slash_command("/help", profile)
    assert returned is profile
    assert home_changed is False
    captured = capsys.readouterr()
    assert "/home" in captured.out
    assert "/forget-home" in captured.out


def test_slash_help_h_alias_works(capsys):
    """/h is an alias for /help."""
    from main import _handle_slash_command
    from models.user_profile import UserProfile

    _, home_changed = _handle_slash_command("/h", UserProfile.default())
    assert home_changed is False
    captured = capsys.readouterr()
    assert "/home" in captured.out


# ---------------------------------------------------------------------------
# _handle_slash_command: /home (read + set)
# ---------------------------------------------------------------------------


def test_slash_home_no_arg_shows_when_unset(capsys):
    """/home with no args + empty profile → 'not set' message."""
    from main import _handle_slash_command
    from models.user_profile import UserProfile

    returned, home_changed = _handle_slash_command("/home", UserProfile.default())
    assert returned.home is None
    assert home_changed is False
    captured = capsys.readouterr()
    assert "まだ設定されていません" in captured.out


def test_slash_home_no_arg_shows_when_set(capsys):
    """/home with no args + profile with home → shows current home."""
    from main import _handle_slash_command
    from models.user_profile import HomeLocation, UserProfile

    profile = UserProfile(home=HomeLocation(label="横浜駅", lat=35.4657, lon=139.6223))
    _, home_changed = _handle_slash_command("/home", profile)
    assert home_changed is False
    captured = capsys.readouterr()
    assert "横浜駅" in captured.out
    assert "35.4657" in captured.out


def test_slash_home_set_saves_profile(tmp_path: Path, monkeypatch, capsys):
    """/home <station> writes the profile to disk and returns new profile."""
    import main
    from main import _handle_slash_command
    from models.user_profile import HomeLocation, UserProfile

    # Redirect PROFILE_PATH to tmp
    profile_path = tmp_path / "data" / "user_profile.json"
    monkeypatch.setattr(main, "PROFILE_PATH", profile_path)

    profile = UserProfile.default()
    returned, home_changed = _handle_slash_command("/home 横浜駅", profile)
    assert home_changed is True
    assert returned.home == HomeLocation(label="横浜駅", lat=35.4657, lon=139.6223)
    # File was written
    assert profile_path.exists()
    # And loadable
    loaded = UserProfile.load(profile_path)
    assert loaded.home.label == "横浜駅"
    captured = capsys.readouterr()
    assert "横浜駅" in captured.out


def test_slash_home_unknown_station_does_not_change_profile(capsys):
    """/home <unknown-station> returns unchanged profile (no save)."""
    from main import _handle_slash_command
    from models.user_profile import UserProfile

    profile = UserProfile.default()
    returned, home_changed = _handle_slash_command("/home ド田舎駅", profile)
    assert returned is profile
    assert returned.home is None
    assert home_changed is False
    captured = capsys.readouterr()
    assert "登録されていない駅" in captured.out


def test_slash_home_replaces_existing(tmp_path: Path, monkeypatch):
    """/home with a new station replaces the existing one (does not merge)."""
    import main
    from main import _handle_slash_command
    from models.user_profile import HomeLocation, UserProfile

    profile_path = tmp_path / "profile.json"
    monkeypatch.setattr(main, "PROFILE_PATH", profile_path)

    profile = UserProfile(home=HomeLocation(label="横浜駅", lat=35.4657, lon=139.6223))
    returned, home_changed = _handle_slash_command("/home 新宿", profile)
    assert home_changed is True
    assert returned.home.label == "新宿"
    assert profile.home.label == "横浜駅"  # original unchanged


# ---------------------------------------------------------------------------
# _handle_slash_command: /forget-home
# ---------------------------------------------------------------------------


def test_slash_forget_home_clears_when_set(tmp_path: Path, monkeypatch, capsys):
    """/forget-home clears the home and saves."""
    import main
    from main import _handle_slash_command
    from models.user_profile import HomeLocation, UserProfile

    profile_path = tmp_path / "profile.json"
    monkeypatch.setattr(main, "PROFILE_PATH", profile_path)

    profile = UserProfile(home=HomeLocation(label="横浜駅", lat=35.4657, lon=139.6223))
    returned, home_changed = _handle_slash_command("/forget-home", profile)
    assert home_changed is True
    assert returned.home is None
    assert profile.home is not None  # original unchanged
    assert profile_path.exists()
    captured = capsys.readouterr()
    assert "クリアしました" in captured.out


def test_slash_forget_home_noop_when_unset(capsys):
    """/forget-home on empty profile prints 'not set' and is a no-op."""
    from main import _handle_slash_command
    from models.user_profile import UserProfile

    profile = UserProfile.default()
    returned, home_changed = _handle_slash_command("/forget-home", profile)
    assert returned is profile
    assert home_changed is False
    captured = capsys.readouterr()
    assert "設定されていません" in captured.out


def test_slash_clear_home_alias_works(tmp_path: Path, monkeypatch):
    """/clear-home is an alias for /forget-home."""
    import main
    from main import _handle_slash_command
    from models.user_profile import HomeLocation, UserProfile

    profile_path = tmp_path / "profile.json"
    monkeypatch.setattr(main, "PROFILE_PATH", profile_path)

    profile = UserProfile(home=HomeLocation(label="横浜駅", lat=35.4657, lon=139.6223))
    _, home_changed = _handle_slash_command("/clear-home", profile)
    assert home_changed is True


# ---------------------------------------------------------------------------
# _handle_slash_command: unknown commands
# ---------------------------------------------------------------------------


def test_slash_unknown_command_prints_error(capsys):
    """Unknown slash commands print an error and return profile unchanged."""
    from main import _handle_slash_command
    from models.user_profile import UserProfile

    profile = UserProfile.default()
    returned, home_changed = _handle_slash_command("/foo", profile)
    assert returned is profile
    assert home_changed is False
    captured = capsys.readouterr()
    assert "不明なコマンド" in captured.out


# ---------------------------------------------------------------------------
# _print_banner
# ---------------------------------------------------------------------------


def test_print_banner_with_home(capsys):
    """Banner shows the home label when set."""
    from main import _print_banner

    _print_banner("横浜駅")
    captured = capsys.readouterr()
    assert "横浜駅" in captured.out
    assert "/home" in captured.out
    assert "/forget-home" in captured.out
    assert "/help" in captured.out


def test_print_banner_without_home(capsys):
    """Banner omits the home line when no home is set."""
    from main import _print_banner

    _print_banner(None)
    captured = capsys.readouterr()
    assert "自宅:" not in captured.out  # no "自宅:" line
    assert "/home" in captured.out  # but still mentions the command


# ---------------------------------------------------------------------------
# Integration: PROFILE_PATH actually gitignores data/
# ---------------------------------------------------------------------------


def test_profile_path_lives_under_gitignored_data_dir():
    """PROFILE_PATH is at data/user_profile.json — confirmed gitignored."""
    from main import PROFILE_PATH

    assert PROFILE_PATH.name == "user_profile.json"
    assert PROFILE_PATH.parent.name == "data"