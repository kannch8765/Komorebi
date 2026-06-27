"""User preferences — the social-anxiety comfort slider.

Module 10 of Komorebi's plan. Komorebi's users vary in how much exposure
they tolerate. The single most important dimension is the tradeoff
between:

  - Crowding exposure  (do I want to avoid busy lines + rush hour?)
  - Time efficiency    (do I just want the fastest route?)

The slider `exposure_comfort` encodes this tradeoff as an integer 1..5:

  1 → strongly avoid crowds, accept slower routes
  2 → lean toward less-crowded
  3 → balanced (default)
  4 → lean toward faster
  5 → time-only, ignore crowds

The slider maps linearly to weight_crowding in [0.85, 0.15]:

  comfort  weight_crowding  weight_time
     1        0.85            0.15
     2        0.675           0.325
     3        0.50            0.50
     4        0.325           0.675
     5        0.15            0.85

Routes are then ranked by a combined score (lower = better):

  rank_score = w_crowding * normalized_crowding
             + w_time     * normalized_duration

`rank_routes()` applies this to a list of RouteRecommendation and returns
them sorted ascending by rank_score.
"""

from __future__ import annotations

from dataclasses import dataclass

from models.schemas import RouteRecommendation


SLIDER_MIN = 1
SLIDER_MAX = 5
SLIDER_DEFAULT = 3


@dataclass(frozen=True)
class UserPreferences:
    """Komorebi's user-facing preferences.

    Only the exposure_comfort slider is exposed for now. Future fields
    (walking_tolerance, prefer_seated, max_transfers) will be additive.
    """

    exposure_comfort: int = SLIDER_DEFAULT

    def __post_init__(self) -> None:
        if not isinstance(self.exposure_comfort, int) or isinstance(
            self.exposure_comfort, bool
        ):
            raise TypeError(
                f"exposure_comfort must be int, got {type(self.exposure_comfort).__name__}"
            )
        if not (SLIDER_MIN <= self.exposure_comfort <= SLIDER_MAX):
            raise ValueError(
                f"exposure_comfort must be {SLIDER_MIN}..{SLIDER_MAX}, "
                f"got {self.exposure_comfort}"
            )

    @property
    def weight_crowding(self) -> float:
        """How much the ranking should penalize high-crowding routes.

        comfort=1 → 0.85 (crowding dominates)
        comfort=5 → 0.15 (time dominates)
        """
        return 0.85 - 0.175 * (self.exposure_comfort - SLIDER_MIN)

    @property
    def weight_time(self) -> float:
        """How much the ranking should penalize slow routes. 1 - weight_crowding."""
        return 1.0 - self.weight_crowding

    @classmethod
    def default(cls) -> "UserPreferences":
        """Balanced preset (slider=3)."""
        return cls(exposure_comfort=SLIDER_DEFAULT)


def rank_routes(
    routes: list[RouteRecommendation],
    preferences: UserPreferences,
) -> list[RouteRecommendation]:
    """Sort routes by combined crowding + time score.

    Lower rank_score = better fit for the user's preferences. The score
    normalizes each route's duration against the fastest option in the
    list (so a route that takes the same time as the fastest gets
    normalized_time=1.0, and faster options would be <1.0 — we clamp at
    1.0 for the fastest so slower routes are always >= it).

    Args:
        routes:    the route options returned by the transit API.
        preferences: the user's slider setting.

    Returns:
        New list of routes sorted by ascending rank_score (best first).
        Original list is not mutated.
    """
    if not routes:
        return []

    # Normalize duration: best = 1.0, slower > 1.0. Clamp to >= 1.0 so the
    # fastest option gets the lowest possible normalized_time.
    min_duration = min(r.duration_min for r in routes)
    if min_duration <= 0:
        min_duration = 1

    scored = [
        (
            preferences.weight_crowding * r.crowding_score
            + preferences.weight_time * max(1.0, r.duration_min / min_duration),
            r,
        )
        for r in routes
    ]
    # Stable sort so equal scores preserve the original API ordering.
    scored.sort(key=lambda pair: (pair[0], pair[1].name))
    return [r for _, r in scored]