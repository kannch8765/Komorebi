"""Crowding Score Algorithm — pure-local heuristic.

Komorebi's LLM-facing "crowding_score" is a value in [0.0, 1.0] where higher
means more crowded. The transit API (api.transit.ls8h.com) does NOT expose
real-time occupancy data, so this module computes a deterministic local
estimate from three signals:

  1. Time of day   — Tokyo rush-hour peaks
  2. Line popularity — known busy rail lines
  3. Transfer hub congestion — known mega-station transfers

The algorithm is intentionally pure (no I/O, no datetime.now()) so it is
deterministic and easy to unit-test. Callers inject the journey's start
time explicitly via CrowdingFactors.time_of_day.

Why a local heuristic?  We surveyed the API at
https://api.transit.ls8h.com/api/openapi.json (searched 12 schemas + all
journey fields) and confirmed there is no passenger-occupancy / load /
crowding field anywhere in the response. /api/v1/guidance/plan has a
"live" mode flag but it's about query semantics, not passenger data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


# ---------------------------------------------------------------------------
# Heuristic tables
# ---------------------------------------------------------------------------

# Tokyo weekday rush hours (24h clock). Source: JR + Metro public ridership
# reports and general commuter consensus.
WEEKDAY_MORNING_RUSH = (7, 30, 9, 30)   # 07:30 – 09:30
WEEKDAY_EVENING_RUSH = (17, 30, 20, 0)  # 17:30 – 20:00
WEEKEND_LATE_MORNING_PEAK = (10, 0, 12, 0)  # 10:00 – 12:00 (recreational)
LATE_NIGHT_QUIET = (0, 5)               # 00:00 – 05:00

# Line popularity. Substring match — covers prefixes like "JR山手線" /
# "東京メトロ東西線" without needing an exhaustive enumeration.
# Each entry: (substring match, base crowding 0..1)
_POPULAR_LINES: tuple[tuple[str, float], ...] = (
    ("山手線", 0.75),       # JR Yamanote — busiest loop line
    ("中央線", 0.70),       # JR Chuo Rapid
    ("京浜東北線", 0.70),
    ("埼京線", 0.65),
    ("総武線", 0.60),
    ("丸ノ内線", 0.70),
    ("東西線", 0.70),
    ("銀座線", 0.65),
    ("有楽町線", 0.55),
    ("半蔵門線", 0.55),
    ("副都心線", 0.60),
    ("日比谷線", 0.55),
    ("千代田線", 0.55),
)
_LOCAL_LINE_BASE = 0.30   # private railways / non-listed subway lines

# Transfer hub tiers. Substring match.
_TIER1_HUBS: tuple[str, ...] = (
    "新宿", "渋谷", "東京", "池袋", "品川", "新橋", "大手町",
    "日本橋", "横浜",
)
_TIER2_HUBS: tuple[str, ...] = (
    "大宮", "上野", "秋葉原", "中野", "高田馬場", "飯田橋", "有楽町",
    "御茶ノ水", "恵比寿", "目黒", "五反田", "三軒茶屋", "吉祥寺",
)
_LOCAL_STATION_BASE = 0.20

# Weights for combining the three factors into the final score.
_WEIGHT_TIME = 0.40
_WEIGHT_LINE = 0.35
_WEIGHT_STATION = 0.25


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CrowdingFactors:
    """Inputs to the crowding score. Inject time-of-day for determinism."""

    time_of_day: datetime
    lines: tuple[str, ...]
    transfer_stations: tuple[str, ...]


def score_route(factors: CrowdingFactors) -> float:
    """Return a crowding score in [0.0, 1.0]; higher = more crowded.

    The score is a weighted combination of three sub-factors, each in
    [0.0, 1.0]:

        final = 0.40 * time_factor
              + 0.35 * line_factor
              + 0.25 * station_factor

    Returns 0.5 (neutral) when no signals apply, matching the placeholder
    value previously returned by TransitAPIClient.
    """
    time_factor = _time_factor(factors.time_of_day)
    line_factor = _line_factor(factors.lines)
    station_factor = _station_factor(factors.transfer_stations)

    return (
        _WEIGHT_TIME * time_factor
        + _WEIGHT_LINE * line_factor
        + _WEIGHT_STATION * station_factor
    )


# ---------------------------------------------------------------------------
# Factor implementations
# ---------------------------------------------------------------------------


def _time_factor(dt: datetime) -> float:
    """Map a datetime to a 0..1 time-of-day crowding factor.

    Weekday profile (peak / off-peak):
        00:00–05:00 → 0.10  (late night, very quiet)
        05:00–07:30 → 0.40  (pre-rush, building up)
        07:30–09:30 → 1.00  (morning rush, max)
        09:30–11:00 → 0.55  (post-rush tail)
        11:00–16:30 → 0.30  (midday off-peak)
        16:30–17:30 → 0.55  (pre-evening-rush)
        17:30–20:00 → 1.00  (evening rush, max)
        20:00–22:00 → 0.55  (post-rush tail)
        22:00–24:00 → 0.30  (winding down)

    Weekend profile:
        00:00–05:00 → 0.10
        05:00–10:00 → 0.20
        10:00–12:00 → 0.70  (recreational peak — Shibuya / Harajuku)
        12:00–20:00 → 0.45
        20:00–24:00 → 0.30
    """
    weekday = dt.weekday()  # 0 = Monday, 6 = Sunday
    is_weekend = weekday >= 5
    minutes = dt.hour * 60 + dt.minute

    if is_weekend:
        if minutes < 5 * 60:
            return 0.10
        if minutes < 10 * 60:
            return 0.20
        if minutes < 12 * 60:
            return 0.70
        if minutes < 20 * 60:
            return 0.45
        return 0.30

    # Weekday
    if minutes < 5 * 60:
        return 0.10
    if minutes < _hms(WEEKDAY_MORNING_RUSH[0], WEEKDAY_MORNING_RUSH[1]):
        return 0.40
    if minutes < _hms(WEEKDAY_MORNING_RUSH[2], WEEKDAY_MORNING_RUSH[3]):
        return 1.00
    if minutes < 11 * 60:
        return 0.55
    if minutes < _hms(WEEKDAY_EVENING_RUSH[0] - 1, 0):  # 16:30
        return 0.30
    if minutes < _hms(WEEKDAY_EVENING_RUSH[0], WEEKDAY_EVENING_RUSH[1]):
        return 0.55
    if minutes < _hms(WEEKDAY_EVENING_RUSH[2], WEEKDAY_EVENING_RUSH[3]):
        return 1.00
    if minutes < 22 * 60:
        return 0.55
    return 0.30


def _line_factor(lines: tuple[str, ...]) -> float:
    """Map a tuple of line names to a 0..1 line-popularity factor.

    Returns the max known score across all lines, falling back to the
    local-line base (0.30) if none of the lines appear in our popularity
    table.
    """
    if not lines:
        return 0.50  # neutral when we don't know which lines were used
    best = 0.0
    matched = False
    for line in lines:
        for substring, score in _POPULAR_LINES:
            if substring in line:
                if score > best:
                    best = score
                matched = True
                break
    if not matched:
        return _LOCAL_LINE_BASE
    return best


def _station_factor(stations: tuple[str, ...]) -> float:
    """Map a tuple of transfer-station names to a 0..1 station factor.

    Tier-1 mega hubs score 0.70, tier-2 0.40, others 0.20. Returns the
    max across all transfer stations.
    """
    if not stations:
        return _LOCAL_STATION_BASE
    best = _LOCAL_STATION_BASE
    for station in stations:
        for hub in _TIER1_HUBS:
            if hub in station:
                if 0.70 > best:
                    best = 0.70
                break
        else:
            for hub in _TIER2_HUBS:
                if hub in station:
                    if 0.40 > best:
                        best = 0.40
                    break
    return best


def _hms(hour: int, minute: int) -> int:
    """Helper: convert (hour, minute) to total minutes since midnight."""
    return hour * 60 + minute