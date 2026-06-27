"""Tests for the crowding-score algorithm.

Pure unit tests — no I/O, no API calls, no LLM. The algorithm is
deterministic given (time_of_day, lines, transfer_stations), so every test
uses frozen datetimes and explicit inputs.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from tools.crowding import CrowdingFactors, score_route


# ---------------------------------------------------------------------------
# Time-of-day factor (weekday)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hour, minute, expected_label",
    [
        (3, 0, "late-night-quiet"),       # 00:00-05:00
        (6, 0, "pre-rush"),                # 05:00-07:30
        (8, 0, "morning-rush-max"),        # 07:30-09:30
        (10, 0, "post-rush-tail"),         # 09:30-11:00
        (13, 0, "midday-off-peak"),        # 11:00-16:30
        (17, 0, "pre-evening-rush"),       # 16:30-17:30
        (18, 30, "evening-rush-max"),      # 17:30-20:00
        (21, 0, "post-evening-tail"),      # 20:00-22:00
        (23, 0, "winding-down"),           # 22:00-24:00
    ],
)
def test_weekday_time_factor_brackets(hour, minute, expected_label):
    """Each weekday time-of-day bracket produces the expected factor."""
    dt = datetime(2026, 6, 22, hour, minute)  # Monday
    factors = CrowdingFactors(time_of_day=dt, lines=(), transfer_stations=())
    score = score_route(factors)
    # Empty lines/stations use neutral defaults: line_factor=0.50, station_factor=0.20.
    # So score = 0.40 * time + 0.35 * 0.50 + 0.25 * 0.20 = 0.40 * time + 0.225
    time_value = {
        "late-night-quiet": 0.10,
        "pre-rush": 0.40,
        "morning-rush-max": 1.00,
        "post-rush-tail": 0.55,
        "midday-off-peak": 0.30,
        "pre-evening-rush": 0.55,
        "evening-rush-max": 1.00,
        "post-evening-tail": 0.55,
        "winding-down": 0.30,
    }[expected_label]
    expected = 0.40 * time_value + 0.35 * 0.50 + 0.25 * 0.20
    assert score == pytest.approx(expected, abs=1e-9)


def test_weekend_late_morning_peak_higher_than_midday():
    """Saturday 11:00 is busier than Saturday 14:00 (recreational peak)."""
    peak_dt = datetime(2026, 6, 27, 11, 0)   # Saturday
    midday_dt = datetime(2026, 6, 27, 14, 0)
    peak_score = score_route(CrowdingFactors(peak_dt, (), ()))
    midday_score = score_route(CrowdingFactors(midday_dt, (), ()))
    assert peak_score > midday_score


def test_sunday_same_profile_as_saturday():
    """Saturday and Sunday use the same weekend time profile."""
    sat = datetime(2026, 6, 27, 11, 0)
    sun = datetime(2026, 6, 28, 11, 0)
    assert score_route(CrowdingFactors(sat, (), ())) == pytest.approx(
        score_route(CrowdingFactors(sun, (), ()))
    )


def test_morning_rush_higher_than_evening_rush_off_peak():
    """08:00 weekday should score higher than 06:00 weekday."""
    rush = score_route(CrowdingFactors(datetime(2026, 6, 22, 8, 0), (), ()))
    pre = score_route(CrowdingFactors(datetime(2026, 6, 22, 6, 0), (), ()))
    assert rush > pre
    # Time factor difference is 1.00 - 0.40 = 0.60 → weighted 0.40 * 0.60 = 0.24
    assert rush - pre >= 0.2


# ---------------------------------------------------------------------------
# Line popularity factor
# ---------------------------------------------------------------------------


def test_yamanote_line_highest_popularity():
    """JR山手線 is in the popularity table at 0.75 → line_factor=0.75."""
    dt = datetime(2026, 6, 22, 13, 0)  # weekday midday (time factor ≈ 0.30)
    factors = CrowdingFactors(dt, ("JR山手線",), ())
    score = score_route(factors)
    # 0.40 * 0.30 (time) + 0.35 * 0.75 (line) + 0.25 * 0.20 (empty stations)
    expected = 0.40 * 0.30 + 0.35 * 0.75 + 0.25 * 0.20
    assert score == pytest.approx(expected, abs=1e-9)


def test_private_railway_low_popularity():
    """Lines not in the popularity table fall back to local base 0.30."""
    dt = datetime(2026, 6, 22, 13, 0)
    factors = CrowdingFactors(dt, ("西武新宿線",), ())
    score = score_route(factors)
    expected = 0.40 * 0.30 + 0.35 * 0.30 + 0.25 * 0.20
    assert score == pytest.approx(expected, abs=1e-9)


def test_mixed_journey_uses_max_line_factor():
    """A journey with a Yamanote leg should inherit Yamanote's high score."""
    dt = datetime(2026, 6, 22, 13, 0)
    factors = CrowdingFactors(
        dt, ("JR山手線", "西武新宿線"), ()  # max should be Yamanote's 0.75
    )
    score = score_route(factors)
    expected = 0.40 * 0.30 + 0.35 * 0.75 + 0.25 * 0.20
    assert score == pytest.approx(expected, abs=1e-9)


