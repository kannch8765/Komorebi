"""Tests for user preferences + route ranking (Module 10)."""

from __future__ import annotations

import pytest

from models.schemas import RouteRecommendation
from models.user_preferences import (
    SLIDER_DEFAULT,
    SLIDER_MAX,
    SLIDER_MIN,
    UserPreferences,
    rank_routes,
)


def _route(
    name: str,
    duration_min: int,
    crowding_score: float,
    transfers: int = 0,
) -> RouteRecommendation:
    """Build a RouteRecommendation with sensible defaults for ranking tests."""
    return RouteRecommendation(
        name=name,
        duration_min=duration_min,
        transfers=transfers,
        crowding_score=crowding_score,
        extra_time_min=0,
        stations=[name.split("→")[0], name.split("→")[-1]],
        lines=["test-line"],
    )


# ---------------------------------------------------------------------------
# UserPreferences validation
# ---------------------------------------------------------------------------


def test_default_is_balanced():
    """UserPreferences.default() returns slider=3 (balanced)."""
    assert UserPreferences.default().exposure_comfort == SLIDER_DEFAULT


def test_default_weights_sum_to_one():
    """weight_crowding + weight_time == 1.0 at any slider value."""
    for slider in range(SLIDER_MIN, SLIDER_MAX + 1):
        prefs = UserPreferences(exposure_comfort=slider)
        assert prefs.weight_crowding + prefs.weight_time == pytest.approx(1.0)


@pytest.mark.parametrize("bad_value", [0, 6, -1, 100])
def test_out_of_range_slider_raises(bad_value):
    """exposure_comfort outside 1..5 raises ValueError."""
    with pytest.raises(ValueError, match="exposure_comfort must be"):
        UserPreferences(exposure_comfort=bad_value)


@pytest.mark.parametrize("bad_type_value", [3.5, "3", None, [3], {"v": 3}])
def test_non_int_slider_raises_type_error(bad_type_value):
    """Non-int exposure_comfort raises TypeError."""
    with pytest.raises(TypeError, match="exposure_comfort must be int"):
        UserPreferences(exposure_comfort=bad_type_value)  # type: ignore[arg-type]


def test_explicit_balanced_equals_default():
    """UserPreferences(3) is functionally identical to default()."""
    explicit = UserPreferences(exposure_comfort=3)
    defaults = UserPreferences.default()
    assert explicit == defaults
    assert explicit.weight_crowding == defaults.weight_crowding


def test_frozen_dataclass():
    """UserPreferences is immutable."""
    prefs = UserPreferences(exposure_comfort=3)
    with pytest.raises((AttributeError, Exception)):
        prefs.exposure_comfort = 5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Weight interpolation
# ---------------------------------------------------------------------------


def test_slider_1_maximizes_crowding_weight():
    """Slider 1 → weight_crowding=0.85 (avoid crowds)."""
    assert UserPreferences(exposure_comfort=1).weight_crowding == pytest.approx(0.85)
    assert UserPreferences(exposure_comfort=1).weight_time == pytest.approx(0.15)


def test_slider_5_minimizes_crowding_weight():
    """Slider 5 → weight_crowding=0.15 (time-only)."""
    assert UserPreferences(exposure_comfort=5).weight_crowding == pytest.approx(0.15)
    assert UserPreferences(exposure_comfort=5).weight_time == pytest.approx(0.85)


def test_slider_3_is_balanced():
    """Slider 3 → 50/50 weights."""
    prefs = UserPreferences(exposure_comfort=3)
    assert prefs.weight_crowding == pytest.approx(0.50)
    assert prefs.weight_time == pytest.approx(0.50)


def test_weights_decrease_linearly():
    """weight_crowding decreases linearly across the slider range."""
    weights = [
        UserPreferences(exposure_comfort=s).weight_crowding
        for s in range(SLIDER_MIN, SLIDER_MAX + 1)
    ]
    deltas = [weights[i + 1] - weights[i] for i in range(len(weights) - 1)]
    for d in deltas:
        assert d == pytest.approx(-0.175, abs=1e-9)


# ---------------------------------------------------------------------------
# rank_routes — slider behavior
# ---------------------------------------------------------------------------


def test_rank_empty_list():
    """rank_routes returns [] for empty input."""
    assert rank_routes([], UserPreferences.default()) == []


def test_rank_single_route():
    """rank_routes returns [route] for a single-element input."""
    r = _route("A→B", 30, 0.5)
    assert rank_routes([r], UserPreferences.default()) == [r]


def test_slider_1_prefers_quiet_over_fast():
    """When slider=1 (avoid crowds), the slower-but-quieter route wins."""
    fast_crowded = _route("fast→crowded", duration_min=15, crowding_score=0.9)
    slow_quiet = _route("slow→quiet", duration_min=40, crowding_score=0.2)
    ranked = rank_routes([fast_crowded, slow_quiet], UserPreferences(exposure_comfort=1))
    assert ranked[0].name == "slow→quiet"


def test_slider_5_prefers_fast_over_quiet():
    """When slider=5 (time-only), the faster-but-crowded route wins."""
    fast_crowded = _route("fast→crowded", duration_min=15, crowding_score=0.9)
    slow_quiet = _route("slow→quiet", duration_min=40, crowding_score=0.2)
    ranked = rank_routes([fast_crowded, slow_quiet], UserPreferences(exposure_comfort=5))
    assert ranked[0].name == "fast→crowded"


def test_slider_3_balanced_picks_compromise():
    """When balanced, the option with the best combined score wins.

    With weight_crowding=weight_time=0.5:
      fast_crowded (15min, 0.9 crowding): 0.5*0.9 + 0.5*1.0 = 0.95
      slow_quiet (40min, 0.2 crowding):   0.5*0.2 + 0.5*2.67 = 1.43
      → fast_crowded still wins because 40/15=2.67 is much worse than 0.9/0.2=4.5
        crowding ratio.
    """
    fast_crowded = _route("fast→crowded", duration_min=15, crowding_score=0.9)
    slow_quiet = _route("slow→quiet", duration_min=40, crowding_score=0.2)
    ranked = rank_routes([fast_crowded, slow_quiet], UserPreferences(exposure_comfort=3))
    assert ranked[0].name == "fast→crowded"


def test_balanced_picks_quieter_when_crowding_diff_dominates():
    """With extreme crowding diff + small time diff, balanced picks quieter."""
    # 30min 0.95 vs 32min 0.05
    # balanced:  0.5*0.95 + 0.5*1.0 = 0.975  vs  0.5*0.05 + 0.5*1.067 = 0.558
    # → quieter wins (crowding gap dominates tiny time gap)
    noisy_fast = _route("A→B", duration_min=30, crowding_score=0.95)
    quiet_slow = _route("A→C", duration_min=32, crowding_score=0.05)
    ranked = rank_routes([noisy_fast, quiet_slow], UserPreferences(exposure_comfort=3))
    assert ranked[0].name == "A→C"


def test_rank_does_not_mutate_input():
    """rank_routes returns a new list; the input order is preserved."""
    routes = [
        _route("first", 10, 0.5),
        _route("second", 20, 0.5),
        _route("third", 30, 0.5),
    ]
    original = [r.name for r in routes]
    rank_routes(routes, UserPreferences.default())
    assert [r.name for r in routes] == original


def test_rank_with_equal_scores_preserves_api_order():
    """When all scores are equal, original API ordering is preserved."""
    routes = [
        _route("alpha", 30, 0.5),
        _route("beta", 30, 0.5),
        _route("gamma", 30, 0.5),
    ]
    ranked = rank_routes(routes, UserPreferences.default())
    assert [r.name for r in ranked] == ["alpha", "beta", "gamma"]


def test_rank_handles_zero_duration_gracefully():
    """A route with duration_min=0 doesn't break the normalization."""
    # min_duration fallback in rank_routes clamps to 1
    routes = [
        _route("instant", duration_min=0, crowding_score=0.5),
        _route("normal", duration_min=20, crowding_score=0.5),
    ]
    ranked = rank_routes(routes, UserPreferences.default())
    assert len(ranked) == 2
    # instant gets normalized_time = 1.0, normal = 20.0; both have crowding=0.5
    # → instant wins (lower score)
    assert ranked[0].name == "instant"


def test_rank_higher_slider_tolerates_more_crowding():
    """As slider increases, the same set of routes gets reordered more toward time."""
    routes = [
        _route("quiet_slow", duration_min=45, crowding_score=0.1),
        _route("fast_loud", duration_min=10, crowding_score=0.8),
    ]
    slider1 = rank_routes(routes, UserPreferences(exposure_comfort=1))
    slider5 = rank_routes(routes, UserPreferences(exposure_comfort=5))
    assert slider1[0].name == "quiet_slow"
    assert slider5[0].name == "fast_loud"