def test_unknown_lines_use_neutral_factor():
    """Empty line list → line_factor=0.50 (neutral)."""
    dt = datetime(2026, 6, 22, 13, 0)
    factors = CrowdingFactors(dt, (), ())
    score = score_route(factors)
    expected = 0.40 * 0.30 + 0.35 * 0.50 + 0.25 * 0.20
    assert score == pytest.approx(expected, abs=1e-9)


def test_line_substring_match_works():
    """Longer line names containing the substring should still match."""
    dt = datetime(2026, 6, 22, 13, 0)
    factors = CrowdingFactors(dt, ("東京メトロ東西線 (中野行)",), ())
    score = score_route(factors)
    # 東西線 → 0.70
    expected = 0.40 * 0.30 + 0.35 * 0.70 + 0.25 * 0.20
    assert score == pytest.approx(expected, abs=1e-9)


# ---------------------------------------------------------------------------
# Transfer station factor
# ---------------------------------------------------------------------------


def test_tier1_hub_higher_than_tier2():
    """Shinjuku (tier1=0.70) should score higher than Akihabara (tier2=0.40)."""
    dt = datetime(2026, 6, 22, 3, 0)  # late night (time_factor=0.10)
    f1 = CrowdingFactors(dt, (), ("新宿",))
    f2 = CrowdingFactors(dt, (), ("秋葉原",))
    assert score_route(f1) > score_route(f2)


def test_unknown_station_uses_local_base():
    """Stations not in either tier list fall back to 0.20."""
    dt = datetime(2026, 6, 22, 13, 0)
    factors = CrowdingFactors(dt, (), ("田奈",))  # small Tama station
    score = score_route(factors)
    expected = 0.40 * 0.30 + 0.35 * 0.50 + 0.25 * 0.20
    assert score == pytest.approx(expected, abs=1e-9)


def test_mixed_transfer_stations_uses_max():
    """A journey through both Akihabara (tier2) and Shinjuku (tier1) → 0.70."""
    dt = datetime(2026, 6, 22, 3, 0)
    factors = CrowdingFactors(dt, (), ("秋葉原", "新宿", "中野"))
    score = score_route(factors)
    # station_factor = 0.70
    expected = 0.40 * 0.10 + 0.35 * 0.50 + 0.25 * 0.70
    assert score == pytest.approx(expected, abs=1e-9)


def test_no_transfers_uses_local_base():
    """Empty transfer-stations list → station_factor=0.20 (the local base)."""
    dt = datetime(2026, 6, 22, 13, 0)
    factors = CrowdingFactors(dt, ("JR山手線",), ())
    score = score_route(factors)
    expected = 0.40 * 0.30 + 0.35 * 0.75 + 0.25 * 0.20
    assert score == pytest.approx(expected, abs=1e-9)


# ---------------------------------------------------------------------------
# End-to-end: realistic journey scenarios
# ---------------------------------------------------------------------------


def test_morning_rush_yamanote_through_shinjuku_is_max_crowded():
    """Worst case: 08:30 weekday + Yamanote + Shinjuku transfer → ≥ 0.7."""
    dt = datetime(2026, 6, 22, 8, 30)
    factors = CrowdingFactors(dt, ("JR山手線",), ("新宿",))
    score = score_route(factors)
    assert score >= 0.7


def test_late_night_private_rail_no_transfers_is_min_crowded():
    """Best case: 03:00 + 西武線 + no transfers → ≤ 0.3."""
    dt = datetime(2026, 6, 22, 3, 0)
    factors = CrowdingFactors(dt, ("西武新宿線",), ())
    score = score_route(factors)
    assert score <= 0.3


def test_score_always_in_unit_interval():
    """Sanity: across a grid of inputs the score never leaves [0, 1]."""
    for hour in range(0, 24, 3):
        for weekday in (0, 6):
            dt = datetime(2026, 6, 22 + weekday, hour, 0)
            for lines in ((), ("JR山手線",), ("西武新宿線",)):
                for stations in ((), ("新宿",), ("田奈",), ("秋葉原", "中野")):
                    score = score_route(
                        CrowdingFactors(dt, lines, stations)
                    )
                    assert 0.0 <= score <= 1.0, (
                        f"out of range: hour={hour} weekday={weekday} "
                        f"lines={lines} stations={stations} score={score}"
                    )


# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------


def test_crowding_factors_is_frozen():
    """CrowdingFactors is a frozen dataclass — immutable inputs."""
    dt = datetime(2026, 6, 22, 13, 0)
    f = CrowdingFactors(dt, ("JR山手線",), ("新宿",))
    with pytest.raises((AttributeError, Exception)):
        f.lines = ()  # type: ignore[misc]


def test_score_route_returns_float():
    """score_route returns a float, not a tuple or other type."""
    dt = datetime(2026, 6, 22, 13, 0)
    score = score_route(CrowdingFactors(dt, (), ()))
    assert isinstance(score, float)